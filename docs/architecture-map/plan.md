# Architecture map: plan

## Decision

The map is a semantic-zoom diagram: one canvas, where zooming into a block
reveals its internals in place. LikeC4 was tried first, in milestones M0 and
M1. It draws each level as a separate view and navigates between them, which
is not what the map is for, so it was removed. No existing tool combined
nested in-place zoom with automatic layout of every level. The viewer is
therefore about 600 lines on established libraries: ELK for layout, d3-zoom for
pan and zoom, and js-yaml for the model.

## Done

- `model.yaml`: 255 blocks in five lanes (111 before milestone Z3). These are the kernel software, the
  workstation, the host firmware, the Zynq block design and off-chip devices.
  The GPGPU goes down to the pipeline registers of a streaming processor and to
  the rings of the DDR backend.
- The viewer has semantic zoom, a details panel with source links and
  connections, search, breadcrumbs, deep links, pins that jump to the other end
  of a wire, and a legend.
- `gpgpu docs map:validate|serve|build`, with no tools beyond Python.
- Published on hv1, port 8765.

## Next

Four milestones, in this order. Each one ends with a redeploy to hv1 so it can
be checked in the browser. Z1 and Z2 are done; their results are at the end of
each section.

### Z1. Zoom behaviour

**Problem.** Some blocks open without any zooming. A block opens when it fills
most of the screen, or when its contents are already legible. The second rule
opens every block with few children early, because its children are drawn at
nearly full size. At the starting view, Off chip (children at 90%) is open and
Workstation (64%) has started to open. Kernels (90%), the BRAM backend (87%)
and the gpgpu CLI (73%) open as soon as their lane does.

**Changes.**
1. A block opens on screen size alone: it starts to open when it covers about
   40% of the screen in its larger dimension, and is fully open at 60%.
   Legibility no longer opens anything.
2. A block opens only once its parent is fully open, so two levels never fade
   in at the same time.
3. Clicking a closed block flies to it and leaves it fully open. `Esc` flies to
   the parent and leaves the block closed.
4. The fade is shorter, so a half-open block, with its face and its contents
   on top of each other, is never on screen for long.

**Done when** the starting view shows five closed lanes, and every block opens
only when zoomed to.

**Result: done.** The opening thresholds are 42% and 56%. At the starting view
no block is open. Scrolling in opens the lanes first and their children on
later steps, never in the same step. Clicking a block leaves it fully open, and
`Esc` closes it again.

### Z2. Wires and labels

**Measured.** ELK's routing is clean. At every level, no wire passes through a
block and no two wires share a segment. The overlaps come from how the viewer
places wire labels, at the middle of each wire's longest segment, with no
collision check:

| Overlap | Count, all levels |
|---|---|
| A label on a block | 69 |
| A label on another label | 9 |

The worst levels are the memory subsystem (9 labels on blocks), the software
lane (9), the SM (7), the DDR backend (6), the host lane (6) and the root (6).

Close wires also look merged when zoomed out: ELK keeps them 11 units apart,
which is about 3 pixels when a level is drawn at 30%. Every wire into a block
also meets it at a point ELK picks freely, so several wires can arrive at one
point.

**Changes.**
1. **Label placement.** Try candidate positions along every segment of a wire,
   and keep the first that touches no block, pin or placed label. A label with
   no free position is not drawn on the canvas. It stays in the wire's tooltip
   and in the panel's connection list.
2. **Ports.** Give each wire its own port on its block: inputs on the side
   facing the flow, outputs on the opposite side, spaced along that side. This
   is ELK's `FIXED_SIDE` port constraint. Wires then arrive side by side
   instead of at one point.
3. **Spacing.** Raise the wire-to-wire and wire-to-block spacing on dense
   levels so parallel wires stay visibly apart when the level opens.
4. **Pins match the outside.** Inside an open block, put each pin on the side
   of the box where its wire arrives from outside, in the same order. A wire
   then visibly continues from the parent level into the block.
