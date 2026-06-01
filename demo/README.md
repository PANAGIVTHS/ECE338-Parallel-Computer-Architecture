# Interactive nbody FPGA demo

This folder contains the browser-controlled nbody demos so the normal `programs/run.sh` workflow stays focused on building/running programs. It supports the original 2D `nbody` program and the newer `nbody-3d` program.

## Run

```bash
# Software backend, no FPGA needed, original 2D program
./demo/run.sh --fake --steps 4 --no-browser --http-port 8770

# Software backend, no FPGA needed, 3D program
./demo/run.sh --program nbody-3d --fake --steps 4 --no-browser --http-port 8771

# FPGA backend over UART, original 2D program
./demo/run.sh --port /dev/ttyUSB1 --steps 1

# FPGA backend over UART, 3D program
./demo/run.sh --program nbody-3d --port /dev/ttyUSB1 --steps 1
```

Browser controls:

- Space / `p`: play-pause
- `n` / Right Arrow: step exactly one simulation step
- Enter: step by the current speed
- `r` or the Reset button: reset the 3D simulation to its initial environment
- `+` / `-`: increase/decrease simulation steps per displayed frame
- `[` / `]`: decrease/increase target FPS
- In the `nbody-3d` UI, drag the mouse to rotate/orbit the three.js camera and use the scroll wheel to zoom.

## DMEM update caching

The FPGA backend keeps a host-side cache of the last DMEM values that this demo wrote. Before each kernel launch it compares the adapter's requested DMEM updates against that cache and sends only changed words, grouped into contiguous `load_dmem_bin()` bursts.

For the current nbody ABI this means:

- Initial launch still clears the output/data windows once and writes the argument block.
- Repeated runs with the same speed do **not** resend the unchanged magic word or unchanged step count.
- After the first run, reset changes from `1` to `0` once and then is not resent.
- Usually only `start_step` changes per frame, so the UART write shrinks to a single DMEM word before each run.

Correctness note: this cache only skips values previously written by the host. It does not assume anything about FPGA-computed output state; the demo still dumps the output window after every run.

## What it would take to make nbody 3D

### Program/kernel (`programs/nbody/nbody.c`)

A real 3D simulation is a medium-sized program change, not just a display change.

Required changes:

- Add `pos_z[CORES]` and `vel_z[CORES]` arrays for both RISC-V and x86 code paths.
- Add deterministic `init_z()` and `init_vz()` functions.
- Change `force_weight(dx, dy)` to `force_weight(dx, dy, dz)` and include `abs(dz)` in the distance metric.
- In the inner interaction loop, load `zj`, compute `dz`, accumulate `az`, update `vz`, and update `new_z`.
- Write `GPGPU_OUTPUT[(tid * 3) + 0..2] = x,y,z` instead of two words per body.
- Update native CSV header/rows from `xN,yN` to `xN,yN,zN`.

Cost/risk:

- Runtime work increases by roughly one more coordinate's worth of integer operations per pairwise interaction: extra loads, subtract, abs/sign, multiply/add accumulation, velocity update, and store.
- DMEM output grows from `32 bodies * 2 words = 64 words` to `32 * 3 = 96 words`, i.e. +128 bytes per frame.
- Persistent per-core state grows from 4 arrays to 6 arrays.
- It should still fit the existing UART demo flow, but FPGA kernel runtime will increase and the compiler may create more register pressure/spills.
- Correctness testing must compare RISC-V/FPGA output against x86 for multiple steps, because 3D changes the numerical trajectory.

Estimated implementation size: roughly 40-80 lines changed in `nbody.c` if we keep the same branchless integer model.

### Loader/adapter (`programs/nbody/fpga.py` and demo backend)

This is a small-to-medium ABI change.

Required changes:

- Change `GPU_OUTPUT_WORDS` from `NUM_BODIES * 2` to `NUM_BODIES * 3`.
- Parse output addresses as `base + body * 3 + {0,1,2}`.
- Generate CSV headers and rows with `zN` fields.
- Update `process_output()` and SVG preview logic. The SVG could either ignore z, use z for radius/brightness, or be replaced by a 3D-capable preview.
- Update the interactive demo `Frame` JSON from `[x,y]` to either `[x,y,z]` or object fields `{x,y,z}`.
- Update the fake backend so software UI tests match the new 3D native behavior.

Estimated implementation size: roughly 40-100 lines across `fpga.py` and `demo/interactive.py`, depending on whether backwards-compatible 2D/3D parsing is kept.

### Visualization

There are two viable levels:

1. **Low-risk pseudo-3D on the existing Canvas 2D renderer**
   - Keep the current browser stack.
   - Add a simple camera rotation/projection from `(x,y,z)` to screen `(x,y)`.
   - Sort bodies/trails by depth; use z/depth for radius, alpha, and brightness.
   - Add keyboard/mouse camera controls later if desired.
   - This is enough for a demo and avoids dependencies.
   - Estimated size: 80-180 lines in `demo/interactive.py` plus similar changes in `visualize.py` if MP4 export must support 3D.

2. **True WebGL/three.js visualization**
   - MDN notes Canvas is mainly 2D, while WebGL uses the same `<canvas>` element for hardware-accelerated 2D/3D graphics.
   - three.js `BufferGeometry` stores vertex positions in GPU buffers and uses item size 3 for x/y/z, which fits a point-cloud/particle view naturally.
   - For only 32 bodies, performance is not a concern; the reason to use WebGL/three.js would be nicer camera controls and depth rendering, not speed.
   - Tradeoff: introduces a third-party frontend dependency/CDN or vendored JS file.
   - Estimated size: 150-300 lines if using three.js, more if writing raw WebGL.

Recommendation: first implement the 3D physics/ABI plus pseudo-3D Canvas projection. It is the smallest correct step and keeps the demo self-contained. Move to three.js only if you want orbit controls, depth-correct trails, or more polished 3D visuals.
