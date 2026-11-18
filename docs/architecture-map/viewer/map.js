// The GPGPU architecture map: every block that has children is laid out on its
// own by ELK and drawn, scaled down, inside its box. Zooming into a box fades
// its face out and its interior in, so depth is revealed by zoom alone.
"use strict";

const REPO = "https://github.com/PANAGIVTHS/ECE338-Parallel-Computer-Architecture/blob/main/";
const KINDS = {
  lane:     { c: "#6b7586", name: "Lane" },
  ip:       { c: "#8b7cf0", name: "IP block" },
  module:   { c: "#5b8def", name: "RTL module" },
  memory:   { c: "#2fb3c4", name: "Memory" },
  regs:     { c: "#e0a04a", name: "Registers" },
  bus:      { c: "#c07ae8", name: "Interconnect" },
  process:  { c: "#4fb879", name: "Software" },
  command:  { c: "#8bd3a3", name: "Command" },
  artifact: { c: "#b8ab92", name: "File" },
  tool:     { c: "#93a0b4", name: "Tool" },
  external: { c: "#c3cad4", name: "Off chip" },
};
const STATUS = { experimental: "not built", deprecated: "deprecated" };
const WIRES = {
  data:     { c: "#8a94a6", w: 1.4, name: "Data" },
  control:  { c: "#e3a54a", w: 1.4, name: "Control" },
  axi:      { c: "#a993ff", w: 2.6, name: "AXI4" },
  axilite:  { c: "#a993ff", w: 1.6, name: "AXI4-Lite" },
  stream:   { c: "#a993ff", w: 1.8, dash: "7 4", name: "AXI4-Stream" },
  uart:     { c: "#5fc48a", w: 1.6, dash: "6 4", name: "UART" },
  irq:      { c: "#ef6f6c", w: 1.5, name: "Interrupt" },
  clock:    { c: "#8a94a6", w: 1.2, dash: "2 4", name: "Clock" },
  produces: { c: "#b8ab92", w: 1.3, dash: "6 4", name: "Produces" },
  perf:     { c: "#8a94a6", w: 1.1, dash: "1 4", name: "Perf events" },
};

// Geometry, in the units of the level a box is drawn in.
// A block starts to open when it covers OPEN[0] of the screen and is fully open at OPEN[1].
const PAD = 22, HEAD = 46, LEAF_W = [176, 280], OPEN = [0.42, 0.56];
const FONT = { label: 15, tech: 11, sum: 11.5, edge: 10.5, pin: 10.5 };

const $ = (s) => document.querySelector(s);
const svg = d3.select("#map");
// ELK on the main thread: a pool of workers was tried and was slower, each worker
// paying ELK's start-up cost. The count of layout calls is what matters.
const elkEngine = new ELK();
const elkStats = { calls: 0 };
const elk = { layout: (graph) => { elkStats.calls++; return elkEngine.layout(graph); } };

// Finished layouts are kept in the browser, keyed by the model and this file's
// layout rules, so a reload skips ELK. Bump LAYOUT_VERSION when the rules change.
const LAYOUT_VERSION = 5;
let layoutCache = {}, cacheKey = null, laidOut = 0, toLayOut = 0;
const hash = (text) => { let h = 2166136261; for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619); return (h >>> 0).toString(36); };
function loadCache(text) {
  cacheKey = `gpgpu-map-layout:${LAYOUT_VERSION}:${hash(text)}:${innerWidth > 720 ? "wide" : "narrow"}`;
  try { layoutCache = JSON.parse(localStorage.getItem(cacheKey) || "{}"); } catch { layoutCache = {}; }
}
function saveCache() {
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i);
      if (key && key.startsWith("gpgpu-map-layout:") && key !== cacheKey) localStorage.removeItem(key);
    }
    localStorage.setItem(cacheKey, JSON.stringify(layoutCache));
  } catch { /* storage full or blocked: the next load lays out again */ }
}
const keep = (r) => ({ dir: r.dir, width: r.width, height: r.height, children: r.children.map((c) => ({ id: c.id, x: c.x, y: c.y })),
  edges: r.edges.map((e) => ({ sections: e.sections ? e.sections.map((q) => ({ startPoint: q.startPoint, endPoint: q.endPoint, bendPoints: q.bendPoints })) : null })) });
const canvas = document.createElement("canvas").getContext("2d");
const byPath = new Map();
const containers = [];
const portsOf = new Map();                 // nested block -> its ports at its parent's level
let root, wires = [], view = d3.zoomIdentity, selected = null, focus = null, zoom;

// ------------------------------------------------------------------ model
function textW(text, size, weight = 400, family = "IBM Plex Sans") {
  canvas.font = `${weight} ${size}px "${family}"`;
  return canvas.measureText(text || "").width;
}
function wrap(text, width, size, max = 3) {
  const words = (text || "").split(/\s+/).filter(Boolean), lines = [];
  let line = "";
  for (const w of words) {
    const next = line ? line + " " + w : w;
    if (textW(next, size) > width && line) { lines.push(line); line = w; } else line = next;
  }
  if (line) lines.push(line);
  if (lines.length > max) { lines.length = max; lines[max - 1] = lines[max - 1].replace(/\s*\S*$/, "") + " …"; }
  return lines;
}

function build(data, parent) {
  const n = { data, id: data.id, parent, depth: parent ? parent.depth + 1 : 0, kind: data.kind || "module", children: [] };
  n.path = parent && parent.parent ? `${parent.path}.${data.id}` : parent ? data.id : "";
  n.label = data.label || data.id;
  if (byPath.has(n.path)) throw new Error(`Duplicate block ${n.path}`);
  byPath.set(n.path, n);
  for (const c of data.children || []) n.children.push(build(c, n));
  return n;
}
function resolve(scope, rel) {
  const path = scope.path ? `${scope.path}.${rel}` : rel;
  const n = byPath.get(path);
  if (!n) throw new Error(`Wire in ${scope.path || "the root"}: no block ${path}`);
  return n;
}
function collectWires(n) {
  for (const spec of n.data.wires || []) {
    const [ends, kind = "data", label = ""] = String(spec).split("|").map((s) => s.trim());
    const m = ends.match(/^(\S+)\s*->\s*(\S+)$/);
    if (!m) throw new Error(`Bad wire "${spec}" in ${n.path || "the root"}`);
    if (!WIRES[kind]) throw new Error(`Unknown wire kind "${kind}" in "${spec}"`);
    wires.push({ from: resolve(n, m[1]), to: resolve(n, m[2]), kind, label, scope: n });
  }
  n.children.forEach(collectWires);
}
const KIND_ORDER = ["axi", "axilite", "stream", "irq", "uart", "clock", "control", "data", "produces", "perf"];
const strongest = (list) => list.map((w) => w.kind).sort((p, q) => KIND_ORDER.indexOf(p) - KIND_ORDER.indexOf(q))[0];
const commonAncestor = (a, b) => { const up = ancestors(a); let c = null; for (const x of ancestors(b)) if (up.includes(x)) c = x; return c; };
const isIn = (n, a) => { for (let x = n; x; x = x.parent) if (x === a) return true; return false; };
const childOf = (scope, n) => { for (let x = n; x && x.parent; x = x.parent) if (x.parent === scope) return x; return null; };
const ancestors = (n) => { const r = []; for (let x = n; x; x = x.parent) r.unshift(x); return r; };

