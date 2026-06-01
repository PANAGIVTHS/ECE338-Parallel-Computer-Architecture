#!/usr/bin/env python3
"""Interactive nbody-3d demo UI using three.js.

This is intentionally independent of the future nbody-3d FPGA adapter.  It gives
us the browser/controls path now with a deterministic software backend; once
programs/nbody-3d/fpga.py exists, an FPGA backend can be wired in without
changing the three.js frontend protocol.

Controls in the browser:
  Mouse drag  orbit/rotate camera
  Scroll      zoom camera
  Space / p   play-pause
  n / →       advance exactly one simulation step
  Enter       advance by the current steps-per-frame speed
  r           reset to the initial 3D environment
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
from typing import Any
from urllib.parse import parse_qs, urlparse

DEMO_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEMO_DIR.parent
PROGRAM_DIR = REPO_ROOT / "programs" / "nbody-3d"
VENDOR_DIR = DEMO_DIR / "vendor"
DATASET_DIR = PROGRAM_DIR / "datasets"
BAREMETAL_DIR = REPO_ROOT / "host" / "baremetal"
if str(BAREMETAL_DIR) not in sys.path:
    sys.path.insert(0, str(BAREMETAL_DIR))

NUM_BODIES = 32
DEFAULT_HTTP_HOST = "0.0.0.0"
DEFAULT_HTTP_PORT = 8765
DEFAULT_FPS = 12.0
MAX_HISTORY = 500
GPU_ARGS_BASE_WORDS = 0x00000040 // 4
GPU_ARGS_WORDS = 4
DEFAULT_DATA_BASE_BYTES = 0x00001000
DEFAULT_DATA_LIMIT_BYTES = 0x00001800
STATE_WORDS = NUM_BODIES * 7          # pos_x,pos_y,pos_z,vel_x,vel_y,vel_z,mass
POSITION_OUTPUT_WORDS = NUM_BODIES * 3 # pos_x,pos_y,pos_z


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def parse_int_auto(value: str) -> int:
    return int(value, 0)


def u32_hex(value: int) -> str:
    return f"{value & 0xFFFFFFFF:08x}"


def int32_from_hex(word: str) -> int:
    value = int(word, 16) & 0xFFFFFFFF
    if value & 0x80000000:
        value -= 0x100000000
    return value


@dataclass(frozen=True)
class Dataset:
    name: str
    description: str
    pos_x: list[int]
    pos_y: list[int]
    pos_z: list[int]
    vel_x: list[int]
    vel_y: list[int]
    vel_z: list[int]
    masses: list[int]


def resolve_dataset_path(dataset: str | Path) -> Path:
    """Resolve a dataset name/path for the fake backend only."""
    raw = Path(dataset)
    candidates: list[Path]
    if raw.is_absolute() or raw.parent != Path("."):
        candidates = [raw]
    else:
        suffix_name = raw.name if raw.suffix == ".json" else f"{raw.name}.json"
        candidates = [DATASET_DIR / suffix_name]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    choices = ", ".join(sorted(p.stem for p in DATASET_DIR.glob("*.json"))) or "<none>"
    raise FileNotFoundError(f"dataset {dataset!s} not found; available datasets: {choices}")


def _int_triplet(value: Any, *, label: str) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must be a 3-element list")
    try:
        return int(value[0]), int(value[1]), int(value[2])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain integer values") from exc


def load_dataset(dataset: str | Path) -> Dataset:
    path = resolve_dataset_path(dataset)
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    bodies = raw.get("bodies") if isinstance(raw, dict) else None
    if not isinstance(bodies, list) or len(bodies) != NUM_BODIES:
        raise ValueError(f"{path} must contain exactly {NUM_BODIES} bodies")

    pos_x: list[int] = []
    pos_y: list[int] = []
    pos_z: list[int] = []
    vel_x: list[int] = []
    vel_y: list[int] = []
    vel_z: list[int] = []
    masses: list[int] = []
    for i, body in enumerate(bodies):
        if not isinstance(body, dict):
            raise ValueError(f"{path}: body {i} must be an object")
        px, py, pz = _int_triplet(body.get("pos"), label=f"{path}: body {i} pos")
        vx, vy, vz = _int_triplet(body.get("vel"), label=f"{path}: body {i} vel")
        if "mass" not in body:
            raise ValueError(f"{path}: body {i} is missing mass")
        try:
            mass = int(body["mass"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path}: body {i} mass must be an integer") from exc
        if mass <= 0:
            raise ValueError(f"{path}: body {i} mass must be positive")
        pos_x.append(px); pos_y.append(py); pos_z.append(pz)
        vel_x.append(vx); vel_y.append(vy); vel_z.append(vz)
        masses.append(mass)
    return Dataset(
        name=str(raw.get("name") or path.stem),
        description=str(raw.get("description") or ""),
        pos_x=pos_x,
        pos_y=pos_y,
        pos_z=pos_z,
        vel_x=vel_x,
        vel_y=vel_y,
        vel_z=vel_z,
        masses=masses,
    )


@dataclass
class Frame:
    step: int
    positions: list[tuple[int, int, int]]
    source: str
    elapsed_ms: float = 0.0
    masses: list[int] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        event = {
            "type": "frame",
            "step": self.step,
            "positions": [[x, y, z] for x, y, z in self.positions],
            "source": self.source,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }
        if self.masses:
            event["masses"] = list(self.masses)
        return event


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

    def replace_with_frame(self, frame: Frame) -> None:
        with self.lock:
            self.frames = [frame]
            self.current_step = frame.step
        self.publish({"type": "reset", "frame": frame.to_json()})
        self.publish(frame.to_json())
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

    def reset(self) -> Frame:
        raise NotImplementedError

    def step(self, steps: int) -> Frame:
        raise NotImplementedError


class FakeNbody3DBackend(Backend):
    """Software nbody-3d model matching the current C reference formulas."""

    source = "fake"

    def __init__(self, dataset: Dataset) -> None:
        self.dataset = dataset
        self.step_count = 0
        self.pos_x: list[int] = []
        self.pos_y: list[int] = []
        self.pos_z: list[int] = []
        self.vel_x: list[int] = []
        self.vel_y: list[int] = []
        self.vel_z: list[int] = []
        self.masses: list[int] = []
        self.reset()

    def body_mass(self, i: int) -> int:
        return self.masses[i]

    @staticmethod
    def sign(x: int) -> int:
        return (x > 0) - (x < 0)

    @staticmethod
    def force_weight(dx: int, dy: int, dz: int) -> int:
        dist = abs(dx) + abs(dy) + abs(dz)
        return 1 + int(dist < 96) + (int(dist < 32) << 1)

    def reset(self) -> Frame:
        self.step_count = 0
        self.pos_x = list(self.dataset.pos_x)
        self.pos_y = list(self.dataset.pos_y)
        self.pos_z = list(self.dataset.pos_z)
        self.vel_x = list(self.dataset.vel_x)
        self.vel_y = list(self.dataset.vel_y)
        self.vel_z = list(self.dataset.vel_z)
        self.masses = list(self.dataset.masses)
        return Frame(
            step=0,
            positions=list(zip(self.pos_x, self.pos_y, self.pos_z)),
            source=self.source,
            elapsed_ms=0.0,
            masses=list(self.masses),
        )

    def step(self, steps: int) -> Frame:
        start = time.perf_counter()
        for _ in range(steps):
            next_x = [0] * NUM_BODIES
            next_y = [0] * NUM_BODIES
            next_z = [0] * NUM_BODIES
            next_vx = [0] * NUM_BODIES
            next_vy = [0] * NUM_BODIES
            next_vz = [0] * NUM_BODIES
            for tid in range(NUM_BODIES):
                xi = self.pos_x[tid]
                yi = self.pos_y[tid]
                zi = self.pos_z[tid]
                ax = ay = az = 0
                for j in range(NUM_BODIES):
                    dx = self.pos_x[j] - xi
                    dy = self.pos_y[j] - yi
                    dz = self.pos_z[j] - zi
                    w = self.force_weight(dx, dy, dz) * self.body_mass(j)
                    ax += self.sign(dx) * w
                    ay += self.sign(dy) * w
                    az += self.sign(dz) * w
                ax_mask = ax >> 31
                ay_mask = ay >> 31
                az_mask = az >> 31
                next_vx[tid] = self.vel_x[tid] + ((ax + (ax_mask & 3)) >> 2)
                next_vy[tid] = self.vel_y[tid] + ((ay + (ay_mask & 3)) >> 2)
                next_vz[tid] = self.vel_z[tid] + ((az + (az_mask & 3)) >> 2)
                next_x[tid] = xi + next_vx[tid]
                next_y[tid] = yi + next_vy[tid]
                next_z[tid] = zi + next_vz[tid]
            self.pos_x = next_x
            self.pos_y = next_y
            self.pos_z = next_z
            self.vel_x = next_vx
            self.vel_y = next_vy
            self.vel_z = next_vz
            self.step_count += 1
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return Frame(
            step=self.step_count,
            positions=list(zip(self.pos_x, self.pos_y, self.pos_z)),
            source=self.source,
            elapsed_ms=elapsed_ms,
            masses=list(self.masses),
        )


class FpgaNbody3DBackend(Backend):
    """UART/FPGA backend for the pointer-based nbody-3d ABI.

    Startup/reset flow:
      1. load IMEM once when the backend is constructed, unless skipped
      2. load the dataset into DMEM at --data-base
      3. pass that byte pointer through GPGPU_ARGS[0]

    Per displayed frame:
      1. write GPGPU_ARGS = [data_base, steps, 0, 0]
      2. run the kernel
      3. dump pos_x,pos_y,pos_z from the same base region
      4. send done so the monitor returns to loading state
    """

    source = "fpga-uart"

    def __init__(
        self,
        *,
        port: str,
        baud: int,
        imem: Path,
        dataset: Dataset,
        data_base_bytes: int = DEFAULT_DATA_BASE_BYTES,
        data_limit_bytes: int = DEFAULT_DATA_LIMIT_BYTES,
        skip_load_imem: bool = False,
        verbose: bool = False,
    ) -> None:
        if data_base_bytes % 4 != 0:
            raise ValueError("--data-base must be 4-byte aligned")
        if data_limit_bytes % 4 != 0:
            raise ValueError("--data-limit must be 4-byte aligned")
        if data_limit_bytes <= data_base_bytes:
            raise ValueError("--data-limit must be greater than --data-base")
        available_words = (data_limit_bytes - data_base_bytes) // 4
        if available_words < STATE_WORDS:
            raise ValueError(
                f"nbody-3d needs {STATE_WORDS} words at --data-base for "
                "pos_x,pos_y,pos_z,vel_x,vel_y,vel_z,mass, "
                f"but only {available_words} are available"
            )

        try:
            from gpgpu_uart import GpgpuUartMonitor, read_mem_file
        except ImportError as exc:
            raise RuntimeError(
                "FPGA backend requires host/baremetal/gpgpu_uart.py and pyserial. "
                "Install pyserial in the active environment if import failed because serial is missing."
            ) from exc

        self.dataset = dataset
        imem = imem if imem.is_absolute() else REPO_ROOT / imem
        self.data_base_bytes = data_base_bytes
        self.data_base_words = data_base_bytes // 4
        self.step_count = 0
        self.previous_kernel_args: list[str] | None = None
        self.uart = GpgpuUartMonitor(port, baud, verbose=verbose)

        if not skip_load_imem:
            program_words = read_mem_file(imem)
            if verbose:
                print(f"[INFO] Loading {len(program_words)} IMEM word(s) from {imem}", flush=True)
            self.uart.load_imem_bin(program_words, offset=0)
        elif verbose:
            print("[INFO] Skipping IMEM load", flush=True)

    @staticmethod
    def dataset_state_words(dataset: Dataset) -> list[str]:
        words: list[int] = []
        words.extend(dataset.pos_x)
        words.extend(dataset.pos_y)
        words.extend(dataset.pos_z)
        words.extend(dataset.vel_x)
        words.extend(dataset.vel_y)
        words.extend(dataset.vel_z)
        words.extend(dataset.masses)
        if len(words) != STATE_WORDS:
            raise ValueError(f"internal error: expected {STATE_WORDS} state words, got {len(words)}")
        return [u32_hex(word) for word in words]

    def close(self) -> None:
        self.uart.close()

    def _load_kernel_args(self, *, steps: int) -> None:
        args = [
            u32_hex(self.data_base_bytes),
            u32_hex(steps),
            u32_hex(0),
            u32_hex(0),
        ]
        if args != self.previous_kernel_args:
            self.uart.load_dmem_bin(args, offset=GPU_ARGS_BASE_WORDS)
            self.previous_kernel_args = args

    def _read_positions(self) -> list[tuple[int, int, int]]:
        words = self.uart.dump_dmem_bin(count=POSITION_OUTPUT_WORDS, offset=self.data_base_words)
        pos_x_word = self.data_base_words
        pos_y_word = pos_x_word + NUM_BODIES
        pos_z_word = pos_y_word + NUM_BODIES
        positions: list[tuple[int, int, int]] = []
        for body in range(NUM_BODIES):
            x_addr = pos_x_word + body
            y_addr = pos_y_word + body
            z_addr = pos_z_word + body
            if x_addr not in words or y_addr not in words or z_addr not in words:
                raise RuntimeError(
                    f"Missing nbody-3d output words for body {body}: "
                    f"DMEM[{x_addr}], DMEM[{y_addr}], DMEM[{z_addr}]"
                )
            positions.append((
                int32_from_hex(words[x_addr]),
                int32_from_hex(words[y_addr]),
                int32_from_hex(words[z_addr]),
            ))
        return positions

    def reset(self) -> Frame:
        start = time.perf_counter()
        self.uart.load_dmem_bin(self.dataset_state_words(self.dataset), offset=self.data_base_words)
        self.step_count = 0
        self.previous_kernel_args = None
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return Frame(
            step=0,
            positions=list(zip(self.dataset.pos_x, self.dataset.pos_y, self.dataset.pos_z)),
            source=self.source,
            elapsed_ms=elapsed_ms,
            masses=list(self.dataset.masses),
        )

    def step(self, steps: int) -> Frame:
        start = time.perf_counter()
        self._load_kernel_args(steps=steps)
        self.uart.run()
        try:
            positions = self._read_positions()
        finally:
            self.uart.done()
        self.step_count += steps
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return Frame(
            step=self.step_count,
            positions=positions,
            source=self.source,
            elapsed_ms=elapsed_ms,
            masses=list(self.dataset.masses),
        )


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Interactive FPGA nbody-3d</title>
<style>
  :root { color-scheme: dark; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  body { margin: 0; background: #050816; color: #e5e7eb; display: grid; grid-template-columns: minmax(720px, 1fr) 360px; height: 100vh; overflow: hidden; }
  #view { position: relative; width: 100%; height: 100%; min-width: 0; min-height: 0; overflow: hidden; }
  #view canvas { display: block; width: 100%; height: 100%; }
  #view .overlay { position: absolute; left: 14px; bottom: 14px; right: 14px; padding: 10px 12px; border: 1px solid #334155; border-radius: 8px; background: rgba(15,23,42,.78); color: #cbd5e1; font-size: 13px; pointer-events: none; }
  #view .overlay.error { border-color: #ef4444; color: #fecaca; background: rgba(69,10,10,.86); }
  aside { border-left: 1px solid #273244; padding: 18px; background: linear-gradient(180deg, #0f172a 0%, #0b1020 100%); overflow: auto; box-shadow: -18px 0 42px rgba(0,0,0,.35); }
  button { background: #1f6feb; color: white; border: 0; border-radius: 8px; padding: 10px 12px; margin: 4px; cursor: pointer; font-weight: 700; }
  button.secondary { background: #334155; }
  button.warn { background: #a16207; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .metric { padding: 10px; border: 1px solid #263348; border-radius: 8px; background: #111827; margin: 8px 0; }
  .label { color: #9ca3af; font-size: 12px; }
  .value { color: #f8fafc; font-size: 18px; margin-top: 4px; word-break: break-word; }
  kbd { background:#1f2937; border:1px solid #4b5563; border-bottom-width:2px; padding:2px 6px; border-radius:4px; }
  .hint { color:#9ca3af; font-size: 13px; line-height: 1.45; }
</style>
</head>
<body>
<div id="view"></div>
<aside>
  <h1>nbody-3d FPGA interactive</h1>
  <div class="grid">
    <button id="play">▶ Play/Pause</button>
    <button id="step1" class="secondary">Step 1</button>
    <button id="stepspeed" class="secondary">Step speed</button>
    <button id="reset" class="warn">Reset</button>
    <button id="faster" class="secondary">Speed +</button>
    <button id="slower" class="secondary">Speed -</button>
    <button id="trailfade" class="secondary">Trail fade: On</button>
    <button id="fadefaster" class="secondary">Fade faster</button>
    <button id="fadeslower" class="secondary">Fade slower</button>
    <button id="clear" class="warn">Clear trail</button>
  </div>
  <div class="metric"><div class="label">Status</div><div id="status" class="value">connecting...</div></div>
  <div class="grid">
    <div class="metric"><div class="label">Backend</div><div id="backend" class="value">?</div></div>
    <div class="metric"><div class="label">Step</div><div id="step" class="value">0</div></div>
    <div class="metric"><div class="label">Steps/frame</div><div id="spf" class="value">1</div></div>
    <div class="metric"><div class="label">Target FPS</div><div id="fps" class="value">?</div></div>
    <div class="metric"><div class="label">Last chunk</div><div id="elapsed" class="value">?</div></div>
    <div class="metric"><div class="label">Trail frames</div><div id="frames" class="value">0</div></div>
    <div class="metric"><div class="label">Trail fade window</div><div id="fadesteps" class="value">80 steps</div></div>
  </div>
  <h2>Mouse</h2>
  <p class="hint">Drag to rotate/orbit. Scroll wheel zooms through three.js OrbitControls.</p>
  <h2>Keyboard</h2>
  <p><kbd>Space</kbd>/<kbd>p</kbd> play/pause</p>
  <p><kbd>n</kbd>/<kbd>→</kbd> step by one</p>
  <p><kbd>Enter</kbd> step by current speed</p>
  <p><kbd>r</kbd> reset simulation</p>
  <p><kbd>f</kbd> toggle older-trail fading</p>
  <p><kbd>,</kbd>/<kbd>.</kbd> fade faster/slower</p>
  <p><kbd>+</kbd>/<kbd>-</kbd> change steps per frame</p>
  <p><kbd>[</kbd>/<kbd>]</kbd> change target FPS</p>
</aside>
<script type="importmap">
{
  "imports": {
    "three": "/vendor/three/three.module.js",
    "three/addons/": "/vendor/three/addons/"
  }
}
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const container = document.getElementById('view');
function showOverlay(text, isError=false) {
  let el = document.getElementById('view-overlay');
  if (!el) {
    el = document.createElement('div');
    el.id = 'view-overlay';
    el.className = 'overlay';
    container.appendChild(el);
  }
  el.textContent = text;
  el.className = isError ? 'overlay error' : 'overlay';
}
function hideOverlay() {
  const el = document.getElementById('view-overlay');
  if (el) el.remove();
}
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x050816);

const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 12000);
camera.position.set(440, 360, 680);

let renderer;
try {
  renderer = new THREE.WebGLRenderer({antialias: true, powerPreference: 'high-performance'});
} catch (err) {
  showOverlay(`Could not create WebGL renderer: ${err && err.message ? err.message : err}. Try enabling browser hardware acceleration/WebGL.`, true);
  throw err;
}
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
// Do not leave an inline 1px x 1px CSS size on the canvas.  resize() below
// sets the real display size.  If this first setSize updates style, the later
// resize(..., false) path can leave the canvas visibly stuck at 1x1.
renderer.setSize(1, 1, false);
container.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.enableRotate = true;
controls.enableZoom = true;
controls.zoomSpeed = 0.85;
controls.rotateSpeed = 0.72;
controls.minDistance = 80;
controls.maxDistance = 4200;
controls.target.set(0, 0, 0);

scene.add(new THREE.AmbientLight(0xaec6ff, 0.55));
const keyLight = new THREE.DirectionalLight(0xffffff, 1.8);
keyLight.position.set(260, 360, 480);
scene.add(keyLight);
const rimLight = new THREE.PointLight(0x60a5fa, 500, 2600);
rimLight.position.set(-420, -120, -360);
scene.add(rimLight);

const grid = new THREE.GridHelper(900, 18, 0x334155, 0x1e293b);
grid.material.transparent = true;
grid.material.opacity = 0.45;
scene.add(grid);

const axes = new THREE.AxesHelper(180);
scene.add(axes);

const starGeometry = new THREE.BufferGeometry();
const starPositions = [];
let seed = 0x12345678;
function rand() { seed = (1664525 * seed + 1013904223) >>> 0; return seed / 0x100000000; }
for (let i = 0; i < 900; i++) {
  starPositions.push((rand() - .5) * 5000, (rand() - .5) * 5000, (rand() - .5) * 5000);
}
starGeometry.setAttribute('position', new THREE.Float32BufferAttribute(starPositions, 3));
const stars = new THREE.Points(starGeometry, new THREE.PointsMaterial({color: 0x93c5fd, size: 2.0, transparent: true, opacity: 0.42}));
scene.add(stars);

const colors = [0xffd700,0x38bdf8,0xfb7185,0x4ade80,0xe879f9,0x22d3ee,0xf472b6,0xa3e635];
const bodies = [];
const bodyMeshes = [];
const bodyMasses = Array(32).fill(1);
const trails = [];
const trailPositions = [];
const trailColors = [];
const trailSteps = [];
const trailWriteIndex = [];
const trailBaseOpacity = [];
const TRAIL_POINTS = 220;
const TRAIL_FADE_MIN_ALPHA = 0.03;
const TRAIL_FADE_MIN_POINTS = 5;
let trailFadeEnabled = true;
let trailFadeSteps = 5;
let currentTrailStep = 0;
let state = {};
let latest = null;

function colorComponents(hex) {
  return {
    r: ((hex >> 16) & 0xff) / 255,
    g: ((hex >> 8) & 0xff) / 255,
    b: (hex & 0xff) / 255,
  };
}

function initialPositions() {
  const out = [];
  for (let i = 0; i < 32; i++) out.push([i * 13 - 208, ((i * 29) & 255) - 128, ((i * 47) & 255) - 128]);
  return out;
}

function visualRadiusForMass(mass) {
  // Use cube-root scaling so rendered sphere volume tracks mass instead of
  // making a mass-1000 body 1000x wider.  Clamp keeps malformed values sane.
  const m = Number.isFinite(Number(mass)) && Number(mass) > 0 ? Number(mass) : 1;
  return THREE.MathUtils.clamp(4.5 + Math.cbrt(m) * 3.5, 6.0, 48.0);
}
function applyMassToBody(i, mass) {
  if (!bodies[i]) return;
  const radius = visualRadiusForMass(mass);
  bodies[i].scale.setScalar(radius);
  bodies[i].userData.mass = mass;
  if (bodyMeshes[i]) {
    bodyMeshes[i].material.emissiveIntensity = mass >= 64 ? 0.55 : 0.16 + Math.min(0.24, Math.cbrt(Math.max(1, mass)) * 0.035);
  }
}
function updateBodyMasses(masses) {
  if (!Array.isArray(masses)) return;
  for (let i = 0; i < Math.min(masses.length, bodies.length); i++) {
    bodyMasses[i] = masses[i];
    applyMassToBody(i, masses[i]);
  }
}

for (let i = 0; i < 32; i++) {
  const group = new THREE.Group();
  const geo = new THREE.SphereGeometry(1, 24, 16);
  const mat = new THREE.MeshStandardMaterial({
    color: colors[i % colors.length],
    emissive: colors[i % colors.length],
    emissiveIntensity: 0.18,
    roughness: 0.38,
    metalness: 0.1,
  });
  const mesh = new THREE.Mesh(geo, mat);
  group.add(mesh);
  scene.add(group);
  bodies.push(group);
  bodyMeshes.push(mesh);
  applyMassToBody(i, bodyMasses[i]);

  const lineArray = new Float32Array(TRAIL_POINTS * 3);
  const colorArray = new Float32Array(TRAIL_POINTS * 4);
  const stepArray = new Float32Array(TRAIL_POINTS);
  const trailGeo = new THREE.BufferGeometry();
  trailGeo.setAttribute('position', new THREE.BufferAttribute(lineArray, 3));
  trailGeo.setAttribute('color', new THREE.BufferAttribute(colorArray, 4));
  trailGeo.setDrawRange(0, 0);
  const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({vertexColors: true, transparent: true, opacity: 1.0, depthWrite: false}));
  scene.add(trail);
  trails.push(trail);
  trailPositions.push(lineArray);
  trailColors.push(colorArray);
  trailSteps.push(stepArray);
  trailWriteIndex.push(0);
  trailBaseOpacity.push(i === 0 ? 0.72 : 0.42);
}

function scaled(p) {
  // C uses x,y,z.  three.js uses x,y,z too; invert no axes so reset/debug values stay intuitive.
  return new THREE.Vector3(p[0], p[1], p[2] || 0);
}
function rebuildTrailFromScratch() {
  for (let b = 0; b < trails.length; b++) {
    trailPositions[b].fill(0);
    trailColors[b].fill(0);
    trailSteps[b].fill(0);
    trailWriteIndex[b] = 0;
    trails[b].geometry.setDrawRange(0, 0);
    trails[b].geometry.attributes.position.needsUpdate = true;
    trails[b].geometry.attributes.color.needsUpdate = true;
  }
  updatePanel();
}
function refreshTrailFadeButton() {
  document.getElementById('trailfade').textContent = `Trail fade: ${trailFadeEnabled ? 'On' : 'Off'}`;
}
function updateTrailFadeWindow(delta) {
  if (delta < 0) {
    trailFadeSteps = Math.max(TRAIL_FADE_MIN_POINTS, Math.floor(trailFadeSteps / 2));
  } else {
    trailFadeSteps = Math.min(1000000, Math.max(trailFadeSteps + 1, Math.ceil(trailFadeSteps * 2)));
  }
  refreshAllTrailColors();
  updatePanel();
}
function updateTrailColors(bodyIndex, count) {
  const color = colorComponents(colors[bodyIndex % colors.length]);
  const arr = trailColors[bodyIndex];
  const base = trailBaseOpacity[bodyIndex];
  for (let i = 0; i < TRAIL_POINTS; i++) {
    const k = i * 4;
    arr[k+0] = color.r;
    arr[k+1] = color.g;
    arr[k+2] = color.b;
    if (i >= count) {
      arr[k+3] = 0;
      continue;
    }
    const stepsBehindNewest = currentTrailStep - trailSteps[bodyIndex][i];
    if (trailFadeEnabled && stepsBehindNewest > trailFadeSteps) {
      arr[k+3] = 0;
      continue;
    }
    const age = trailFadeEnabled ? 1 - (stepsBehindNewest / Math.max(1, trailFadeSteps)) : 1; // 0=oldest visible, 1=newest
    const fade = trailFadeEnabled ? (TRAIL_FADE_MIN_ALPHA + Math.pow(Math.max(0, age), 1.35) * (1 - TRAIL_FADE_MIN_ALPHA)) : 1;
    arr[k+3] = base * fade;
  }
  trails[bodyIndex].geometry.attributes.color.needsUpdate = true;
}
function refreshAllTrailColors() {
  for (let b = 0; b < trails.length; b++) {
    updateTrailColors(b, Math.min(trailWriteIndex[b], TRAIL_POINTS));
  }
}
function toggleTrailFade() {
  trailFadeEnabled = !trailFadeEnabled;
  refreshTrailFadeButton();
  refreshAllTrailColors();
  updatePanel();
}
function appendTrail(bodyIndex, v) {
  const arr = trailPositions[bodyIndex];
  const steps = trailSteps[bodyIndex];
  const idx = trailWriteIndex[bodyIndex] % TRAIL_POINTS;
  arr[idx*3+0] = v.x;
  arr[idx*3+1] = v.y;
  arr[idx*3+2] = v.z;
  steps[idx] = currentTrailStep;
  trailWriteIndex[bodyIndex] += 1;
  // Keep the line simple and ordered.  Once full, rewrite a rotated copy.
  const count = Math.min(trailWriteIndex[bodyIndex], TRAIL_POINTS);
  if (trailWriteIndex[bodyIndex] > TRAIL_POINTS) {
    const copy = new Float32Array(TRAIL_POINTS * 3);
    const stepCopy = new Float32Array(TRAIL_POINTS);
    for (let i = 0; i < TRAIL_POINTS; i++) {
      const srcIndex = (trailWriteIndex[bodyIndex] + i) % TRAIL_POINTS;
      const src = srcIndex * 3;
      copy[i*3+0] = arr[src+0]; copy[i*3+1] = arr[src+1]; copy[i*3+2] = arr[src+2];
      stepCopy[i] = steps[srcIndex];
    }
    arr.set(copy);
    steps.set(stepCopy);
    trailWriteIndex[bodyIndex] = TRAIL_POINTS;
  }
  trails[bodyIndex].geometry.setDrawRange(0, count);
  trails[bodyIndex].geometry.attributes.position.needsUpdate = true;
  updateTrailColors(bodyIndex, count);
}
function applyFrame(frame, {resetTrail=false}={}) {
  latest = frame;
  if (frame.masses) updateBodyMasses(frame.masses);
  currentTrailStep = frame.step ?? currentTrailStep;
  if (resetTrail) rebuildTrailFromScratch();
  const center = new THREE.Vector3();
  frame.positions.forEach((p, i) => {
    if (!bodies[i]) return;
    const v = scaled(p);
    bodies[i].position.copy(v);
    center.add(v);
    appendTrail(i, v);
  });
  center.multiplyScalar(1 / Math.max(1, frame.positions.length));
  controls.target.lerp(center, resetTrail ? 1.0 : 0.08);
  hideOverlay();
  updatePanel();
}
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
  setText('frames', trailWriteIndex[0] || 0);
  setText('fadesteps', trailFadeEnabled ? `${trailFadeSteps} steps` : 'off');
  if (latest) setText('elapsed', `${latest.elapsed_ms} ms`);
}
function resize() {
  const rect = container.getBoundingClientRect();
  const w = Math.max(1, Math.floor(rect.width));
  const h = Math.max(1, Math.floor(rect.height));
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  // Update both drawing-buffer size and CSS display size.  The third argument
  // must remain true here; otherwise three.js may keep an old inline CSS size
  // and render a correctly-sized buffer into an invisible 1px canvas.
  renderer.setSize(w, h, true);
}
window.addEventListener('resize', resize);
resize();

showOverlay('Loading initial nbody-3d frame...');
applyFrame({step: 0, positions: initialPositions(), source: 'local-placeholder', elapsed_ms: 0}, {resetTrail: true});
const events = new EventSource('/events');
events.onmessage = ev => {
  const msg = JSON.parse(ev.data);
  if (msg.type === 'frame') applyFrame(msg);
  if (msg.type === 'reset') applyFrame(msg.frame, {resetTrail: true});
  if (msg.type === 'state') { state = msg; if (msg.latest && (!latest || latest.source === 'local-placeholder')) applyFrame(msg.latest, {resetTrail: true}); updatePanel(); }
  if (msg.type === 'error') { state.status = msg.message; showOverlay(msg.message, true); updatePanel(); }
};
events.onerror = () => showOverlay('Lost /events stream; controls may still work, trying /state fallback...', true);
fetch('/state')
  .then(r => r.json())
  .then(s => { state=s; if (s.latest) applyFrame(s.latest, {resetTrail: true}); updatePanel(); })
  .catch(err => showOverlay(`Could not fetch /state: ${err && err.message ? err.message : err}`, true));

document.getElementById('play').onclick = () => post('toggle_play');
document.getElementById('step1').onclick = () => post('step_one');
document.getElementById('stepspeed').onclick = () => post('step_speed');
document.getElementById('reset').onclick = () => post('reset_simulation');
document.getElementById('faster').onclick = () => post('speed_up');
document.getElementById('slower').onclick = () => post('speed_down');
document.getElementById('trailfade').onclick = () => toggleTrailFade();
document.getElementById('fadefaster').onclick = () => updateTrailFadeWindow(-1);
document.getElementById('fadeslower').onclick = () => updateTrailFadeWindow(1);
document.getElementById('clear').onclick = () => rebuildTrailFromScratch();
refreshTrailFadeButton();
document.addEventListener('keydown', ev => {
  if (ev.target && ['INPUT','TEXTAREA'].includes(ev.target.tagName)) return;
  if (ev.key === ' ' || ev.key === 'p') { ev.preventDefault(); post('toggle_play'); }
  else if (ev.key === 'n' || ev.key === 'ArrowRight') { ev.preventDefault(); post('step_one'); }
  else if (ev.key === 'Enter') { ev.preventDefault(); post('step_speed'); }
  else if (ev.key === 'r' || ev.key === 'R') { ev.preventDefault(); post('reset_simulation'); }
  else if (ev.key === 'f' || ev.key === 'F') { ev.preventDefault(); toggleTrailFade(); }
  else if (ev.key === ',') { ev.preventDefault(); updateTrailFadeWindow(-1); }
  else if (ev.key === '.') { ev.preventDefault(); updateTrailFadeWindow(1); }
  else if (ev.key === '+' || ev.key === '=') { ev.preventDefault(); post('speed_up'); }
  else if (ev.key === '-' || ev.key === '_') { ev.preventDefault(); post('speed_down'); }
  else if (ev.key === '[') { ev.preventDefault(); post('fps_down'); }
  else if (ev.key === ']') { ev.preventDefault(); post('fps_up'); }
});
function animate() {
  requestAnimationFrame(animate);
  controls.update();
  stars.rotation.y += 0.00008;
  bodies.forEach((body, i) => { body.rotation.y += 0.006 + i * 0.0002; });
  renderer.render(scene, camera);
}
animate();
</script>
</body>
</html>
"""


