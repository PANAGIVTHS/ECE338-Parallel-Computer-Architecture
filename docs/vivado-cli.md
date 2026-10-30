# Vivado 2025.2 packaged-IP and Zynq CLI flow

This flow references production RTL under `hardware/rtl/gpgpu/` and board
constraints under `hardware/constraints/smart_zynq.xdc`. No ZIP, saved project,
reference IP repository or prebuilt XSA is a clean-build prerequisite.

## Public stages

```text
vivado:ip:create
  -> vivado:ip:build
  -> vivado:system:create
  -> vivado:system:build
  -> vitis:project -> vitis:build:platform -> vitis:build:host -> vitis:build:all
```

- **ip:create** recreates the managed `gpgpu_ip_dev` project with top
  `gpgpu_axi`. It does not package or synthesize a system. Portable registration
  was reconstructed from the exported IP-development project: production-only
  manifest, SystemVerilog headers, interface ordering and explicit initialization.
- **ip:build** packages and validates `user.org:user:gpgpu_axi:1.0` into a
  self-contained repository. It never builds a standalone bitstream. Publication
  occurs only after Tcl integrity checks and Python file/interface validation.
- **system:create** registers that repository before catalog/BD creation,
  creates or reuses `gpgpu_system/design_1`, applies config-owned parameters,
  validates, generates products and registers `design_1_wrapper`.
- **system:build** executes separately cached synthesis, implementation,
  bitstream and fixed, bitstream-inclusive XSA export. Internal staged tasks
  retain checkpoints, jobs and stage diagnostics; a failed bitstream retry does
  not delete routed state. Required OOC IP synthesis belongs here.
  `hardware.vivado.post_route_phys_opt.{enabled,directive}` (passed as
  `-post-route-phys-opt` / `-post-route-phys-opt-directive`) set `impl_1`'s
  post-route `phys_opt_design` step and its `-directive` on every
  implementation run. The run is launched without `-to_step` (which has no name
  for that step), so it executes every enabled step before `write_bitstream`;
  bitstream and XSA use its result.

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
    fabric_clock_mhz: 35
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
`tools/hardware/vivado/ip/empty.mem`, provides explicit 2048-word zero
initialization for IMEM/DMEM; its file name must match the RTL's default
`$readmemh` name. Project and package copy it beside the flattened
production files; their stage cwd is owned, never a random repository cwd.
Board XDC is excluded from the reusable IP.

## System contract

The saved system BD, not its inconsistent neighboring Tcl export, supplied:
DDR **16-bit MT41K256M16 RE-125**, UART0 **EMIO**. The fabric clock FCLK0
(GPGPU, SmartConnect and reset) is configuration-owned:
`hardware.vivado.fabric_clock_mhz` (default **35 MHz**) is passed as
`-fclk0-mhz`, used when bootstrapping a new BD and re-applied to a saved BD on
every `vivado:system:create`, like the core count and AXI aperture. It is the
requested `PCW_FPGA0_PERIPHERAL_FREQMHZ`; the PS picks the nearest achievable
frequency from its dividers.
The system connects PS GP0 -> SmartConnect -> `gpgpu_axi_0/s00_axi`, with
clock/reset distribution, DDR/FIXED_IO external ports and UART/LED ports.
`irq` connects through width handling to `IRQ_F2P[0]` (GIC ID 61), matching
the IRQ-enabled driver; polling is not silently enabled.

`smart_zynq.xdc` owns UART TX/RX L17/M17 and idle/running P20/P21, all
LVCMOS33. DRC severity is not relaxed. The system consumes the packaged IP,
not an additional raw copy of GPGPU RTL.

## Protected references and GUI state

The pre-existing `GPU`, `gpgpu_axi_v1_0_project`, `gpgpu_ip_dev`,
`gpgpu_system` and `ip_repo` reference directories are **not automatically
adopted**. A nonempty output directory without the matching managed marker is
rejected before mutation. Use a new, disposable build root:

```bash
./gpgpu --set paths.build.root=build-axi-2025-2 run vivado:ip:create
./gpgpu --set paths.build.root=build-axi-2025-2 run vivado:ip:build
./gpgpu --set paths.build.root=build-axi-2025-2 run vivado:system:create
./gpgpu --set paths.build.root=build-axi-2025-2 run vivado:system:build
./gpgpu --set paths.build.root=build-axi-2025-2 run vitis:build:all
```

Each later command resolves its prerequisites. No board upload/programming is
performed. Close the GUI before running automation.

Managed IP recreation retains the previous complete project in a sibling
`.snapshots/` directory; previous published repositories are also retained.
A valid saved managed system BD is snapshot before refresh and is opened, not
recreated. Incompatible/renamed/GPIO BDs are rejected. Core/address settings
remain config-owned. Builds never automatically export references or overwrite
tracked BD templates; the explicit raw export helper is guarded and is not a
build dependency or automatic GUI-to-source synchronization feature.

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

Tests using Tcl recorders/fake vendor processes validate contracts and
orchestration, **not synthesis, implementation, SDK compatibility or hardware
operation**. A real 2025.2 run remains necessary before claiming those results.