// ------------------------------------------------------------------ layout
function leafSize(n) {
  const d = n.data;
  const w = Math.min(LEAF_W[1], Math.max(LEAF_W[0],
    textW(n.label, FONT.label, 600) + 34, textW(d.tech, FONT.tech, 400, "IBM Plex Mono") + 34));
  n.sumLines = wrap(d.summary, w - 28, FONT.sum, 3);
  n.w = w;
  n.h = 16 + 19 + (d.tech ? 16 : 0) + n.sumLines.length * 15 + 14;
}

function containerSize(n) {
  // A block's box keeps the shape of its contents but a bounded area, so at any
  // level its face reads next to its sibling leaves, and zooming in opens it.
  const lane = n.kind === "lane";
  const area = lane ? 640 * 420 : 520 * 330;
  const aspect = Math.min(4.5, Math.max(0.7, n.inner.w / n.inner.h));
  const bodyW = Math.sqrt(area * aspect), bodyH = bodyW / aspect;
  const s = Math.min(0.9, bodyW / n.inner.w, bodyH / n.inner.h);
  n.s = s;
  n.w = bodyW + 2 * PAD;
  n.h = HEAD + bodyH + PAD;
  n.ox = (n.w - n.inner.w * s) / 2;
  n.oy = HEAD + (bodyH - n.inner.h * s) / 2;
  // the closed face: label, tech, summary and the blocks inside
  n.base = Math.min(n.w, n.h * 2.2);
  n.faceSize = n.base / 13;
  n.faceSum = wrap(n.data.summary, (n.w - 2 * PAD) * 30 / n.base, 1, 3);
}