class ControlServer(ThreadingHTTPServer):
    def __init__(self, addr, handler, *, state: SharedState, commands: "queue.Queue[tuple[str, Any]]"):
        super().__init__(addr, handler)
        self.state = state
        self.commands = commands
        self.quiet = False


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
        elif parsed.path.startswith("/vendor/"):
            try:
                asset = (DEMO_DIR / parsed.path.lstrip("/")).resolve()
                asset.relative_to(VENDOR_DIR.resolve())
            except ValueError:
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                return
            if not asset.is_file():
                self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
                return
            content_type = "text/javascript; charset=utf-8" if asset.suffix == ".js" else "application/octet-stream"
            self._send(HTTPStatus.OK, asset.read_bytes(), content_type)
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


def apply_control(state: SharedState, commands: "queue.Queue[tuple[str, Any]]") -> tuple[int | None, bool]:
    """Apply pending UI commands. Return (manual step count, reset requested)."""
    manual_step: int | None = None
    reset_requested = False
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
            elif action == "reset_simulation":
                state.playing = False
                reset_requested = True
            elif action == "speed_up":
                state.steps_per_frame = clamp(state.steps_per_frame * 2, 1, 10240)
            elif action == "speed_down":
                state.steps_per_frame = clamp(max(1, state.steps_per_frame // 2), 1, 10240)
            elif action == "fps_up":
                state.target_fps = min(60.0, state.target_fps + 1.0)
            elif action == "fps_down":
                state.target_fps = max(1.0, state.target_fps - 1.0)
            elif action == "set_speed":
                state.steps_per_frame = clamp(int(data.get("steps_per_frame", state.steps_per_frame)), 1, 10240)
            elif action == "set_fps":
                state.target_fps = float(max(1.0, min(60.0, float(data.get("target_fps", state.target_fps)))))
            else:
                state.status = f"ignored unknown action: {action}"
        state.publish(state.snapshot())
    return manual_step, reset_requested


def worker_loop(state: SharedState, commands: "queue.Queue[tuple[str, Any]]", backend: Backend) -> None:
    state.replace_with_frame(backend.reset())
    state.set_status("ready")
    try:
        while not state.stop_event.is_set():
            manual_step, reset_requested = apply_control(state, commands)
            if reset_requested:
                with state.lock:
                    state.busy = True
                    state.status = "resetting"
                state.publish(state.snapshot())
                frame = backend.reset()
                state.replace_with_frame(frame)
                with state.lock:
                    state.busy = False
                    state.status = "ready"
                state.publish(state.snapshot())
                continue
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
    except Exception as exc:
        with state.lock:
            state.busy = False
            state.playing = False
            state.status = f"ERROR: {exc}"
        state.publish({"type": "error", "message": str(exc)})
        state.publish(state.snapshot())
    finally:
        backend.close()


def default_imem() -> Path:
    return PROGRAM_DIR / "nbody-3d_instructions.mem"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Interactive three.js browser UI for the nbody-3d demo")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fake", action="store_true", help="Use the local software backend")
    mode.add_argument("--port", help="FPGA UART serial port, e.g. /dev/ttyUSB1")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--imem", type=Path, default=default_imem())
    parser.add_argument("--skip-load-imem", action="store_true")
    parser.add_argument("--data-base", type=parse_int_auto, default=DEFAULT_DATA_BASE_BYTES, help="DMEM byte address passed as GPGPU_ARGS[0]")
    parser.add_argument("--data-limit", type=parse_int_auto, default=DEFAULT_DATA_LIMIT_BYTES, help="End byte address of usable nbody-3d DMEM data region")
    parser.add_argument("--steps-per-frame", type=int, default=1)
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS)
    parser.add_argument(
        "--dataset",
        default="default",
        help="Fake-backend initial condition dataset name/path (default: default). Names are read from programs/nbody-3d/datasets/.",
    )
    parser.add_argument("--http-host", default=DEFAULT_HTTP_HOST)
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.fake and not args.port:
        raise SystemExit("Choose --fake or pass --port for the FPGA UART backend")
    dataset = load_dataset(args.dataset)
    backend_label = f"fake:{dataset.name}" if args.fake else f"fpga-uart:{dataset.name}"
    state = SharedState(
        steps_per_frame=clamp(args.steps_per_frame, 1, 10240),
        target_fps=max(1.0, min(60.0, args.fps)),
        backend=backend_label,
    )
    commands: queue.Queue[tuple[str, Any]] = queue.Queue()
    if args.fake:
        backend: Backend = FakeNbody3DBackend(dataset)
    else:
        backend = FpgaNbody3DBackend(
            port=args.port,
            baud=args.baud,
            imem=args.imem,
            dataset=dataset,
            data_base_bytes=args.data_base,
            data_limit_bytes=args.data_limit,
            skip_load_imem=args.skip_load_imem,
            verbose=args.verbose,
        )
    worker = threading.Thread(target=worker_loop, args=(state, commands, backend), daemon=True)
    worker.start()
    server = ControlServer((args.http_host, args.http_port), Handler, state=state, commands=commands)
    url = f"http://{args.http_host}:{args.http_port}/"
    print(f"[INFO] Interactive nbody-3d three.js UI: {url}", flush=True)
    print(f"[INFO] Dataset: {dataset.name}", flush=True)
    print("[INFO] Mouse: drag to rotate/orbit, scroll to zoom", flush=True)
    print("[INFO] Browser keys: Space play/pause, n step one, r reset, Enter step by speed, +/- speed", flush=True)
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