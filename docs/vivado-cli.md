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

The tracked `production_sources.tcl` lists only production root/control/memory/
sp/interfaces files, with `constants.svh` and `MemoryInterface.sv` first.
`tools/hardware/vivado/ip/empty.mem` provides explicit 2048-word zero
initialization for IMEM/DMEM. Project and package copy it beside the flattened
production files; their stage cwd is owned, never a random repository cwd.
Board XDC is excluded from the reusable IP.

## System contract

The saved system BD, not its inconsistent neighboring Tcl export, supplied:
FCLK0 **35 MHz**, DDR **16-bit MT41K256M16 RE-125**, UART0 **EMIO**.
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
stage. Use `--plain` for plain live output. The FPGA artifact contract is unchanged:
published bitstream, Vitis `ps7_init.tcl`, and host ELF. No reference artifact is
accepted as evidence of a newly completed vendor build.

Tests using Tcl recorders/fake vendor processes validate contracts and
orchestration, **not synthesis, implementation, SDK compatibility or hardware
operation**. A real 2025.2 run remains necessary before claiming those results.