async function layout(n) {
  await Promise.all(n.children.filter((c) => c.children.length).map(layout));
  n.children.forEach((c) => (c.children.length ? containerSize(c) : leafSize(c)));

  // Wires seen at this level. Between two children, every wire one way is one
  // line. A wire leaving the block ends at a pin named after the block it goes
  // to at the level where it really runs: the child of the two ends' common
  // ancestor. So each level shows its neighbours, and zooming in shows the rest.
  const edges = new Map(), pins = new Map();
  const edgeFor = (key, src, dst) => edges.get(key) || edges.set(key, { src, dst, wires: [] }).get(key);
  for (const w of wires) {
    const a = childOf(n, w.from), b = childOf(n, w.to);
    if (a && b && a !== b) edgeFor(`${a.id}|${b.id}`, a, b).wires.push(w);
    else if (n.parent && !(a && b) && (a ? w.to !== n : b && w.from !== n)) {
      const out = !!a, inner = a || b;
      const peer = childOf(commonAncestor(w.from, w.to), out ? w.to : w.from);
      const pid = `${out ? "out" : "in"}:${peer.path}`;
      if (!pins.has(pid)) pins.set(pid, { id: pid, out, peer, wires: [] });
      const pin = pins.get(pid);
      pin.wires.push(w);
      (out ? edgeFor(`${inner.id}|${pid}`, inner, pin) : edgeFor(`${pid}|${inner.id}`, pin, inner)).wires.push(w);
    }
  }
  for (const e of edges.values()) e.kind = strongest(e.wires);
  for (const p of pins.values()) {
    p.text = `${p.out ? "" : "◂ "}${p.peer.label}${p.out ? " ▸" : ""}`;
    p.w = textW(p.text, FONT.pin, 500, "IBM Plex Mono") + 22; p.h = 24;
  }
  for (const e of edges.values()) {
    const labels = [...new Set(e.wires.map((w) => w.label).filter(Boolean))];
    let t = labels.join(", ");
    if (t.length > 26) t = t.slice(0, 25) + "…";
    e.text = t;
  }
  // A wire into a nested block meets its box where the matching pin sits inside,
  // so the wire visibly continues into the block when it opens.
  const ports = new Map();                  // child id -> [{id, x, y, side, pin}]
  const portFor = (c, e, out) => {
    if (!c.children || !c.children.length) return null;
    const list = ports.get(c.id) || ports.set(c.id, []).get(c.id);
    const right = c.w + (c.data.count ? 8 : 0), bottom = c.h + (c.data.count ? 8 : 0);
    const pin = c.pins.find((p) => p.out === out && p.wires.some((w) => e.wires.includes(w)));
    if (!pin) {
      // a wire to the block as a whole meets it beside its title
      const side = out ? "EAST" : "WEST";
      const i = list.filter((q) => !q.pin && q.side === side).length;
      const id = `${c.id}~whole:${out ? "out" : "in"}:${i}`;
      list.push({ id, side, x: out ? right : 0, y: HEAD / 2 + i * 12 });
      return id;
    }
    const id = `${c.id}~${pin.id}`;
    if (!list.some((q) => q.id === id)) {
      const side = pin.side;
      const along = side === "WEST" || side === "EAST";
      let at = along ? c.oy + (pin.y + pin.h / 2) * c.s : c.ox + (pin.x + pin.w / 2) * c.s;
      while (list.some((q) => q.side === side && Math.abs((along ? q.y : q.x) - at) < 10)) at += 12;
      list.push({ id, side, pin,
        x: side === "WEST" ? 0 : side === "EAST" ? right : at,
        y: side === "NORTH" ? 0 : side === "SOUTH" ? bottom : at });
    }
    return id;
  };
  const edgeList = [...edges.values()];
  for (const e of edgeList) { e.sp = portFor(e.src, e, true); e.tp = portFor(e.dst, e, false); }
  const dense = edgeList.length > 10;
  const graph = {
    id: "g",
    layoutOptions: {
      "elk.algorithm": "layered", "elk.direction": "RIGHT", "elk.edgeRouting": "ORTHOGONAL",
      "elk.spacing.nodeNode": "26", "elk.layered.spacing.nodeNodeBetweenLayers": "46",
      "elk.spacing.edgeNode": dense ? "24" : "18", "elk.spacing.edgeEdge": dense ? "15" : "12",
      "elk.layered.spacing.edgeNodeBetweenLayers": "22",
      "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
      "elk.padding": "[top=10,left=10,bottom=10,right=10]",
    },
    children: [
      ...n.children.map((c) => ({ id: c.id, width: c.w + (c.data.count ? 8 : 0), height: c.h + (c.data.count ? 8 : 0),
        ...(ports.has(c.id) ? {
          layoutOptions: { "elk.portConstraints": "FIXED_POS" },
          ports: ports.get(c.id).map((q) => ({ id: q.id, x: q.x, y: q.y, width: 0, height: 0, layoutOptions: { "elk.port.side": q.side } })),
        } : {}) })),
      ...[...pins.values()].map((p) => ({ id: p.id, width: p.w, height: p.h,
        layoutOptions: { "elk.layered.layering.layerConstraint": p.out ? "LAST" : "FIRST" } })),
    ],
    edges: edgeList.map((e, i) => ({ id: `e${i}`, sources: [e.sp || e.src.id], targets: [e.tp || e.dst.id] })),
  };
  // Try both directions and keep the shape closest to a screen. (ELK's wrapping of
  // wide levels was tried: it loops wires around the whole level, so it is not used.)
  const fit = (r) => Math.abs(Math.log((r.width / r.height) / 1.7));
  const attempt = async (options) => {
    const g = structuredClone(graph);
    Object.assign(g.layoutOptions, options);
    const r = await elk.layout(g);
    r.dir = options["elk.direction"];
    return r;
  };
  const choose = async (gap) => {
    const extra = { "elk.layered.spacing.nodeNodeBetweenLayers": String(gap), "elk.spacing.nodeNode": String(26 + (gap - 46) / 2) };
    // the other direction only when the first is far from the shape of a screen
    const right = await attempt({ ...extra, "elk.direction": "RIGHT" });
    const aspect = right.width / right.height;
    if (n.children.length <= 3 || (aspect > 0.9 && aspect < 2.6)) return right;
    const down = await attempt({ ...extra, "elk.direction": "DOWN" });
    return fit(down) < fit(right) ? down : right;
  };
  const apply = (res) => {
    const pos = new Map(res.children.map((c) => [c.id, c]));
    n.dir = res.dir;
    n.children.forEach((c) => { c.x = pos.get(c.id).x; c.y = pos.get(c.id).y; });
    n.pins = [...pins.values()].map((p) => {
      const x = pos.get(p.id).x, y = pos.get(p.id).y;
      // the side of the level the pin is nearest to, preferring the one its direction faces
      const gap = { WEST: x, EAST: res.width - x - p.w, NORTH: y, SOUTH: res.height - y - p.h };
      const prefer = res.dir === "DOWN" ? (p.out ? "SOUTH" : "NORTH") : (p.out ? "EAST" : "WEST");
      const side = Object.keys(gap).reduce((a, b) => (gap[b] < gap[a] - 1 ? b : a), prefer);
      return Object.assign(p, { x, y, side });
    });
    n.edges = edgeList.map((e, i) => {
      const sec = res.edges[i].sections && res.edges[i].sections[0];
      return Object.assign(e, { route: res.edges[i], pts: sec ? [sec.startPoint, ...(sec.bendPoints || []), sec.endPoint] : null });
    });
    return placeLabels(n);
  };
  // Where a label finds no free spot, give the level more room and lay it out again.
  let best = layoutCache[n.path || "root"] || null;
  if (best) apply(best);
  else {
    let hidden = Infinity, last = null;
    for (const gap of [46, 76, 106]) {
      last = await choose(gap);
      const h = apply(last);
      if (h < hidden) { hidden = h; best = last; }
      if (!h) break;
    }
    if (best !== last) apply(best);
    layoutCache[n.path || "root"] = keep(best);
  }
  const res = best;
  laidOut++;
  const status = document.getElementById("status");
  if (status) status.textContent = `Laying out the model… ${laidOut} of ${toLayOut} levels`;
  for (const c of n.children) if (ports.has(c.id)) portsOf.set(c, ports.get(c.id));
  n.inner = { w: res.width, h: res.height };
  containers.push(n);
}

function place(n, ax, ay, as) {           // world position of n's interior origin and its scale
  n.ax = ax; n.ay = ay; n.as = as;
  for (const c of n.children) {
    c.bx = ax + c.x * as; c.by = ay + c.y * as; c.bw = c.w * as; c.bh = c.h * as;   // the box, in world units
    if (c.children.length) place(c, c.bx + c.ox * as, c.by + c.oy * as, as * c.s);
  }
}

// ------------------------------------------------------------------ drawing
const tint = (hex, a) => { const c = d3.color(hex); const b = d3.color("#0d1015"); return d3.rgb(b.r + (c.r - b.r) * a, b.g + (c.g - b.g) * a, b.b + (c.b - b.b) * a); };

function roundedPath(pts, r = 7) {
  let d = `M${pts[0].x},${pts[0].y}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const p0 = pts[i - 1], p1 = pts[i], p2 = pts[i + 1];
    const l1 = Math.hypot(p1.x - p0.x, p1.y - p0.y), l2 = Math.hypot(p2.x - p1.x, p2.y - p1.y);
    const k = Math.min(r, l1 / 2, l2 / 2);
    const a = { x: p1.x - (p1.x - p0.x) / l1 * k, y: p1.y - (p1.y - p0.y) / l1 * k };
    const b = { x: p1.x + (p2.x - p1.x) / l2 * k, y: p1.y + (p2.y - p1.y) / l2 * k };
    d += `L${a.x},${a.y}Q${p1.x},${p1.y} ${b.x},${b.y}`;
  }
  const z = pts[pts.length - 1];
  return d + `L${z.x},${z.y}`;
}

function defs() {
  const d = svg.append("defs");
  for (const [k, v] of Object.entries(WIRES)) {
    d.append("marker").attr("id", `arrow-${k}`).attr("viewBox", "0 0 10 10").attr("refX", 9).attr("refY", 5)
      .attr("markerWidth", 7).attr("markerHeight", 7).attr("markerUnits", "userSpaceOnUse").attr("orient", "auto-start-reverse")
      .append("path").attr("d", "M0,1 L10,5 L0,9 z").attr("fill", v.c);
  }
}

function drawEdges(g, n) {
  for (const e of n.edges) {
    if (!e.pts) continue;
    const st = WIRES[e.kind], pts = e.pts;
    const eg = g.append("g").attr("class", "edge").attr("data-src", e.src.id).attr("data-dst", e.dst.id);
    eg.append("path").attr("class", "line").attr("d", roundedPath(pts)).attr("stroke", st.c)
      .attr("stroke-width", st.w).attr("stroke-dasharray", st.dash || null).attr("marker-end", `url(#arrow-${e.kind})`);
    eg.append("title").text(e.wires.map((w) => `${w.from.label} → ${w.to.label}${w.label ? ": " + w.label : ""} (${WIRES[w.kind].name})`).join("\n"));
    if (e.label) {
      eg.append("rect").attr("x", e.label.x).attr("y", e.label.y).attr("width", e.label.w).attr("height", e.label.h).attr("rx", 3);
      eg.append("text").attr("x", e.labelAt.x).attr("y", e.labelAt.y + 3.5).attr("text-anchor", "middle").attr("font-size", FONT.edge).text(e.text);
    }
  }
}

