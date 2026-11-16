# DOOM

The game's logic runs on the ARM; its 3D view is drawn by the GPU.

The game is [doomgeneric](https://github.com/ozkl/doomgeneric), fetched by the build at the commit
`game.yaml` pins and compiled unchanged. It is GPLv2, as is the code in `port/`, which is written
against it. The GPU side is `software/programs/doom`.

## Running it

DOOM needs an IWAD, which is not in the repository: the shareware `doom1.wad`, `doom.wad` or
`doom2.wad` from a copy of the game, or a [Freedoom](https://freedoom.github.io) WAD. Set its path
once in `config/local.yaml`:

```yaml
software:
  games:
    settings:
      doom:
        assets:
          wad: ~/games/doom1.wad
```

On a PC:

```bash
./gpgpu rtl constants                  # once, for verify
./gpgpu software games:doom:sim        # frames in build/software/games/doom/sim/frames
./gpgpu software games:doom:verify
```

On the board, with the hardware built from the current RTL:

```bash
./gpgpu vitis build:games:doom
./gpgpu fpga games:doom:deploy
```

The game starts with its demo. Play it from a serial terminal on the board's UART (115200 baud),
for example `picocom -b 115200 /dev/ttyUSB0` on the machine the board is connected to.

| Key | Action |
| --- | --- |
| arrows, or `w` `a` `s` `d` | Move and turn |
| `q`, `e` | Strafe |
| `f` | Fire |
| space | Use (open doors) |
| upper-case letter | The same with Shift: run |
| `1`..`7` | Weapon |
| Enter, Escape | Menus |
| Tab | Map |
| `-`, `=` | Screen size |

The letters above reach DOOM as those actions, so a cheat code or savegame name cannot contain
them. The table is `keymap` in `port/doom_game.c`.

Game arguments (`software.games.settings.doom.args`): DOOM's own, such as `-warp 1 3 -skill 4`,
and two of the port:

| Argument | Effect |
| --- | --- |
| `-nogpu` | The ARM draws the view with DOOM's own loops; the kernel only scales the picture. For comparison |
| `-gpustats` | Once a second, print what a frame costs: runs, batches, columns, spans, and how many lanes had work |

## How the work is split

DOOM draws its view with two loops. `R_DrawColumn` draws a vertical run of a wall, sprite or sky
texture, and `R_DrawSpan` a horizontal run of a floor or ceiling. Everything before them decides
what to draw: the BSP walk, the clipping, the fixed-point setup of each run. That part is
branchy and stays on the ARM. The two loops only add, shift and load bytes, and the kernel runs
them, 32 at a time.

The game is linked with `--wrap` for those functions (the `wrap` list of `game.yaml`), so its
calls arrive in `port/doom_render.c`, which records them in GMEM. At the end of the view the
kernel draws them into DOOM's 320x200 screen, which also lives in GMEM. The ARM then draws the
status bar, text and menus into the same screen, and a second run of the kernel scales it to the
display through the palette.

| File | Role |
| --- | --- |
| `port/doom_render.c` | Records the draw calls, groups them into batches, runs the kernel |
| `port/doom_video.c` | DOOM's screen and palette (replaces `i_video.c`) |
| `port/doom_wad.c` | The WAD, copied into GMEM and used in place (replaces `w_file.c`) |
| `port/doom_system.c` | DOOM's heap in GMEM, errors, exit (replaces `i_system.c`) |
| `port/doom_game.c` | Start-up, time, keys |
| `software/programs/doom/doom_abi.h` | What the ARM hands to the kernel |
| `software/programs/doom/doom_kernel.h` | How a lane draws it |

### No divergence

Every lane of the GPU takes every branch with lane 0. The kernel keeps to that as follows:

- A **span** is drawn by all lanes together, lane `i` on pixels `i`, `i + 32`, ... The loop count
  is the span's length, the same word in every lane.
- A **batch** holds up to one column per lane and is drawn row by row for as many rows as its
  tallest column needs. The ARM computes that count. A lane whose column does not cover the
  current row computes its pixel anyway and stores it to a spare byte.

The ARM is what a divergence stack would otherwise be: it sorts columns into batches of similar
height and neighbouring position, so that few lanes wait and the stores of a row are one burst.

### Order

Walls, floors and sky are drawn first. DOOM's clipping keeps them off each other's pixels, so
they may be batched in any order. Sprites and see-through walls follow, back to front: they fill batches in
DOOM's order, and a column that would touch a pixel of its own batch starts the next one. The
kernel draws the opaque batches, then the spans, then the rest.

Not drawn by the kernel, but by DOOM's own loops on the ARM after everything recorded so far:
the low-detail mode (F5), the partial-invisibility effect, and recoloured sprites.

## What is checked, and what is not

Checked on a PC:

- The simulation's frames are identical to those of `-nogpu`, pixel for pixel, over the demo
  loops of the shareware WAD and both Freedoom WADs, new games started from the menu with
  scripted keys, several levels, both detail modes, reduced screen sizes, and with 4 and 32 lanes.
- The kernel's RISC-V image on the GPGPU model, against runs captured from the simulation:
  no divergent branch, no fault, the same memory. It is 203 instructions, uses a 32-byte stack
  frame, and no divide or high-multiply instruction.
- `gpgpu vitis build:games:doom` builds `doom_host.elf` with Vitis 2025.2 against the BSP of the
  current hardware: 8 MiB of heap, 1 MiB of stack and the WAD are in it, and DOOM's draw functions
  point at the port's.

Not checked: the game has not run on the board. The frame rate is therefore unknown. From the model's counts for one frame of the demo:

| Run of the kernel | Instructions | Store bursts | Load bursts (beats) |
| --- | --- | --- | --- |
| The 3D view | 35,000 | 2,200 | 40,600 (134,000) |
| Scaling to 960x720 | 178,000 | 21,600 of 16 beats | 17,100 (40,200) |

The scaling writes 691,200 pixels and is the larger part. A smaller picture
(`software.games.platform.output`) cuts it in proportion.

## Limits

- A UART terminal holds one key at a time; see `platform/gp_input_uart.c`.
- No sound, no savegames (there is no file system) and no network game.
- The display switches framebuffers at its next refresh, without waiting for it. If a frame ever
  takes under 17 ms, the top of the picture may tear.
