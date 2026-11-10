# Vivado 2025.2 packaged-IP and Zynq CLI flow

This flow references production RTL under `hardware/rtl/gpgpu/` and board
constraints under `hardware/constraints/smart_zynq.xdc`. No ZIP, saved project,
reference IP repository or prebuilt XSA is a clean-build prerequisite.

## Public stages

```text
vivado ip:create -> ip:build -> system:create
  -> system:synthesis -> system:implementation -> system:bitstream -> system:build
```

Each command runs whatever before it is stale, and stops there. The Vitis flow only
reads the XSA that `system:build` exports, and never starts Vivado.

- **ip:create** recreates the managed `gpgpu_ip_dev` project with top
  `gpgpu_axi`. It does not package or synthesize a system. Portable registration
  was reconstructed from the exported IP-development project: production-only
  manifest, SystemVerilog headers, interface ordering and explicit initialization.
- **ip:build** packages and validates `user.org:user:gpgpu_axi:1.0` into a
  self-contained repository. It never builds a standalone bitstream. Publication
  occurs only after Tcl integrity checks and Python file/interface validation.
  The same repository also publishes the other IP the block design uses:
  every directory under `hardware.vivado.vendor_ip.root` (`hardware/rtl`)
  except `hardware.vivado.vendor_ip.exclude` (`gpgpu`, the GPGPU's own RTL),
  copied beside the package, e.g. `ip_repo/rgb2dvi/` and the `tmds` interface
  definition in `ip_repo/tmds_v1_0/`. Vivado's IP catalog scans the repository
  recursively. A vendor directory may not reuse a name the package produced
  (`src`, `xgui`); editing, adding or removing one republishes the repository.
- **system:create** registers that repository before catalog/BD creation,
  creates or reuses `gpgpu_system/design_1`, applies config-owned parameters,
  validates, generates products and registers `design_1_wrapper`.
- **system:synthesis**, **system:implementation**, **system:bitstream** and
  **system:build** are separately cached: synthesis, implementation, bitstream,
  and the fixed, bitstream-inclusive XSA export. They retain checkpoints, jobs and
  stage diagnostics; a failed bitstream retry does not delete routed state.
  Required OOC IP synthesis belongs to synthesis.
  `hardware.vivado.post_route_phys_opt.{enabled,directive}` (passed as
  `-post-route-phys-opt` / `-post-route-phys-opt-directive`) set `impl_1`'s
  post-route `phys_opt_design` step and its `-directive` on every
  implementation run. The run is launched without `-to_step` (which has no name
  for that step), so it executes every enabled step before `write_bitstream`;
  bitstream and XSA use its result. The stage ends by printing the timing it
  closed (setup WNS/TNS, hold WHS/THS) from `impl_1`'s last timing summary, and
  a warning when the design misses timing; it still succeeds, so check the line.

The former GPIO/module-reference tasks are not part of this pipeline.

## Prerequisites and configuration

Install licensed Vivado/Vitis **2025.2**, then source their environment or set
`tools.vivado.command` / `tools.vitis.command` in ignored `config/local.yaml`.
The runtime version checks reject a different SDK; discovery does not invoke it.
The generic `./gpgpu doctor` checks configured executable prerequisites.

Defaults in `config/profiles/default.yaml`:

```yaml
architecture:
  num_cores: 24
hardware:
  fpga:
    part: xc7z020clg484-1
  vivado:
    ip_project_name: gpgpu_ip_dev
    project_name: gpgpu_system
    bd_name: design_1
    top: design_1_wrapper
    xsa_name: gpgpu_platform
    version: "2025.2"
    jobs: 6
    fabric_clock_mhz: 42
    post_route_phys_opt:
      enabled: true
      directive: AggressiveExplore
    peripheral:
      base_address: "0x43C00000"
      range: "0x00010000"
```

The current RTL decodes a 64-KiB window while retaining 32-bit AXI address
signals. Packaging therefore declares `s00_axi/reg0` range **65536**, not the
reference package's dependent 4-GiB range. No RTL widths/register semantics
were changed. The range is fixed to this ABI; the base must be a valid aligned
32-bit hexadecimal string. The same base is passed to the host build as
`GPGPU_BASEADDR` (see [Vitis flow](vitis-cli.md)). Core count maps to
`CONFIG.SP_PER_SM` and the IP user-to-HDL/XGUI parameter, never a second setting.

Production sources come from the config, not from a tracked list: the shared
`hardware.sources` description (extensions, header extensions, compile order)
under `paths.rtl.sources.gpgpu`, minus `hardware.vivado.exclude_sources` (bare
directory/file names matched at any depth, or paths relative to the RTL root;
excluded `ordered` entries are dropped). Headers are packaged first as include
headers, then the `ordered` files, then the rest in path order, with the
file declaring the IP top module (`gpgpu_axi`) moved last: with a manual compile
order `ipx::package_project` takes the last file as the top-level file.
`hardware.vivado.memory_init` is staged before all of them. Python writes the
resolved list to `<ip project>/.gpgpu/sources.tsv` (`<kind>\t<path>` lines) and
passes only that file as `-sources-manifest`: long or brace-quoted list
arguments do not survive Vivado's `-tclargs` handling. `production_sources.tcl`
reads and validates it (all files exist, unique file names, headers among the
sources). The default `hardware.vivado.memory_init`,
`tools/gpgpu/adapters/vivado/tcl/ip/empty.mem`, provides explicit 2048-word zero
initialization for IMEM/DMEM; its file name must match the RTL's default
`$readmemh` name. Project and package copy it beside the flattened
production files; their stage cwd is owned, never a random repository cwd.
Board XDC is excluded from the reusable IP.

## System contract

The saved system BD, not its inconsistent neighboring Tcl export, supplied:
DDR **16-bit MT41K256M16 RE-125**, UART0 **EMIO**, SD0 **MIO 40..45** with
card detect on **MIO 47** (the TF card, for SD boot; bank 501 at 3.3 V). The fabric clock FCLK0
(GPGPU, its SmartConnects and reset) is configuration-owned:
`hardware.vivado.fabric_clock_mhz` (default **42 MHz**) is passed as
`-fclk0-mhz`, used when bootstrapping a new BD and re-applied to a saved BD on
every `vivado:system:create`, like the core count and AXI aperture. It is the
requested `PCW_FPGA0_PERIPHERAL_FREQMHZ`; the PS picks the nearest achievable
frequency from its dividers.
The system connects PS GP0 -> `gpgpu_ctrl` (SmartConnect) -> `gpgpu_axi_0/s00_axi`, with
clock/reset distribution, DDR/FIXED_IO external ports and UART/LED ports.
`irq` connects through width handling to `IRQ_F2P[0]` (GIC ID 61), matching
the IRQ-enabled driver; polling is not silently enabled. The GPGPU's DDR master
`m00_axi` reaches `S_AXI_HP0` through `gpgpu_ddr` and the scanout VDMA
reaches `S_AXI_HP2` through `vdma_ddr` (1x1 SmartConnects, which also convert
AXI4 to AXI3), so the two meet only in the DDR controller; both see PS DDR
identity-mapped (0x0000_0000-0x1FFF_FFFF); the DDR controller keeps its
default arbitration. PS GP1 reaches the VDMA registers
at 0x8300_0000. Scanout:
VDMA (32-bit pixels, two frame stores, 16-beat bursts, 4096-pixel line
buffer) -> AXI4-Stream subset converter (4 to
3 bytes, `0x00RRGGBB` to the video order) -> AXI4-Stream video out, timed by a
VTC in its default mode -> `rgb2dvi` (serial clock generated, see below) -> the
`TMDS_0` HDMI port. FCLK0 runs only the GPGPU, GP0 and HP0 (reset `gpu_sys_reset`), so it
can follow the GPGPU's timing. The display has a fixed 100 MHz FCLK1 (GP1,
the VDMA, HP2 and the stream into the video out, faster than the pixel clock;
reset `rst_ps7_0_35M`) and the 74.25 MHz (720p60) pixel clock that `clk_wiz_0`
makes from the board's 50 MHz PL oscillator `clk_50m` (M19, in the HDMI bank;
reset `proc_sys_reset_0`) with a PLL. `rgb2dvi`
makes the 5x 371.25 MHz serial clock itself with an MMCM in the TMDS pins'
clock region (BUFIO for the serial clock, BUFR for the serializers' pixel
clock), so the serializer clocks stay off the global clock network; see
`docs/hdmi-blanking-investigation.md`. No PS clock feeds the HDMI
output; the video out's asynchronous FIFO crosses from FCLK1 to the pixel
clock. All three resets follow
`FCLK_RESET0_N`. A new project starts from `hardware/bd/design_1.tcl`;
`create_system.tcl` refuses a saved design that lacks the GPGPU's host,
interrupt or DDR cells. `smart_zynq.xdc` places the TMDS pairs (TMDS_33).