// Labels go where they touch no block, pin or other label, preferring spots that
// cross no other wire. A label with no free spot stays in the tooltip and panel.
function placeLabels(n) {
  const boxes = [...n.children.map((c) => ({ x: c.x, y: c.y, w: c.w + (c.data.count ? 8 : 0), h: c.h + (c.data.count ? 8 : 0) })),
    ...n.pins.map((p) => ({ x: p.x, y: p.y, w: p.w, h: p.h }))];
  const segs = n.edges.filter((e) => e.pts).flatMap((e) => e.pts.slice(1).map((b, i) => ({ e, a: e.pts[i], b })));
  const placed = [];
  const hit = (r, q, m = 3) => r.x < q.x + q.w + m && r.x + r.w + m > q.x && r.y < q.y + q.h + m && r.y + r.h + m > q.y;
  const crosses = (r, sg) => {
    const x0 = Math.min(sg.a.x, sg.b.x), x1 = Math.max(sg.a.x, sg.b.x), y0 = Math.min(sg.a.y, sg.b.y), y1 = Math.max(sg.a.y, sg.b.y);
    return x0 <= r.x + r.w && x1 >= r.x && y0 <= r.y + r.h && y1 >= r.y;
  };
  let hidden = 0;
  for (const e of n.edges) e.label = null;
  const order = [...n.edges].filter((e) => e.text && e.pts).sort((p, q) => p.text.length - q.text.length);
  for (const e of order) {
    const w = textW(e.text, FONT.edge, 400, "IBM Plex Mono") + 8, h = 15;
    let best = null;
    for (let i = 1; i < e.pts.length; i++) {
      const a = e.pts[i - 1], b = e.pts[i], len = Math.hypot(b.x - a.x, b.y - a.y);
      const horizontal = Math.abs(a.y - b.y) < 0.5;
      // on the line where the segment is long enough, otherwise beside it
      const spots = [];
      for (const t of [0.5, 0.35, 0.65, 0.2, 0.8]) {
        if (horizontal ? len >= w + 12 : len >= h + 12) spots.push([t, 0, 0, 0]);
        if (horizontal && len >= w * 0.7) spots.push([t, 0, -(h / 2 + 2), 0.3], [t, 0, h / 2 + 2, 0.35]);
        if (!horizontal && len >= h + 6) spots.push([t, w / 2 + 3, 0, 0.3], [t, -(w / 2 + 3), 0, 0.35]);
      }
      for (const [t, dx, dy, extra] of spots) {
        const cx = a.x + (b.x - a.x) * t + dx, cy = a.y + (b.y - a.y) * t + dy;
        const r = { x: cx - w / 2, y: cy - h / 2, w, h };
        if (boxes.some((q) => hit(r, q)) || placed.some((q) => hit(r, q, 2))) continue;
        const cost = 10 * segs.filter((sg) => sg.e !== e && crosses(r, sg)).length + Math.abs(t - 0.5) + (horizontal ? 0 : 0.5) + extra;
        if (!best || cost < best.cost) best = { r, cx, cy, cost };
      }
    }
    if (!best) { e.label = null; hidden++; continue; }
    placed.push(best.r);
    e.label = best.r; e.labelAt = { x: best.cx, y: best.cy };
  }
  return hidden;
}

function drawPins(g, n) {
  for (const p of n.pins) {
    const lane = ancestors(p.peer)[1];
    const c = KINDS[p.peer.kind].c;
    const pg = g.append("g").attr("class", "pin").attr("transform", `translate(${p.x},${p.y})`)
      .on("click", (ev) => { ev.stopPropagation(); go(p.peer); });
    pg.append("rect").attr("width", p.w).attr("height", p.h).attr("rx", p.h / 2).attr("stroke", tint(c, 0.55))
      .attr("stroke-dasharray", "3 3");
    pg.append("text").attr("x", p.w / 2).attr("y", 16).attr("text-anchor", "middle").attr("font-size", FONT.pin).text(p.text);
    // the stub from the pin to the edge of the box, where the wire continues outside
    const extra = n.data.count ? 8 : 0, st = WIRES[strongest(p.wires)];
    const port = n.parent && (portsOf.get(n) || []).find((q) => q.pin === p);
    // to the box edge, at the port's position when it was moved off the pin's line
    const toX = (bx) => (bx - n.ox) / n.s - p.x, toY = (by) => (by - n.oy) / n.s - p.y;
    const stub = {
      WEST: { x1: 0, y1: p.h / 2, x2: toX(0), y2: port ? toY(port.y) : p.h / 2 },
      EAST: { x1: p.w, y1: p.h / 2, x2: toX(n.w + extra), y2: port ? toY(port.y) : p.h / 2 },
      NORTH: { x1: p.w / 2, y1: 0, x2: port ? toX(port.x) : p.w / 2, y2: toY(0) },
      SOUTH: { x1: p.w / 2, y1: p.h, x2: port ? toX(port.x) : p.w / 2, y2: toY(n.h + extra) },
    }[p.side];
    const flat = p.side === "WEST" || p.side === "EAST";
    const mid = flat ? (stub.x1 + stub.x2) / 2 : (stub.y1 + stub.y2) / 2;
    const d = flat ? `M${stub.x1},${stub.y1}H${mid}V${stub.y2}H${stub.x2}` : `M${stub.x1},${stub.y1}V${mid}H${stub.x2}V${stub.y2}`;
    pg.insert("path", ":first-child").attr("class", "stub").attr("d", d).attr("fill", "none")
      .attr("stroke", st.c).attr("stroke-width", st.w).attr("stroke-dasharray", "2 3").attr("opacity", 0.7);
    pg.append("title").text(`${p.out ? "To" : "From"} ${p.peer.label}${lane && lane !== p.peer ? ` (${lane.label})` : ""}\n` +
      p.wires.map((w) => `${w.from.label} → ${w.to.label}${w.label ? ": " + w.label : ""}`).join("\n") + "\nClick to go there");
  }
}