5. **Wide levels.** Wrap levels with an aspect ratio above 3, such as the DDR
   backend, onto two rows. This uses ELK's graph wrapping, applied only to
   those levels, so their boxes stop leaving empty space.
6. **Check.** Turn the overlap measurement into a debug mode of the page,
   opened with `#debug`. It outlines every overlap and prints the counts.

**Done when** the debug mode reports zero for all six counts at every level.
Those counts are wires through blocks, shared segments, shared end points,
labels on blocks, labels on labels and pins off their side.

**Result: done.** All six counts are zero at every level, and 166 of 167 wire
labels are drawn. The hidden one is "branch target (lane 0)", inside a lane.
Its wire ends at a pin that already reads "Program counter", and the label
stays in the tooltip. Changes from the plan:

- Per-wire ports were only needed on nested blocks, where ELK cannot see the
  pins inside. Leaves already got distinct end points from ELK.
- Pins are now one per peer, direction and wire kind. Wires of two kinds to the
  same peer used to share a port and overlap.
- ELK's graph wrapping (item 5) was tried and dropped. It routed wires around
  the whole level and put output pins on the wrong side. Wide levels instead
  get boxes up to 4.5 times as wide as tall.
- The debug mode is opened with `?debug`, not `#debug`, because the hash
  already names a block.

The GPGPU level is still the busiest, with 10 blocks and 24 wires. Z3 should
group its control blocks (AXI4-Lite slave, MMIO controller, CSR bank,
execution controller, performance counters) into one block.

### Z3. The model: complete and checked against the sources

**Correctness first.** Go through each instantiation in `GPGPU.sv`,
`StreamingMultiprocessor.sv`, `StreamingProcessor.sv`, `MemorySubsystem.sv`,
`BRAMBackend.sv`, `DDRBackend.sv` and `design_1.tcl`. Check every wire against
the actual port connections. The wires inferred from comments come first: the
forwarding paths, the hazard flush, the multiplier's write-back, the port
controller internals and the IMEM owner mux. Name the real signals in each
wire's label.

**Additions**, by lane:

| Lane | What is added | Source |
|---|---|---|
| Hardware | The register map as a block: identity (5 registers), control and status (4), fault (3), and the IMEM and DMEM windows, one leaf per register with offset and fields | `ControlPkg.sv` |
| Hardware | Performance counters split into their groups: run, the AW, W, AR and R channels, the write and read rings, coalescing, BRAM, and the per-warp leaves | `PerfPkg.sv` |
| Hardware | The memory map as a block: DMEM, FB0, FB1 and GMEM, with base and size | `gpu_pkg.sv` |
| Hardware | The IP wrapper `AXI4Top` around the core, with its two AXI ports, IRQ and status outputs | `AXI4Top.v` |
| Hardware | Experimental modules, marked as such: warp scheduler, scoreboard, warp state mask, FIFO and stack | `experimental/` |
| Board | Clock and reset nets: FCLK0 and FCLK1, the pixel clock, the three reset blocks, the IRQ concat, the board-level ports (DDR, FIXED_IO, TMDS, UART) and the constraints | `design_1.tcl`, `smart_zynq.xdc` |
| Board | Video pipeline settings: VDMA frame stores and burst length, the converter's byte remap, timing | `design_1.tcl` |
| Host | All 21 monitor commands as leaves of their groups | `main.c` |
| Host | All 18 driver functions, grouped as now | `gpgpu_driver.h` |
| Software | All 18 kernels, grouped as framebuffer demos, compute, and tests | `software/programs` |
| Workstation | The test tooling: assembler, GPGPU model, expected-result generator, program checker, random tester, the test cases and the waveform visualiser | `tools/tests`, `tests/hardware/rtl` |
| Workstation | The board tooling: the UART transport, the Vivado and Vitis flows, IP packaging and the bitstream | `tools/board`, `tools/gpgpu/adapters` |