`smart_zynq.xdc` owns UART TX/RX L17/M17 and idle/running P20/P21, all
LVCMOS33. DRC severity is not relaxed. The system consumes the packaged IP,
not an additional raw copy of GPGPU RTL.

## Protected references and GUI state

The pre-existing `GPU`, `gpgpu_axi_v1_0_project`, `gpgpu_ip_dev`,
`gpgpu_system` and `ip_repo` reference directories are **not automatically
adopted**. A nonempty output directory without the matching managed marker is
rejected before mutation. Use a new, disposable build root:

```bash
./gpgpu --set paths.build.root=build-axi-2025-2 vivado ip:create
./gpgpu --set paths.build.root=build-axi-2025-2 vivado ip:build
./gpgpu --set paths.build.root=build-axi-2025-2 vivado system:create
./gpgpu --set paths.build.root=build-axi-2025-2 vivado system:build
./gpgpu --set paths.build.root=build-axi-2025-2 vitis build:all
```

Each later command in a category resolves its prerequisites there. No board
upload/programming is performed.

Managed IP recreation retains the previous complete project in a sibling
`.snapshots/` directory; previous published repositories are also retained.
A valid saved managed system BD is snapshot before refresh and is opened, not
recreated. Incompatible/renamed/GPIO BDs are rejected. Core/address settings
remain config-owned. Builds never overwrite committed files.

