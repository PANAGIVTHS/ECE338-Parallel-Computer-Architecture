# Games

A game here is a program whose logic runs on the ARM CPU and whose drawing runs on the GPU,
through a kernel. Each game is one directory with a manifest; everything a game needs from the
machine comes from `platform/`, which exists twice: for the board and for a PC.

```text
software/games/
  platform/            what every game shares
    gp.h                 the API a game uses: time, console, keys, GMEM, the GPU, the display
    gp_port.h            what an implementation of the platform provides
    gp_main.c            console, GMEM allocator, built-in files, picture placement, main loop
    gp_input.c           the list of input devices
    gp_input_uart.c      keys from a terminal on the UART
    xc7z020/gp_zynq.c    the board: PS timer and UART, the GPU driver, the VDMA
    sim/gp_sim.c         a PC: the kernel runs natively on every lane, frames become pictures
  doom/                a game
    game.yaml            its manifest
    port/                its code
software/programs/<kernel>/   the game's GPU side, built like every other program
```

## Commands

`<game>` is a directory name, such as `doom`.

| Command | What it does |
| --- | --- |
| `gpgpu software games:<game>:fetch` | Fetch the upstream source at the commit the manifest pins, into the build tree |
| `gpgpu software games:<game>:sim` | Build the game for this PC and run it, writing frames as pictures |
| `gpgpu software games:<game>:verify` | Run the kernel's RISC-V image on the GPGPU model against runs captured from the simulation |
| `gpgpu software games:<game>:all` | Everything that needs no board tools: kernel image and simulation |
| `gpgpu vitis build:games:<game>` | Build the game's host application, `<game>_host.elf` |
| `gpgpu fpga games:<game>:deploy` | Upload bitstream, PS init script and the game's ELF, then start it on the board |
| `gpgpu software games:<game>:clean` | Remove everything built or fetched for the game |

Each command runs what it needs first. `verify` needs `gpgpu rtl constants` once, and the `fpga`
commands need the builds of `vivado` and `vitis`; the CLI names the command to run when one is
missing. The hardware must be built from the same RTL as the game: `GMEM_SIZE` in
`hardware/rtl/gpgpu/packages/gpu_pkg.sv` is 64 MiB for games, so a bitstream from before that
change must be rebuilt.

A game is one host application, started in place of the monitor. To get the monitor back, run
`gpgpu fpga deploy`.

## Configuration

All under `software.games` in `config/profiles/default.yaml`; set machine-specific values in
`config/local.yaml` or with `--set`.

| Option | Meaning |
| --- | --- |
| `platform.output.width`, `.height` | Size of the picture on the 1280x720 display, centred. A smaller picture is drawn faster |
| `platform.input.hold_ms` | How long a key of a UART terminal counts as held |
| `platform.stats_seconds` | Seconds between frame-rate reports on the UART; 0 for none |
| `platform.memory.heap_mb`, `.stack_kb` | The board build's C heap and stack |
| `platform.simulation.frames`, `.dump_every`, `.arguments` | What `games:<game>:sim` runs |
| `settings.<game>.assets.<name>` | Path of a data file linked into the game. Not committed |
| `settings.<game>.args` | Arguments added to the game's own |
| `settings.<game>.defines` | C definitions for the game's build |

```bash
./gpgpu --set software.games.settings.doom.assets.wad=~/doom1.wad software games:doom:sim
./gpgpu --set 'software.games.settings.doom.args=["-warp","1","3"]' vitis build:games:doom
```

## Memory

GMEM is the part of DDR the GPU reads and writes. The ARM sees it at the same addresses, so a
pointer into it is the address the kernel uses (`gp_gpu_address`). Whatever a kernel reads must be
allocated there with `gp_gmem_alloc`: a game's data files, textures and drawing commands.

The GPU reaches DDR around the ARM's caches. Before a kernel reads what the game wrote, and before
the game reads what a kernel wrote, the game calls `gp_gmem_sync` on that memory. In the simulation
it does nothing, so a missing call shows only on the board, as stale pixels.

## Input

A game reads key events with `gp_input_poll` and never knows the device. Today there is one
device, `gp_input_uart.c`: a terminal on the UART. A terminal reports no key release, so a key
counts as held for `hold_ms` after its last byte, and only the last key pressed repeats. That
file's header describes the consequences.

To add a keyboard: write a file that defines a `gp_input_source_t` with real press and release
events, declare it in `gp.h` and add it to the list in `gp_input.c`. No game changes.

## The simulation

`<game>_sim` is the game's own code, compiled for the PC, with `platform/sim` under it. GMEM and
the framebuffers are mapped at their board addresses, and the kernel is the native build of the
same source the GPU runs. Time is virtual, so a run draws the same frames every time.

```bash
build/software/games/doom/sim/doom_sim --frames 600 --dump frames --dump-every 100
build/software/games/doom/sim/doom_sim --frames 900 --checksums --keys '40:\e,60:\r' -- -warp 1 1
```

`--keys FRAME:TEXT,...` feeds console bytes from a frame on, through the same decoder the board
uses. `--checksums` prints one line per frame, so two runs can be compared with `diff`.
`--capture N DIR` saves the N-th run of the kernel for `tools/tests/kernel_replay.py`.

The simulation shows that the game and the kernel's logic are right. It runs the lanes one after
the other, so it cannot show that every lane takes every branch the same way, which the GPU
requires. `games:<game>:verify` checks that: it replays captured runs with the kernel's RISC-V
image on the model the RTL tests use, and fails on a divergent branch, a memory fault, two lanes
storing different values to one byte, or a result that differs from the native build's.

## Adding a game

1. Write its kernel in `software/programs/<kernel>/<kernel>.c`. For the native build, define
   `void gpgpu_kernel_run(const uint32_t *args)`, which runs the kernel on every lane (see
   `software/programs/doom/doom.c`). A game that draws its own indexed picture on the ARM needs
   no kernel of its own: `blit` scales such a picture to the display.
2. Create `software/games/<game>/` with its code and a `game.yaml`:

   | Key | Meaning |
   | --- | --- |
   | `description` | One line |
   | `kernel` | The program of `software/programs` that is its GPU side |
   | `upstream` | Optional: `url`, `commit`, `directory` and the `sources` to compile from it, unchanged |
   | `sources`, `include` | Its own C files and include directories |
   | `defines` | C definitions |
   | `wrap` | Functions of the upstream source whose calls go to `__wrap_<name>` in the game's code |
   | `assets` | Data files linked into the game, each with a `description` shown when its path is not set |
   | `arguments` | The game's arguments; `{name}` is the file name of asset `name` |
   | `verify.runs` | Runs of the kernel in the simulation that `verify` replays |

3. In its code, define `const gp_game_t gp_game = { "name", init, tick };` and use only `gp.h`.
4. Add `software.games.settings.<game>` to `config/profiles/default.yaml`.

The commands above then exist for it.