function frame(g, c) {
  const k = KINDS[c.kind], lane = c.kind === "lane";
  if (c.data.count) {
    for (const off of [8, 4]) g.append("rect").attr("x", off).attr("y", off).attr("width", c.w).attr("height", c.h)
      .attr("rx", 9).attr("fill", tint(k.c, 0.1)).attr("stroke", tint(k.c, 0.45));
  }
  g.append("rect").attr("class", "frame").attr("width", c.w).attr("height", c.h).attr("rx", lane ? 14 : 9)
    .attr("fill", lane ? tint(k.c, 0.05) : tint(k.c, c.children.length ? 0.07 : 0.13))
    .attr("stroke", lane ? tint(k.c, 0.7) : k.c).attr("stroke-dasharray", lane ? "6 5" : c.kind === "external" || c.data.status ? "4 3" : null)
    .attr("opacity", c.data.status ? 0.75 : null);
  if (!lane) g.append("rect").attr("x", 0).attr("y", 9).attr("width", 3).attr("height", Math.min(c.h - 18, 40)).attr("fill", k.c);
}

function drawLeaf(g, c) {
  const k = KINDS[c.kind];
  const ng = g.append("g").attr("class", "node").attr("data-path", c.path).attr("transform", `translate(${c.x},${c.y})`)
    .style("--glow", k.c);
  frame(ng, c);
  let y = 16 + 14;
  ng.append("text").attr("class", "n-label").attr("x", 16).attr("y", y).attr("font-size", FONT.label).text(c.label);
  if (c.data.tech) { y += 16; ng.append("text").attr("class", "n-tech").attr("x", 16).attr("y", y).attr("font-size", FONT.tech).attr("fill", k.c).text(c.data.tech); }
  y += 4;
  for (const line of c.sumLines) { y += 15; ng.append("text").attr("class", "n-sum").attr("x", 16).attr("y", y).attr("font-size", FONT.sum).text(line); }
  if (c.data.count) ng.append("text").attr("class", "n-badge").attr("x", c.w - 12).attr("y", 22).attr("text-anchor", "end").attr("font-size", 11).text(`×${c.data.count}`);
  if (c.data.status) ng.append("text").attr("class", "n-badge").attr("x", c.w - 12).attr("y", 22).attr("text-anchor", "end").attr("font-size", 10.5).text(STATUS[c.data.status]);
  wireNode(ng, c);
}

function wireNode(sel, c) {
  c.el = sel;
  sel.on("click", (ev) => { ev.stopPropagation(); select(c); if (c.children.length && openness(c) < 0.5) go(c); })
    .on("dblclick", (ev) => { ev.stopPropagation(); go(c); })
    .on("mouseenter", () => hover(c, true)).on("mouseleave", () => hover(c, false));
}

function drawFace(g, c) {
  // drawn above c's interior, in the coordinates of c's parent
  const k = KINDS[c.kind], lane = c.kind === "lane";
  const fg = g.append("g").attr("class", "face node").attr("data-path", c.path).attr("transform", `translate(${c.x},${c.y})`).style("--glow", k.c);
  const body = fg.append("g").attr("class", "closed");
  const head = fg.append("g").attr("class", "head");
  head.append("rect").attr("width", c.w).attr("height", HEAD).attr("fill", "transparent");
  if (lane) {
    head.append("text").attr("class", "lane-label").attr("x", 20).attr("y", 29).attr("font-size", 15).text(c.label);
  } else {
    head.append("text").attr("class", "n-label").attr("x", 18).attr("y", 28).attr("font-size", 16).text(c.label);
    if (c.data.tech) head.append("text").attr("class", "n-tech").attr("x", 18 + textW(c.label, 16, 600) + 12).attr("y", 28)
      .attr("font-size", 11).attr("fill", k.c).text(c.data.tech);
  }
  if (c.data.count) head.append("text").attr("class", "n-badge").attr("x", c.w - 14).attr("y", 28).attr("text-anchor", "end").attr("font-size", 12).text(`×${c.data.count}`);

  body.append("rect").attr("class", "frame").attr("width", c.w).attr("height", c.h).attr("rx", lane ? 14 : 9)
    .attr("fill", tint(k.c, lane ? 0.1 : 0.15)).attr("stroke", lane ? tint(k.c, 0.7) : k.c).attr("stroke-dasharray", lane ? "6 5" : c.data.status ? "4 3" : null);
  body.append("rect").attr("x", 0).attr("y", 12).attr("width", 4).attr("height", c.faceSize * 1.6).attr("fill", k.c);
  let y = PAD + c.faceSize;
  body.append("text").attr("class", "n-label").attr("x", PAD).attr("y", y).attr("font-size", c.faceSize).text(c.label);
  if (c.data.tech) { y += c.faceSize * 0.75; body.append("text").attr("class", "n-tech").attr("x", PAD).attr("y", y).attr("font-size", c.faceSize * 0.42).attr("fill", k.c).text(c.data.tech); }
  y += c.faceSize * 0.35;
  const fs = c.base / 30;
  for (const line of c.faceSum) { y += fs * 1.35; body.append("text").attr("class", "n-sum").attr("x", PAD).attr("y", y).attr("font-size", fs).text(line); }
  // the blocks inside, as a compact list
  y += fs * 1.2;
  const cs = c.base / 34, chips = c.children.map((x) => x.label + (x.data.count ? ` ×${x.data.count}` : ""));
  let x = PAD, row = 0;
  const maxRows = Math.max(1, Math.floor((c.h - y - PAD - cs * 2) / (cs * 2)));
  for (const t of chips) {
    const w = textW(t, cs, 500, "IBM Plex Mono") + cs * 1.2;
    if (x + w > c.w - PAD) { x = PAD; row++; }
    if (row >= maxRows) break;
    const ch = body.append("g").attr("transform", `translate(${x},${y + row * cs * 2})`);
    ch.append("rect").attr("width", w).attr("height", cs * 1.55).attr("rx", cs * 0.35).attr("fill", tint(k.c, 0.28));
    ch.append("text").attr("class", "n-tech").attr("x", cs * 0.6).attr("y", cs * 1.1).attr("font-size", cs).attr("fill", "#d5dae2").text(t);
    x += w + cs * 0.5;
  }
  if (c.data.status) body.append("text").attr("class", "n-badge").attr("x", c.w - PAD).attr("y", PAD + c.faceSize * 0.4).attr("text-anchor", "end")
    .attr("font-size", c.base / 34).text(STATUS[c.data.status]);
  body.append("text").attr("class", "n-badge").attr("x", c.w - PAD).attr("y", c.h - PAD * 0.8).attr("text-anchor", "end")
    .attr("font-size", c.base / 40).text(`${c.children.length} blocks inside — zoom in`);
  c.face = fg; c.faceBody = body; c.faceHead = head;
  wireNode(fg, c);
}

