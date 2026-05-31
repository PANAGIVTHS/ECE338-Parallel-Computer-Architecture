#!/usr/bin/env python3
"""Interactive nbody FPGA demo UI.

This script runs a small local web UI that draws the latest nbody positions on an
HTML canvas and controls the FPGA through the existing PS UART monitor.  It also
has a deterministic --fake backend so the UI/control path can be tested without a
ZedBoard attached.

Controls in the browser:
  Space / p   play-pause
  n / →       advance exactly one simulation step
  Enter       advance by the current steps-per-frame speed
  + / =       increase steps per frame
  - / _       decrease steps per frame
  [ / ]       decrease/increase target FPS
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

DEMO_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEMO_DIR.parent
PROGRAMS_DIR = REPO_ROOT / "programs"
NBODY_PROGRAM_DIR = PROGRAMS_DIR / "nbody"
BAREMETAL_DIR = REPO_ROOT / "host" / "baremetal"
sys.path.insert(0, str(BAREMETAL_DIR))
sys.path.insert(0, str(PROGRAMS_DIR))
sys.path.insert(0, str(NBODY_PROGRAM_DIR))

from gpgpu_uart import GpgpuUartMonitor, normalize_word, read_mem_file  # type: ignore[import-not-found]  # noqa: E402
from fpga import (  # noqa: E402
    GPU_OUTPUT_BASE_WORDS,
    GPU_OUTPUT_WORDS,
    NUM_BODIES,
    ProgramAdapter,
    int32_from_hex,
)

DEFAULT_HTTP_HOST = "0.0.0.0"
DEFAULT_HTTP_PORT = 8765
DEFAULT_FPS = 12.0
MAX_HISTORY = 400


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def normalize_dmem_updates(updates: Any) -> list[tuple[int, list[str]]]:
    """Normalize adapter DMEM updates to [(offset, normalized_words), ...]."""
    if not updates:
        return []
    if isinstance(updates, tuple) and len(updates) == 2:
        offset, words = updates
        return [(int(offset), [normalize_word(word) for word in words])]
    normalized: list[tuple[int, list[str]]] = []
    for item in updates:
        if not isinstance(item, tuple) or len(item) != 2:
            raise RuntimeError("DMEM updates must be (offset, words) or an iterable of those tuples")
        offset, words = item
        normalized.append((int(offset), [normalize_word(word) for word in words]))
    return normalized


class DmemUpdateCache:
    """Send only DMEM words whose value differs from the last host-written value.

    The PS/PL monitor still accepts contiguous bursts, so changed words are grouped
    into maximal contiguous ranges instead of being sent one word at a time.
    """

    def __init__(self) -> None:
        self.words: dict[int, str] = {}

    def changed_ranges(self, updates: Any) -> list[tuple[int, list[str]]]:
        changed: dict[int, str] = {}
        for offset, words in normalize_dmem_updates(updates):
            for i, word in enumerate(words):
                addr = offset + i
                if self.words.get(addr) != word:
                    changed[addr] = word

        if not changed:
            return []

        ranges: list[tuple[int, list[str]]] = []
        sorted_addrs = sorted(changed)
        start = sorted_addrs[0]
        current_words = [changed[start]]
        prev = start
        for addr in sorted_addrs[1:]:
            if addr == prev + 1:
                current_words.append(changed[addr])
            else:
                ranges.append((start, current_words))
                start = addr
                current_words = [changed[addr]]
            prev = addr
        ranges.append((start, current_words))
        return ranges

    def load_changed(self, uart: GpgpuUartMonitor, updates: Any, *, verbose: bool = False) -> None:
        for offset, words in self.changed_ranges(updates):
            if verbose:
                print(f"[INFO] Loading {len(words)} changed DMEM words at offset {offset}")
            uart.load_dmem_bin(words, offset=offset)
            for i, word in enumerate(words):
                self.words[offset + i] = word


@dataclass
class Frame:
    step: int
    positions: list[tuple[int, int]]
    source: str
    elapsed_ms: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "frame",
            "step": self.step,
            "positions": [[x, y] for x, y in self.positions],
            "source": self.source,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


@dataclass
class SharedState:
    playing: bool = False
    steps_per_frame: int = 1
    target_fps: float = DEFAULT_FPS
    busy: bool = False
    status: str = "initializing"
    backend: str = "fake"
    current_step: int = 0
    frames: list[Frame] = field(default_factory=list)
    clients: list[queue.Queue[str]] = field(default_factory=list)
    stop_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            latest = self.frames[-1].to_json() if self.frames else None
            return {
                "type": "state",
                "playing": self.playing,
                "steps_per_frame": self.steps_per_frame,
                "target_fps": self.target_fps,
                "busy": self.busy,
                "status": self.status,
                "backend": self.backend,
                "current_step": self.current_step,
                "latest": latest,
            }

    def publish(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, separators=(",", ":"))
        dead: list[queue.Queue[str]] = []
        with self.lock:
            for client in self.clients:
                try:
                    client.put_nowait(payload)
                except queue.Full:
                    dead.append(client)
            for client in dead:
                if client in self.clients:
                    self.clients.remove(client)

    def set_status(self, text: str) -> None:
        with self.lock:
            self.status = text
        self.publish(self.snapshot())

    def add_frame(self, frame: Frame) -> None:
        with self.lock:
            self.frames.append(frame)
            if len(self.frames) > MAX_HISTORY:
                del self.frames[: len(self.frames) - MAX_HISTORY]
            self.current_step = frame.step
        self.publish(frame.to_json())
        self.publish(self.snapshot())


class Backend:
    source = "backend"

    def close(self) -> None:
        pass

    def step(self, steps: int) -> Frame:
        raise NotImplementedError


class FakeNbodyBackend(Backend):
    """Software nbody model matching the native C reference update semantics."""

    source = "fake"

    def __init__(self) -> None:
        self.step_count = 0
        self.pos_x = [i * 13 - 208 for i in range(NUM_BODIES)]
        self.pos_y = [((i * 29) & 255) - 128 for i in range(NUM_BODIES)]
        self.vel_x = [((i & 1) << 1) - 1 for i in range(NUM_BODIES)]
        self.vel_y = [(((i >> 1) & 1) << 1) - 1 for i in range(NUM_BODIES)]

    @staticmethod
    def body_mass(i: int) -> int:
        return 1 + (i & 3)

    @staticmethod
    def sign(x: int) -> int:
        return (x > 0) - (x < 0)

    @staticmethod
    def force_weight(dx: int, dy: int) -> int:
        dist = abs(dx) + abs(dy)
        return 1 + int(dist < 96) + (int(dist < 32) << 1)

    def step(self, steps: int) -> Frame:
        start = time.perf_counter()
        for _ in range(steps):
            next_x = [0] * NUM_BODIES
            next_y = [0] * NUM_BODIES
            next_vx = [0] * NUM_BODIES
            next_vy = [0] * NUM_BODIES
            for tid in range(NUM_BODIES):
                xi = self.pos_x[tid]
                yi = self.pos_y[tid]
                ax = 0
                ay = 0
                for j in range(NUM_BODIES):
                    dx = self.pos_x[j] - xi
                    dy = self.pos_y[j] - yi
                    w = self.force_weight(dx, dy) * self.body_mass(j)
                    ax += self.sign(dx) * w
                    ay += self.sign(dy) * w
                next_vx[tid] = self.vel_x[tid] + (ax >> 2)
                next_vy[tid] = self.vel_y[tid] + (ay >> 2)
                next_x[tid] = xi + next_vx[tid]
                next_y[tid] = yi + next_vy[tid]
            self.pos_x = next_x
            self.pos_y = next_y
            self.vel_x = next_vx
            self.vel_y = next_vy
            self.step_count += 1
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return Frame(
            step=self.step_count,
            positions=list(zip(self.pos_x, self.pos_y)),
            source=self.source,
            elapsed_ms=elapsed_ms,
        )


class FpgaUartBackend(Backend):
    source = "fpga-uart"

    def __init__(self, *, port: str, baud: int, imem: Path, skip_load_imem: bool, verbose: bool) -> None:
        self.adapter = ProgramAdapter(program_dir=NBODY_PROGRAM_DIR)
        self.uart = GpgpuUartMonitor(port, baud, verbose=verbose)
        self.dmem_cache = DmemUpdateCache()
        self.verbose = verbose
        self.run_index = 0
        self.current_step = 0
        if not skip_load_imem:
            words = read_mem_file(imem)
            self.uart.load_imem_bin(words, offset=0)
        self.dmem_cache.load_changed(self.uart, self.adapter.initial_dmem(), verbose=verbose)

    def close(self) -> None:
        self.uart.close()

    def _parse_positions(self, words: dict[int, str]) -> list[tuple[int, int]]:
        positions: list[tuple[int, int]] = []
        for body in range(NUM_BODIES):
            x_addr = GPU_OUTPUT_BASE_WORDS + body * 2
            y_addr = x_addr + 1
            if x_addr not in words or y_addr not in words:
                raise RuntimeError(f"Missing FPGA output word for body {body}: DMEM[{x_addr}], DMEM[{y_addr}]")
            positions.append((int32_from_hex(words[x_addr]), int32_from_hex(words[y_addr])))
        return positions

    def step(self, steps: int) -> Frame:
        start = time.perf_counter()
        self.dmem_cache.load_changed(
            self.uart,
            self.adapter.before_run(
                run_index=self.run_index,
                start_step=self.current_step,
                steps=steps,
            ),
            verbose=self.verbose,
        )
        self.uart.run()
        words = self.uart.dump_dmem_bin(count=GPU_OUTPUT_WORDS, offset=GPU_OUTPUT_BASE_WORDS)
        self.uart.done()
        self.current_step += steps
        self.run_index += 1
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return Frame(
            step=self.current_step,
            positions=self._parse_positions(words),
            source=self.source,
            elapsed_ms=elapsed_ms,
        )


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Interactive FPGA nbody</title>
<style>
  :root { color-scheme: dark; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  body { margin: 0; background: #070b14; color: #e5e7eb; display: grid; grid-template-columns: minmax(680px, 1fr) 360px; height: 100vh; overflow: hidden; }
  canvas { width: 100%; height: 100vh; display: block; background: #050816; image-rendering: auto; }
  aside { border-left: 1px solid #273244; padding: 18px; background: linear-gradient(180deg, #0f172a 0%, #0b1020 100%); overflow: auto; box-shadow: -18px 0 42px rgba(0,0,0,.35); }
  button { background: #1f6feb; color: white; border: 0; border-radius: 8px; padding: 10px 12px; margin: 4px; cursor: pointer; font-weight: 700; }
  button.secondary { background: #334155; }
  button.warn { background: #a16207; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .metric { padding: 10px; border: 1px solid #263348; border-radius: 8px; background: #111827; margin: 8px 0; }
  .label { color: #9ca3af; font-size: 12px; }
  .value { color: #f8fafc; font-size: 18px; margin-top: 4px; }
  kbd { background:#1f2937; border:1px solid #4b5563; border-bottom-width:2px; padding:2px 6px; border-radius:4px; }
  .ok { color:#34d399; } .busy { color:#fbbf24; } .err { color:#f87171; }
</style>
</head>
<body>
<canvas id="view" width="1200" height="900"></canvas>
<aside>
  <h1>nbody FPGA interactive</h1>
  <div class="grid">
    <button id="play">▶ Play/Pause</button>
    <button id="step1" class="secondary">Step 1</button>
    <button id="stepspeed" class="secondary">Step speed</button>
    <button id="faster" class="secondary">Speed +</button>
    <button id="slower" class="secondary">Speed -</button>
    <button id="clear" class="warn">Clear trail</button>
  </div>
  <div class="metric"><div class="label">Status</div><div id="status" class="value">connecting...</div></div>
  <div class="grid">
    <div class="metric"><div class="label">Backend</div><div id="backend" class="value">?</div></div>
    <div class="metric"><div class="label">Step</div><div id="step" class="value">0</div></div>
    <div class="metric"><div class="label">Steps/frame</div><div id="spf" class="value">1</div></div>
    <div class="metric"><div class="label">Target FPS</div><div id="fps" class="value">?</div></div>
    <div class="metric"><div class="label">Last FPGA/UI chunk</div><div id="elapsed" class="value">?</div></div>
    <div class="metric"><div class="label">Frames</div><div id="frames" class="value">0</div></div>
  </div>
  <h2>Keyboard</h2>
  <p><kbd>Space</kbd>/<kbd>p</kbd> play/pause</p>
  <p><kbd>n</kbd>/<kbd>→</kbd> step by one</p>
  <p><kbd>Enter</kbd> step by current speed</p>
  <p><kbd>+</kbd>/<kbd>-</kbd> change steps per frame</p>
  <p><kbd>[</kbd>/<kbd>]</kbd> change target FPS</p>
  <p>Rendering uses browser Canvas + requestAnimationFrame; FPGA data arrives over Server-Sent Events.</p>
</aside>
<script>
const canvas = document.getElementById('view');
const ctx = canvas.getContext('2d', { alpha: false });
let state = {};
let trail = [];
let latest = null;
let dpr = 1;
let viewW = 1200;
let viewH = 900;
let stars = [];
let camera = null;
const colors = ['#ffd700','#38bdf8','#fb7185','#4ade80','#e879f9','#22d3ee','#f472b6','#a3e635'];

function resizeCanvas() {
  dpr = Math.max(1, Math.min(window.devicePixelRatio || 1, 2.5));
  const rect = canvas.getBoundingClientRect();
  viewW = Math.max(1, Math.floor(rect.width));
  viewH = Math.max(1, Math.floor(rect.height));
  const nextW = Math.floor(viewW * dpr);
  const nextH = Math.floor(viewH * dpr);
  if (canvas.width !== nextW || canvas.height !== nextH) {
    canvas.width = nextW;
    canvas.height = nextH;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    buildStars();
  }
}
function buildStars() {
  stars = [];
  let seed = 0x12345678;
  const rand = () => {
    seed = (1664525 * seed + 1013904223) >>> 0;
    return seed / 0x100000000;
  };
  for (let i = 0; i < 180; i++) {
    stars.push({x: rand() * viewW, y: rand() * viewH, r: 0.35 + rand() * 1.2, a: 0.12 + rand() * 0.38});
  }
}
window.addEventListener('resize', resizeCanvas);
resizeCanvas();

function post(action, body={}) {
  return fetch('/control', {method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({action, ...body})});
}
function setText(id, text) { document.getElementById(id).textContent = text; }
function updatePanel() {
  setText('status', `${state.busy ? 'busy: ' : ''}${state.status || 'unknown'} ${state.playing ? '▶' : '⏸'}`);
  setText('backend', state.backend || '?');
  setText('step', state.current_step ?? 0);
  setText('spf', state.steps_per_frame ?? '?');
  setText('fps', state.target_fps ?? '?');
  setText('frames', trail.length);
  if (latest) setText('elapsed', `${latest.elapsed_ms} ms`);
}
function ingestFrame(frame) {
  latest = frame;
  trail.push(frame);
  if (trail.length > 400) trail.shift();
  updatePanel();
}
function boundsForFrames(frames) {
  let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
  for (const frame of frames) for (const [x,y] of frame.positions) {
    minX=Math.min(minX,x); maxX=Math.max(maxX,x); minY=Math.min(minY,y); maxY=Math.max(maxY,y);
  }
  if (!isFinite(minX)) return null;
  if (minX === maxX) maxX = minX + 1;
  if (minY === maxY) maxY = minY + 1;
  return {minX,maxX,minY,maxY,cx:(minX+maxX)/2,cy:(minY+maxY)/2,span:Math.max(maxX-minX, maxY-minY, 120)};
}
function worldMap() {
  const recent = trail.slice(-120);
  const b = boundsForFrames(recent.length ? recent : trail);
  if (!b) return {sx:x=>x, sy:y=>y, scale:1};
  const margin = 86;
  const target = {cx:b.cx, cy:b.cy, span:b.span * 1.24};
  if (!camera) camera = target;
  const alpha = 0.12;
  camera = {
    cx: camera.cx + (target.cx - camera.cx) * alpha,
    cy: camera.cy + (target.cy - camera.cy) * alpha,
    span: camera.span + (target.span - camera.span) * alpha,
  };
  const drawableW = Math.max(1, viewW - 2 * margin);
  const drawableH = Math.max(1, viewH - 2 * margin);
  const scale = Math.min(drawableW, drawableH) / Math.max(camera.span, 1);
  return {
    sx: x => viewW / 2 + (x - camera.cx) * scale,
    sy: y => viewH / 2 - (y - camera.cy) * scale,
    scale,
  };
}
function drawBackground() {
  const bg = ctx.createRadialGradient(viewW * 0.46, viewH * 0.42, 20, viewW * 0.50, viewH * 0.50, Math.max(viewW, viewH) * 0.78);
  bg.addColorStop(0, '#172554');
  bg.addColorStop(0.42, '#0b1220');
  bg.addColorStop(1, '#020617');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, viewW, viewH);

  ctx.save();
  for (const s of stars) {
    ctx.globalAlpha = s.a;
    ctx.fillStyle = '#dbeafe';
    ctx.beginPath();
    ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  ctx.save();
  ctx.strokeStyle = 'rgba(148,163,184,.11)';
  ctx.lineWidth = 1;
  const spacing = 72;
  for (let x = 0; x < viewW; x += spacing) { ctx.beginPath(); ctx.moveTo(x+.5,0); ctx.lineTo(x+.5,viewH); ctx.stroke(); }
  for (let y = 0; y < viewH; y += spacing) { ctx.beginPath(); ctx.moveTo(0,y+.5); ctx.lineTo(viewW,y+.5); ctx.stroke(); }
  ctx.restore();
}
function drawOverlay() {
  const text = latest ? `step ${latest.step}   ${state.backend || latest.source}   ${state.playing ? 'playing' : 'paused'}   ${state.steps_per_frame || 1} step/frame` : 'waiting for frame...';
  ctx.save();
  ctx.font = '600 16px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';
  const w = ctx.measureText(text).width + 34;
  ctx.fillStyle = 'rgba(2,6,23,.62)';
  ctx.strokeStyle = 'rgba(148,163,184,.28)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(20, 18, w, 42, 14);
  ctx.fill(); ctx.stroke();
  ctx.fillStyle = '#e5e7eb';
  ctx.fillText(text, 37, 44);
  ctx.restore();
}
function draw() {
  resizeCanvas();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, viewW, viewH);
  drawBackground();
  const map = worldMap();
  if (trail.length) {
    const bodies = trail[trail.length-1].positions.length;
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    for (let b=0; b<bodies; b++) {
      let prev = null;
      for (let i=Math.max(1, trail.length - 180); i<trail.length; i++) {
        const p0 = trail[i-1].positions[b];
        const p1 = trail[i].positions[b];
        if (!p0 || !p1) continue;
        const age = (i - Math.max(1, trail.length - 180)) / Math.min(180, Math.max(1, trail.length - 1));
        ctx.beginPath();
        ctx.moveTo(map.sx(p0[0]), map.sy(p0[1]));
        ctx.lineTo(map.sx(p1[0]), map.sy(p1[1]));
        ctx.strokeStyle = colors[b % colors.length] + Math.floor(38 + age * 150).toString(16).padStart(2, '0');
        ctx.lineWidth = (b === 0 ? 2.8 : 1.55) + age * .45;
        ctx.stroke();
        prev = p1;
      }
    }
    ctx.restore();
  }
  if (latest) {
    latest.positions.forEach(([x0,y0], b) => {
      const x = map.sx(x0), y = map.sy(y0);
      const radius = b === 0 ? 11 : 5.6;
      ctx.save();
      ctx.shadowColor = b === 0 ? '#fde68a' : colors[b % colors.length];
      ctx.shadowBlur = b === 0 ? 22 : 12;
      ctx.beginPath(); ctx.arc(x, y, radius + 2.8, 0, Math.PI*2);
      ctx.fillStyle = b === 0 ? 'rgba(250,204,21,.22)' : colors[b % colors.length] + '35';
      ctx.fill();
      ctx.shadowBlur = 0;
      const g = ctx.createRadialGradient(x - radius*.35, y - radius*.45, 1, x, y, radius);
      if (b === 0) { g.addColorStop(0, '#fef3c7'); g.addColorStop(.45, '#111827'); g.addColorStop(1, '#020617'); }
      else { g.addColorStop(0, '#ffffff'); g.addColorStop(.22, colors[b % colors.length]); g.addColorStop(1, '#0f172a'); }
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI*2);
      ctx.fillStyle = g; ctx.fill();
      ctx.strokeStyle = b === 0 ? '#facc15' : 'rgba(15,23,42,.95)'; ctx.lineWidth = b === 0 ? 2.2 : 1.5; ctx.stroke();
      ctx.restore();
    });
  }
  drawOverlay();
  requestAnimationFrame(draw);
}

new EventSource('/events').onmessage = ev => {
  const msg = JSON.parse(ev.data);
  if (msg.type === 'frame') ingestFrame(msg);
  if (msg.type === 'state') { state = msg; if (msg.latest && !latest) ingestFrame(msg.latest); updatePanel(); }
  if (msg.type === 'error') { state.status = msg.message; updatePanel(); }
};
fetch('/state').then(r => r.json()).then(s => { state=s; if (s.latest) ingestFrame(s.latest); updatePanel(); });
document.getElementById('play').onclick = () => post('toggle_play');
document.getElementById('step1').onclick = () => post('step_one');
document.getElementById('stepspeed').onclick = () => post('step_speed');
document.getElementById('faster').onclick = () => post('speed_up');
document.getElementById('slower').onclick = () => post('speed_down');
document.getElementById('clear').onclick = () => { trail = latest ? [latest] : []; updatePanel(); };
document.addEventListener('keydown', ev => {
  if (ev.target && ['INPUT','TEXTAREA'].includes(ev.target.tagName)) return;
  if (ev.key === ' ' || ev.key === 'p') { ev.preventDefault(); post('toggle_play'); }
  else if (ev.key === 'n' || ev.key === 'ArrowRight') { ev.preventDefault(); post('step_one'); }
  else if (ev.key === 'Enter') { ev.preventDefault(); post('step_speed'); }
  else if (ev.key === '+' || ev.key === '=') { ev.preventDefault(); post('speed_up'); }
  else if (ev.key === '-' || ev.key === '_') { ev.preventDefault(); post('speed_down'); }
  else if (ev.key === '[') { ev.preventDefault(); post('fps_down'); }
  else if (ev.key === ']') { ev.preventDefault(); post('fps_up'); }
});
requestAnimationFrame(draw);
</script>
</body>
</html>
"""


