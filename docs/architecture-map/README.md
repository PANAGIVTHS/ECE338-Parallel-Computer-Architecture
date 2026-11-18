# Architecture map

A zoomable diagram of the whole system, from the kernel sources to the inside
of one streaming processor. Zooming into a block opens it in place: its
summary fades out and its own diagram fades in, down to the leaves.

- `model.yaml`: the model, one tree of blocks and the wires between them.
- `viewer/`: the static page that lays out and draws it (d3, ELK, js-yaml).

## Use it

| Action | How |
|---|---|
| Zoom into a block | Scroll over it, or click it |
| Pan | Drag |
| Inspect | Click a block: the panel shows its source, parameters, contents and connections |
| Follow a wire out of a block | Click the dashed pin at the edge of the diagram |
| Go up a level | `Esc`, or a breadcrumb |
| Fit everything | `F` |
| Find a block | `/`, then type |

A link to a block is the page URL with its path as the hash, for example
`#board.gpgpu.memsys.ddr`. The page opens zoomed onto that block.

## Run it

```bash
./gpgpu docs map:validate   # keys, kinds, wires and source paths
./gpgpu docs map:serve      # http://127.0.0.1:8731/, reads model.yaml on every reload
./gpgpu docs map:build      # the static site in build/docs/architecture-map
```

`map:serve` needs nothing but Python. The page loads its three libraries and
its fonts from public CDNs, so the browser needs internet access.

## Publish it

The site is four static files. The team copy is on hv1, served by a user
systemd service, `gpgpu-map.service`, on port 8765 from `~/gpgpu-bd/site`:

```bash
./gpgpu docs map:build
rsync -az --delete build/docs/architecture-map/ jason@hv1:~/gpgpu-bd/site/
```

Then open http://hv1:8765/.

## Edit the model

A block:

```yaml
- id: ddr                       # unique among its siblings; the path is board.gpgpu.memsys.ddr
  label: DDR backend
  kind: module                  # lane ip module memory regs bus process command artifact tool external
  tech: DDRBackend              # the module, IP or file name, in monospace
  summary: One line, shown on the block.
  doc: |                        # optional: paragraphs for the panel; `code` is allowed
    ...
  rtl: hardware/rtl/gpgpu/memory/ddr/DDRBackend.sv    # or src: for software; links to GitHub
  bd: gpgpu_axi_0               # optional: the block design cell(s) it stands for, a name or a list
  meta: {AXI data: "${AXI_DATA_W} bit"}   # optional: shown as a table
  count: ${config:architecture.num_cores}  # optional: drawn as a stack
  status: experimental          # optional: experimental or deprecated, drawn dashed
  children: [...]               # optional: makes the block zoomable
  wires: [...]                  # wires between blocks inside this one
```

**Values from the sources.** Anywhere in the model, `${NAME}` is a constant of
the RTL packages, read with pyslang, and `${config:a.b}` is a configuration
value. A constant name can be bare, or qualified as `pkg::NAME` when two
packages define it. `:hex` prints `0x1800_0000`, and `:kib` and `:mib` print a
size. The build and the live server put the values in. Write sizes,
addresses, counts and clock rates this way, so the map follows the RTL.

A wire is one string: `"<from> -> <to> | <kind> | <label>"`. Both ends are
paths relative to the block that declares the wire, so declare it on the
lowest block that contains both ends. The kinds are `data`, `control`, `axi`,
`axilite`, `stream`, `uart`, `irq`, `clock`, `produces` and `perf`.

At every level, all the wires from one child to another are one line, coloured
by the strongest kind among them, in this order: AXI4, AXI4-Lite, stream, IRQ,
UART, clock, control, data, produces, perf. A wire that leaves the block ends at
a pin. The pin names the block at the other end, at the level where the wire
runs between two siblings. Inside the SM, for example, every wire to the memory
subsystem ends at one "Memory subsystem" pin. The line's tooltip and the panel
list each wire.

Rules that keep the map readable:

- A block with more than about nine children is too many for one level. Group them.
- `summary` is one sentence, short enough for three lines on a leaf.
- Name RTL modules, IP cells and files exactly in `tech`, so search finds them.
- Run `./gpgpu docs map:validate` before committing. It fails on any of these:
  - a wire to a block that does not exist;
  - an `rtl` or `src` path that does not exist;
  - a `${...}` value that does not resolve, or a bare constant name that is ambiguous;
  - a module-like block whose `tech` is one identifier that its `rtl` file does
    not declare as a module;
  - a cell of `hardware/bd/design_1.tcl` that no block names in `bd`, or a `bd`
    name that is not a cell.

  The CLI tests run the same validation, so a change to the RTL or the block
  design that the map does not follow fails the tests.

## How the viewer works

Each block with children is laid out on its own by ELK, the Eclipse Layout
Kernel. Both directions are tried, and the shape closer to a screen is kept.
Its box at the parent level keeps that shape with a bounded area, and the
diagram is drawn scaled inside it.

- **Opening.** A block opens on screen size alone. It starts to open when it
  covers 42% of the screen in either dimension and is fully open at 56%. It
  opens only inside a fully open parent, so one level fades in at a time.
- **Wires across levels.** A wire into a nested block meets its box where the
  matching pin sits inside. When the block opens, a dotted stub joins the pin
  to that point, so the wire visibly continues. A wire to a block as a whole
  meets it beside its title.
- **Labels.** Each label goes where it touches no block, pin or other label,
  preferring spots that cross no other wire. Where a label finds no spot, the
  level is laid out again with more room, up to two more times. A label that
  still has no spot stays in the wire's tooltip and in the panel.
- **Speed.** The first visit lays out every level, about five seconds, with a
  counter. The result is kept in the browser's local storage, keyed by the model
  and the layout rules, so a reload takes about a second. A new model is laid
  out again on its first load.
- **Drawing.** Every level has its own transform, computed in double precision,
  so deep levels stay sharp. Off-screen and closed levels are hidden.

### Checking the layout

Open the page with `?debug`, for example `http://127.0.0.1:8731/?debug`. Every
overlap is outlined in red, and a box shows the totals over all levels: wires
through blocks, wires sharing a segment, wires sharing an end, labels on
blocks, labels on labels, and wires off their pin. The browser console has the
counts per level. A clean layout is zero on all six. After a model change,
check this before publishing.