## Editing in the GUI

`gpgpu project` keeps a project and its committed files in sync.

```bash
./gpgpu project open system     # or ip; creates the project first if needed
./gpgpu project status system   # which side changed since the last sync
./gpgpu project pull system     # project -> committed files
./gpgpu project push system     # committed files -> project; the old state is kept as a snapshot
```

| Status | Meaning | A build |
| --- | --- | --- |
| `in sync` | Nothing changed since the last sync | Runs |
| `project ahead` | Edited in the GUI | `system` builds the edit; `ip` refuses, it would ignore it |
| `source ahead` | Committed files changed | `system` refuses, it would ignore them; `ip` recreates the project |
| `diverged` | Both changed | Refuses. `pull` and `push` also refuse without `--force` |
| `untracked` | Made before sync existed. `pull` or `push` starts tracking it | Runs |

**system** maps to `hardware/bd/design_1.tcl`. `pull` brings the saved design up to
date as a build does, so you need not validate it first, and refuses it with Vivado's
reason if it is invalid. It then exports the design with `write_bd_tcl`, rebuilds that
script in a throwaway project and compares the result with `diffbd`. If they differ,
it refuses and leaves the script unchanged.
Settings the configuration owns (cores, aperture, clock) are overwritten on every
build; `status` reports any that differ. See [the block design](../hardware/bd/README.md).

**ip** maps to the RTL under `hardware/rtl/gpgpu/`. The project holds flat copies
in `src/`, and `pull` copies edited ones back.

`status` also detects edits made in the IP Packager, but `pull` refuses them. Their
source of truth is `tools/gpgpu/adapters/vivado/tcl/package_ip.tcl`, because most of
that metadata follows from the RTL, and Vivado cannot turn a packaged IP back into a
script: `write_project_tcl` only recreates the project, `write_ip_tcl` only covers IP
instances, and `ipx::dump_tcl_commands` (undocumented) writes commands that 2025.2
itself rejects. Vivado does journal what you do, so copy your edit's commands from
the project's `vivado.jou` into `package_ip.tcl`.

### Building after an edit

Every stage is its own command, so you can stop where you want, for example with
`./gpgpu vivado system:bitstream`. A build reruns only what your change affects:

| Changed in Vivado | What reruns |
| --- | --- |
| Block design, saved | `system:create` (validates it, applies the configuration, regenerates the wrapper), then synthesis onwards |
| Synthesis settings | Synthesis onwards |
| Implementation settings | Implementation onwards |
| Nothing since a `project pull` | Only `system:create`, in seconds |

Run settings live in the `.xpr`, not in `design_1.tcl`. Builds honour them, but
`pull` does not save them, so a recreated project loses them. If the design changed,
a build reruns synthesis even when you already ran it in the GUI.

You can leave the GUI open while the CLI builds. The build uses what is saved on
disk, and the GUI does not reload: it keeps showing its runs as out of date until
you reopen the project. Do not launch runs from both at once, and close the GUI
before `push`, because its next save would overwrite the pushed design.

### What a stage checks

Freshness includes production sources/headers/init files, Tcl/metadata, tools
and version checks, part/core/address command fingerprints, package contents,
saved BD, XDC and downstream targets. Repackaging refreshes the instantiated IP
catalog/revision even though its VLNV remains unchanged. Unchanged invocations
skip completed stages. IP package failure blocks system and Vitis execution.

## Outputs and logging

```text
<build-root>/hardware/vivado/gpgpu_ip_dev/gpgpu_ip_dev.xpr
<build-root>/hardware/vivado/ip_repo/component.xml
<build-root>/hardware/vivado/ip_repo/.gpgpu-package.json
<build-root>/hardware/vivado/gpgpu_system/gpgpu_system.xpr
<build-root>/hardware/bitstream/design_1_wrapper.bit
<build-root>/hardware/platform/gpgpu_platform.xsa
```

The XSA must include `.bit`, `.hwh`, `ps7_init.tcl` and `ps7_init.c` before the
stage succeeds. Vivado logs/journals/streamed console logs stay in the managed
project's `.gpgpu/logs/`; the existing JSON-backed CLI monitor also records each
stage. Use `--plain` for plain live output. `launch_runs` executes each run in
its own process, so the synthesis, implementation and bitstream stages also copy
their runs' logs and reports (`runme.log`, `.vds`, `.vdi`, `.rpt`) to
`.gpgpu/logs/<stage>/<run>/`: `synth_1` plus every out-of-context IP
synthesis run (`*synth_1`), or `impl_1`. The copy is refreshed on every
execution, also when Vivado fails; reused out-of-context runs keep the logs from
when they ran. The FPGA artifact contract is unchanged:
published bitstream, Vitis `ps7_init.tcl`, and host ELF. No reference artifact is
accepted as evidence of a newly completed vendor build.