class ControlServer(ThreadingHTTPServer):
    def __init__(self, addr, handler, *, state: SharedState, commands: "queue.Queue[tuple[str, Any]]"):
        super().__init__(addr, handler)
        self.state = state
        self.commands = commands


class Handler(BaseHTTPRequestHandler):
    server: ControlServer  # type: ignore[assignment]

    def log_message(self, format: str, *args) -> None:
        if getattr(self.server, "quiet", False):
            return
        super().log_message(format, *args)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(HTTPStatus.OK, HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif parsed.path == "/state":
            self._send(HTTPStatus.OK, json.dumps(self.server.state.snapshot()).encode(), "application/json")
        elif parsed.path == "/events":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q: queue.Queue[str] = queue.Queue(maxsize=100)
            with self.server.state.lock:
                self.server.state.clients.append(q)
            try:
                self.wfile.write(f"data: {json.dumps(self.server.state.snapshot())}\n\n".encode())
                self.wfile.flush()
                while not self.server.state.stop_event.is_set():
                    try:
                        payload = q.get(timeout=10.0)
                    except queue.Empty:
                        payload = json.dumps({"type": "ping", "time": time.time()})
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with self.server.state.lock:
                    if q in self.server.state.clients:
                        self.server.state.clients.remove(q)
        else:
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/control":
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        ctype = self.headers.get("Content-Type", "")
        if "application/json" in ctype:
            data = json.loads(raw.decode("utf-8") or "{}")
        else:
            data = {k: v[-1] for k, v in parse_qs(raw.decode("utf-8")).items()}
        action = data.get("action")
        if not isinstance(action, str):
            self._send(HTTPStatus.BAD_REQUEST, b"missing action", "text/plain")
            return
        self.server.commands.put((action, data))
        self._send(HTTPStatus.OK, json.dumps({"ok": True}).encode(), "application/json")


def apply_control(state: SharedState, commands: "queue.Queue[tuple[str, Any]]") -> int | None:
    """Apply pending UI commands. Return a manual step count if requested."""
    manual_step: int | None = None
    while True:
        try:
            action, data = commands.get_nowait()
        except queue.Empty:
            break
        with state.lock:
            if action == "toggle_play":
                state.playing = not state.playing
            elif action == "play":
                state.playing = True
            elif action == "pause":
                state.playing = False
            elif action == "step_one":
                state.playing = False
                manual_step = 1
            elif action == "step_speed":
                state.playing = False
                manual_step = state.steps_per_frame
            elif action == "speed_up":
                state.steps_per_frame = clamp(state.steps_per_frame * 2, 1, 10240)
            elif action == "speed_down":
                state.steps_per_frame = clamp(max(1, state.steps_per_frame // 2), 1, 10240)
            elif action == "fps_up":
                state.target_fps = min(60.0, state.target_fps + 1.0)
            elif action == "fps_down":
                state.target_fps = max(1.0, state.target_fps - 1.0)
            elif action == "set_speed":
                state.steps_per_frame = clamp(int(data.get("steps_per_frame", state.steps_per_frame)), 1, 4096)
            elif action == "set_fps":
                state.target_fps = float(max(1.0, min(60.0, float(data.get("target_fps", state.target_fps)))))
            else:
                state.status = f"ignored unknown action: {action}"
        state.publish(state.snapshot())
    return manual_step


def worker_loop(state: SharedState, commands: "queue.Queue[tuple[str, Any]]", backend: Backend) -> None:
    state.set_status("ready")
    try:
        while not state.stop_event.is_set():
            manual_step = apply_control(state, commands)
            with state.lock:
                playing = state.playing
                steps = state.steps_per_frame
                target_fps = state.target_fps
            steps_to_run = manual_step if manual_step is not None else (steps if playing else 0)
            if steps_to_run <= 0:
                time.sleep(0.03)
                continue
            with state.lock:
                state.busy = True
                state.status = f"running {steps_to_run} step(s)"
            state.publish(state.snapshot())
            frame = backend.step(steps_to_run)
            state.add_frame(frame)
            with state.lock:
                state.busy = False
                state.status = "ready"
            state.publish(state.snapshot())
            if playing:
                delay = max(0.0, (1.0 / target_fps) - (frame.elapsed_ms / 1000.0))
                time.sleep(delay)
    except Exception as exc:  # keep server alive so the browser shows the failure
        with state.lock:
            state.busy = False
            state.playing = False
            state.status = f"ERROR: {exc}"
        state.publish({"type": "error", "message": str(exc)})
        state.publish(state.snapshot())
    finally:
        backend.close()


def default_imem() -> Path:
    return NBODY_PROGRAM_DIR / "nbody_instructions.mem"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interactive browser/keyboard UI for the FPGA nbody demo")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fake", action="store_true", help="Use a software backend instead of UART/FPGA")
    mode.add_argument("--port", help="UART serial port for the ZedBoard PS monitor, e.g. /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--imem", type=Path, default=default_imem())
    parser.add_argument("--skip-load-imem", action="store_true")
    parser.add_argument("--steps-per-frame", type=int, default=1)
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS)
    parser.add_argument("--http-host", default=DEFAULT_HTTP_HOST)
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.fake and not args.port:
        raise SystemExit("Choose --fake for local testing or pass --port /dev/tty... for FPGA UART mode")
    state = SharedState(
        steps_per_frame=clamp(args.steps_per_frame, 1, 10240),
        target_fps=max(1.0, min(60.0, args.fps)),
        backend="fake" if args.fake else "fpga-uart",
    )
    commands: queue.Queue[tuple[str, Any]] = queue.Queue()
    if args.fake:
        backend: Backend = FakeNbodyBackend()
        state.add_frame(backend.step(0))
    else:
        backend = FpgaUartBackend(
            port=args.port,
            baud=args.baud,
            imem=args.imem,
            skip_load_imem=args.skip_load_imem,
            verbose=args.verbose,
        )
    worker = threading.Thread(target=worker_loop, args=(state, commands, backend), daemon=True)
    worker.start()
    server = ControlServer((args.http_host, args.http_port), Handler, state=state, commands=commands)
    url = f"http://{args.http_host}:{args.http_port}/"
    print(f"[INFO] Interactive nbody UI: {url}", flush=True)
    print("[INFO] Browser keys: Space play/pause, n step one, Enter step by speed, +/- speed", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down")
    finally:
        state.stop_event.set()
        server.shutdown()
        worker.join(timeout=2.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