function draw() {
  defs();
  const layers = svg.append("g").attr("class", "layers");
  const emit = (n, parentGroup) => {
    const g = layers.append("g").attr("class", "interior").attr("data-path", n.path);
    n.g = g;
    drawEdges(g, n);
    drawPins(g, n);
    for (const c of n.children) {
      if (c.children.length) frame(g.append("g").attr("transform", `translate(${c.x},${c.y})`).attr("class", "under"), c);
      else drawLeaf(g, c);
    }
    for (const c of n.children) if (c.children.length) {
      emit(c);
      c.faceG = layers.append("g").attr("class", "faces");
      drawFace(c.faceG, c);
    }
  };
  emit(root);
}

// ------------------------------------------------------------------ zoom and level of detail
const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
// A block opens on screen size alone, and only inside a fully open parent, so
// one level fades in at a time and nothing opens before it is zoomed to.
const fillOf = (c) => Math.max(view.k * c.bw / innerWidth, view.k * (c.bh) / (innerHeight - 52));
const openness = (c) => {
  if (c === root) return 1;
  if (c.parent !== root && openness(c.parent) < 0.999) return 0;
  return smooth(OPEN[0], OPEN[1], fillOf(c));
};

function update() {
  const { k, x, y } = view, W = innerWidth, H = innerHeight;
  const tf = (n) => `translate(${x + k * n.ax},${y + k * n.ay}) scale(${k * n.as})`;
  root.g.attr("transform", tf(root));
  const shown = new Set([root]);
  let best = root;
  const visit = (n) => {
    for (const c of n.children) {
      if (!c.children.length) continue;
      const sx = x + k * c.bx, sy = y + k * c.by, sw = k * c.bw, sh = k * c.bh;
      const onscreen = sx < W && sy < H && sx + sw > 0 && sy + sh > 0;
      c.faceG.attr("transform", tf(n)).style("display", onscreen ? null : "none");
      if (!onscreen) continue;
      const t = openness(c);
      c.faceBody.style("opacity", 1 - t).style("display", t >= 0.999 ? "none" : null).style("pointer-events", t < 0.5 ? null : "none");
      c.faceHead.style("opacity", t).style("display", t <= 0.001 ? "none" : null);
      if (t > 0.001) {
        shown.add(c);
        c.g.attr("transform", tf(c)).style("opacity", t);
        if (t > 0.6 && sx < W / 2 && sy < H / 2 && sx + sw > W / 2 && sy + sh > H / 2) best = c;
        visit(c);
      }
    }
  };
  visit(root);
  for (const c of containers) if (c !== root) {
    c.g.style("display", shown.has(c) ? null : "none");
    if (!shown.has(c.parent)) c.faceG.style("display", "none");
  }
  $("#stage").style.backgroundPosition = `${x % 22}px ${y % 22}px`;
  if (best !== focus) { focus = best; crumbs(); }
}

function fitTransform(n, frac = 0.86) {
  const W = innerWidth, H = innerHeight - 52;
  const panel = selected && !$("#panel").hidden && innerWidth > 720 ? 400 : 0;
  const box = n === root ? { x: 0, y: 0, w: root.inner.w, h: root.inner.h } : { x: n.bx, y: n.by, w: n.bw, h: n.bh };
  let k = Math.min((W - panel) * frac / box.w, H * frac / box.h);
  if (!n.children.length) k = Math.min(k, (W - panel) * 0.32 / box.w);
  return d3.zoomIdentity.translate((W - panel) / 2 - k * (box.x + box.w / 2), 52 + H / 2 - k * (box.y + box.h / 2)).scale(k);
}
function go(n, ms = 950) {
  svg.transition().duration(ms).ease(d3.easeCubicInOut).call(zoom.transform, fitTransform(n.children.length || n === root ? n : n));
}

function crumbs() {
  const nav = $("#crumbs");
  nav.replaceChildren();
  ancestors(focus).forEach((n, i) => {
    if (i) nav.append(Object.assign(document.createElement("span"), { className: "sep", textContent: "›" }));
    const b = document.createElement("button");
    b.textContent = n === root ? "System" : n.label;
    b.onclick = () => go(n);
    nav.append(b);
  });
}

function hover(c, on) {
  const g = c.parent && c.parent.g;
  if (!g) return;
  g.classed("dim", on);
  g.selectAll(".edge").classed("hl", function () { return on && (this.dataset.src === c.id || this.dataset.dst === c.id); });
}

// ------------------------------------------------------------------ details panel
const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
const md = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");