No level gets more than about nine children; larger sets are grouped.

**Checks in `map:validate`.**
1. A block whose `tech` names an RTL module must have `module <tech>` in its
   `rtl` file.
2. A `meta` value written as a constant name, for example `SP_PER_SM`, is
   resolved from `rtl_constants.txt` and shown with its value. A constant name
   that does not exist fails validation.
3. The block design cells in the model must match `create_bd_cell` in
   `design_1.tcl`, in both directions.

**Done when** every wire has been checked against a port connection, and
validation passes with the three new checks.

**Result: done.** Every wire was checked against the instance connections of
`GPGPU.sv`, `StreamingMultiprocessor.sv`, `StreamingProcessor.sv`,
`MemorySubsystem.sv`, `PortController.sv`, `DDRBackend.sv` and `design_1.tcl`.
The model grew from 111 blocks to 255, with 229 wires. Corrections the check found:

| Was | Is |
|---|---|
| AXI4-Lite slave inside the core | In the wrapper `gpgpu_axi`; the core is `GPGPU.sv` |
| ID/EX register in each lane | One shared register in the SM |
| IF/ID register holds the instruction | It holds the PC; the instruction is IMEM's output register |
| Multiplier writes back through MEM/WB | Its product goes back into the ALU |
| Port controllers pass store data to DDR | Both backends read every lane's request directly |
| Port controller as claim, decode, response, word select | Decode, claim, a state machine, a response mux |
| Board: Zybo Z7-20, DDR3 1 GiB | `xc7z020clg484-1`, `smart_zynq.xdc`; 512 MiB of DDR mapped |
| Driver waits on the interrupt | Interrupt only with `GPGPU_USE_IRQ`; polls STATUS otherwise |
| `HostControllerProcessor` | The module in that file is `HostCommandProcessor` |

Also added: the stall, exit and warp-leaf logic of the SM, grouped as "Warp
control"; the operand select and branch logic of a lane; the quiet detection
of the memory subsystem; the status pins, the IRQ bus and the tied inputs of the
block design.

The three checks are in `map:validate` and in the CLI tests. Values such as
sizes, addresses, counts and clock rates are written as `${NAME}` and come from
the RTL packages and the configuration, so the map cannot drift from them.

Two viewer changes came with the larger model:

- **Wire bundling.** One line per pair of blocks and direction, and pins named
  after the neighbour at the level where the wire runs. The busiest levels
  dropped from 36 to 23 lines (SM) and from 29 to 21 (core).
- **Layout cache.** The first load lays out the model in about five seconds;
  later loads read the layouts from the browser's storage in about one.
  A pool of ELK web workers was tried first and was slower.


### Z4. What the page is still missing

1. **Flows.** A flow is a named, ordered list of wires with a note per step,
   declared in the model. The page steps through it, flying to each wire and
   highlighting it. These five flows come first:
   - **Build to run:** a kernel from source to IMEM.
   - **Kernel launch:** `run` → driver → AXI4-Lite → CSR → execution controller
     → SM → exit → IRQ → driver.
   - **Host memory access:** an IMEM or DMEM window while idle.
   - **DDR store:** lane requests → group former → write ring → AXI4 master →
     HP0.
   - **Display:** a framebuffer from DDR through the VDMA to HDMI.
2. **SVG export** of the current level, for the LaTeX report.
3. **Offline copy.** `map:build` copies d3, ELK, js-yaml and the fonts into the
   site.
4. **Light theme**, following the system setting, with a toggle.

## Order of work

Z1 and Z2 change only the viewer, so they come first and make every later
review easier. Z3 is the largest part. Z4 depends on Z3, because the flows name
wires that Z3 corrects or adds. The model and viewer formats stay compatible
throughout. Flows are new keys, and the old keys keep their meaning.