function select(n) {
  if (selected && selected.el) selected.el.classed("selected", false);
  if (selected && selected.face) selected.face.classed("selected", false);
  selected = n;
  if (!n) { $("#panel").hidden = true; history.replaceState(null, "", location.pathname); return; }
  (n.face || n.el)?.classed("selected", true);
  history.replaceState(null, "", "#" + n.path);
  const d = n.data, k = KINDS[n.kind];
  const crossing = wires.filter((w) => isIn(w.from, n) !== isIn(w.to, n));
  const row = (w, out) => {
    const peer = out ? w.to : w.from, here = out ? w.from : w.to;
    return `<li data-go="${esc(peer.path)}"><span class="dir" style="color:${WIRES[w.kind].c}">${out ? "→" : "←"}</span>
      <span>${esc(peer.label)}${here !== n ? ` <span class="w-label">from ${esc(here.label)}</span>` : ""}
      ${w.label ? `<br><span class="w-label">${esc(w.label)}</span>` : ""} <span class="w-kind">${WIRES[w.kind].name}</span></span></li>`;
  };
  const src = d.rtl || d.src;
  $("#panel-body").innerHTML = `
    <div class="p-kind"><i style="background:${k.c}"></i>${esc(k.name)}${d.count ? ` · ×${d.count}` : ""}${d.status ? ` · ${esc(STATUS[d.status])}` : ""}</div>
    <h2>${esc(n.label)}</h2>
    ${d.tech ? `<div class="p-tech">${esc(d.tech)}</div>` : ""}
    <div class="p-path">${ancestors(n).slice(1).map((a) => `<a data-go="${esc(a.path)}">${esc(a.label)}</a>`).join("&nbsp;/&nbsp;")}</div>
    ${d.summary ? `<p class="p-summary">${md(d.summary)}</p>` : ""}
    ${d.doc ? `<div class="p-doc">${String(d.doc).trim().split(/\n\s*\n/).map((p) => `<p>${md(p)}</p>`).join("")}</div>` : ""}
    ${src ? `<h3>Source</h3><div class="p-links"><a href="${REPO}${esc(src)}" target="_blank" rel="noopener">${esc(src)} ↗</a></div>` : ""}
    ${d.bd ? `<h3>Block design</h3><div class="p-tech">${[].concat(d.bd).map(esc).join(", ")}</div>` : ""}
    ${d.meta ? `<h3>Parameters</h3><table class="p-meta">${Object.entries(d.meta).map(([a, b]) => `<tr><td>${esc(a)}</td><td>${esc(b)}</td></tr>`).join("")}</table>` : ""}
    ${n.children.length ? `<h3>Inside</h3><ul class="p-list">${n.children.map((c) => `<li data-go="${esc(c.path)}"><span class="dir" style="color:${KINDS[c.kind].c}">■</span><span>${esc(c.label)} <span class="w-label">${esc(c.data.tech || "")}</span></span></li>`).join("")}</ul>` : ""}
    ${crossing.length ? `<h3>Connections</h3><ul class="p-list">${crossing.map((w) => row(w, isIn(w.from, n))).join("")}</ul>` : ""}`;
  $("#panel").hidden = false;
  $("#panel-body").querySelectorAll("[data-go]").forEach((el) => el.addEventListener("click", () => {
    const t = byPath.get(el.dataset.go); select(t); go(t);
  }));
}

// ------------------------------------------------------------------ search
function search() {
  const input = $("#search"), list = $("#results");
  const all = [...byPath.values()].filter((n) => n !== root);
  let items = [], active = 0;
  const render = () => {
    list.replaceChildren(...items.map((n, i) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option"); li.setAttribute("aria-selected", i === active);
      li.innerHTML = `<span class="r-label">${esc(n.label)}</span><span class="r-path">${esc(ancestors(n).slice(1, -1).map((a) => a.label).join(" / ") || KINDS[n.kind].name)}</span>`;
      li.onmousedown = (ev) => { ev.preventDefault(); pick(n); };
      return li;
    }));
    list.hidden = !items.length;
  };
  const pick = (n) => { input.value = ""; items = []; render(); input.blur(); select(n); go(n); };
  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    items = q ? all.map((n) => {
      const hay = `${n.label} ${n.data.tech || ""} ${n.id} ${[].concat(n.data.bd || []).join(" ")}`.toLowerCase();
      const i = hay.indexOf(q);
      return { n, score: i < 0 ? -1 : (n.label.toLowerCase().startsWith(q) ? 0 : 1) + i / 100 + n.depth / 1000 };
    }).filter((r) => r.score >= 0).sort((a, b) => a.score - b.score).slice(0, 12).map((r) => r.n) : [];
    active = 0; render();
  });
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown") { active = Math.min(items.length - 1, active + 1); render(); ev.preventDefault(); }
    if (ev.key === "ArrowUp") { active = Math.max(0, active - 1); render(); ev.preventDefault(); }
    if (ev.key === "Enter" && items[active]) pick(items[active]);
    if (ev.key === "Escape") { input.value = ""; items = []; render(); input.blur(); }
  });
  input.addEventListener("blur", () => setTimeout(() => (list.hidden = true), 100));
}

function legend() {
  const body = $("#legend-body");
  const used = new Set([...byPath.values()].map((n) => n.kind)), usedW = new Set(wires.map((w) => w.kind));
  let html = "<h4>Blocks</h4>";
  for (const [k, v] of Object.entries(KINDS)) if (used.has(k)) html += `<span class="sw"><span class="chip" style="border-color:${v.c};background:${tint(v.c, 0.2)}"></span>${v.name}</span>`;
  html += "<h4>Wires</h4>";
  for (const [k, v] of Object.entries(WIRES)) if (usedW.has(k)) html += `<span class="sw"><svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="${v.c}" stroke-width="${Math.min(v.w, 2.4)}" stroke-dasharray="${v.dash || ""}"/></svg>${v.name}</span>`;
  body.innerHTML = html;
  const box = $("#legend"), btn = $("#legend-toggle");
  btn.onclick = () => { const c = box.toggleAttribute("data-collapsed"); btn.setAttribute("aria-expanded", !c); };
}

// ------------------------------------------------------------------ debug: ?debug
// Counts what makes a level hard to read, outlines each case in red, and shows
// the totals. The layout is clean when every count is zero.
function overlapReport() {
  const rows = [];
  const inside = (q, x, y, m = 2) => x > q.x + m && x < q.x + q.w - m && y > q.y + m && y < q.y + q.h - m;
  const hit = (r, q) => r.x < q.x + q.w && r.x + r.w > q.x && r.y < q.y + q.h && r.y + r.h > q.y;
  for (const n of containers) {
    const nodes = [...n.children.map((c) => ({ id: c.id, x: c.x, y: c.y, w: c.w + (c.data.count ? 8 : 0), h: c.h + (c.data.count ? 8 : 0) })),
      ...n.pins.map((p) => ({ id: p.id, x: p.x, y: p.y, w: p.w, h: p.h }))];
    const segs = n.edges.filter((e) => e.pts).flatMap((e) => e.pts.slice(1).map((b, i) => ({ e, a: e.pts[i], b })));
    const bad = [];
    const row = { level: n.path || "root", wires: n.edges.length, throughBlock: 0, sharedSegment: 0, sharedEnd: 0,
      labelOnBlock: 0, labelOnLabel: 0, pinOffSide: 0, unlabelled: n.edges.filter((e) => e.text && !e.label).length };
    for (const sg of segs) for (const q of nodes) {
      if (q.id === sg.e.src.id || q.id === sg.e.dst.id) continue;
      let crossed = false;
      for (let t = 0.05; t < 1; t += 0.05) if (inside(q, sg.a.x + (sg.b.x - sg.a.x) * t, sg.a.y + (sg.b.y - sg.a.y) * t)) crossed = true;
      if (crossed) { row.throughBlock++; bad.push({ x: Math.min(sg.a.x, sg.b.x), y: Math.min(sg.a.y, sg.b.y), w: Math.abs(sg.b.x - sg.a.x) + 1, h: Math.abs(sg.b.y - sg.a.y) + 1 }); }
    }
    for (let i = 0; i < segs.length; i++) for (let j = i + 1; j < segs.length; j++) {
      const A = segs[i], B = segs[j];
      if (A.e === B.e) continue;
      const span = (u, v, key) => Math.min(Math.max(u.a[key], u.b[key]), Math.max(v.a[key], v.b[key])) - Math.max(Math.min(u.a[key], u.b[key]), Math.min(v.a[key], v.b[key]));
      const hz = (u) => Math.abs(u.a.y - u.b.y) < 0.5, vt = (u) => Math.abs(u.a.x - u.b.x) < 0.5;
      if ((hz(A) && hz(B) && Math.abs(A.a.y - B.a.y) < 3 && span(A, B, "x") > 6) || (vt(A) && vt(B) && Math.abs(A.a.x - B.a.x) < 3 && span(A, B, "y") > 6)) {
        row.sharedSegment++; bad.push({ x: Math.min(A.a.x, A.b.x) - 2, y: Math.min(A.a.y, A.b.y) - 2, w: Math.abs(A.b.x - A.a.x) + 4, h: Math.abs(A.b.y - A.a.y) + 4 });
      }
    }
    const ends = new Map();
    for (const e of n.edges) if (e.pts) for (const [pt, node, port] of [[e.pts[0], e.src, e.sp], [e.pts.at(-1), e.dst, e.tp]]) {
      const key = `${Math.round(pt.x)},${Math.round(pt.y)}`;
      const owner = port || node.id;
      if (ends.has(key) && ends.get(key) !== owner) { row.sharedEnd++; bad.push({ x: pt.x - 4, y: pt.y - 4, w: 8, h: 8 }); }
      ends.set(key, owner);
    }
    const labels = n.edges.filter((e) => e.label).map((e) => e.label);
    for (const r of labels) for (const q of nodes) if (hit(r, q)) { row.labelOnBlock++; bad.push(r); }
    for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) if (hit(labels[i], labels[j])) { row.labelOnLabel++; bad.push(labels[i]); }
    // a wire into a nested block must end on the side its pin faces inside
    for (const e of n.edges) if (e.pts) for (const [pt, node, port, out] of [[e.pts[0], e.src, e.sp, true], [e.pts.at(-1), e.dst, e.tp, false]]) {
      if (!node.children || !node.children.length) continue;
      const q = (portsOf.get(node) || []).find((x) => x.id === port);
      const want = !port ? null : { x: node.x + q.x, y: node.y + q.y };
      if (!want || Math.hypot(pt.x - want.x, pt.y - want.y) > 3) { row.pinOffSide++; bad.push({ x: pt.x - 5, y: pt.y - 5, w: 10, h: 10 }); }
    }
    for (const r of bad) n.g.append("rect").attr("class", "debug-mark").attr("x", r.x - 2).attr("y", r.y - 2)
      .attr("width", r.w + 4).attr("height", r.h + 4).attr("fill", "none").attr("stroke", "#ff3b3b").attr("stroke-width", 2);
    rows.push(row);
  }
  return rows;
}

function showDebug() {
  const rows = overlapReport();
  window.mapReport = rows;
  const keys = ["throughBlock", "sharedSegment", "sharedEnd", "labelOnBlock", "labelOnLabel", "pinOffSide"];
  const total = Object.fromEntries(keys.map((k) => [k, rows.reduce((a, r) => a + r[k], 0)]));
  console.table(rows);
  const box = document.createElement("pre");
  box.className = "debug";
  box.textContent = "Overlaps, all levels\n" + keys.map((k) => `${k.padEnd(14)} ${total[k]}`).join("\n") +
    `\nlabels hidden   ${rows.reduce((a, r) => a + r.unlabelled, 0)}`;
  document.body.append(box);
}

// ------------------------------------------------------------------ start
async function main() {
  await document.fonts.load('600 15px "IBM Plex Sans"');
  await document.fonts.load('400 11px "IBM Plex Mono"');
  await document.fonts.load('500 11px "IBM Plex Mono"');
  const text = await (await fetch("model.yaml", { cache: "no-cache" })).text();
  const t0 = performance.now();
  root = build(jsyaml.load(text), null);
  loadCache(text);
  toLayOut = [...byPath.values()].filter((n) => n.children.length).length;
  collectWires(root);
  const t1 = performance.now();
  await layout(root);
  saveCache();
  const t2 = performance.now();
  place(root, 0, 0, 1);
  draw();
  console.info(`map: parse ${Math.round(t1 - t0)} ms, layout ${Math.round(t2 - t1)} ms (${elkStats.calls} ELK calls), draw ${Math.round(performance.now() - t2)} ms`);
  legend();
  search();
  const minAs = Math.min(...containers.map((c) => c.as * c.s || 1), ...containers.map((c) => c.as));
  zoom = d3.zoom().scaleExtent([0.05, 3 / minAs]).on("zoom", (ev) => {
    view = ev.transform; requestAnimationFrame(update);
    if (ev.sourceEvent) $("#hint").classList.add("gone");
  });
  svg.call(zoom).on("dblclick.zoom", null);
  svg.on("click", () => select(null));
  $("#panel-close").onclick = () => select(null);
  addEventListener("resize", update);
  addEventListener("keydown", (ev) => {
    if (ev.target.tagName === "INPUT") return;
    if (ev.key === "/") { ev.preventDefault(); $("#search").focus(); }
    if (ev.key === "Escape") { if (focus && focus !== root) go(focus.parent); else select(null); }
    if (ev.key === "f" || ev.key === "F" || ev.key === "0") go(root);
  });
  $("#status").remove();
  if (new URLSearchParams(location.search).has("debug")) showDebug();
  const start = byPath.get(decodeURIComponent(location.hash.slice(1)));
  svg.call(zoom.transform, fitTransform(root, 0.92));
  if (start && start !== root) { select(start); setTimeout(() => go(start, 1400), 300); }
}
main().catch((err) => { const s = $("#status"); s.classList.add("error"); s.textContent = String(err.stack || err); console.error(err); });
