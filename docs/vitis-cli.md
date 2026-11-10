# Vitis 2025.2 CLI flow

The build creates hardware-derived platform/BSP/SDT inputs from the **current
new system XSA**, using Vitis 2025.2 Python APIs. It does not restore the stale
GPIO hardware/BSP from `default-project.zip`. That archive remains an explicit
GUI export/application-settings input, not a hardware bootstrap prerequisite.

## Dependency graph and configuration

```text
vitis project -> build:platform -> build:host -> build:all
```

These commands use the XSA from `./gpgpu vivado system:build` and never start
Vivado. If it is missing they stop and say so; if the hardware is out of date they
warn, and build on the XSA that exists. `build:host` also regenerates the driver's
headers, which takes well under a second.
`hardware.vivado.xsa_name` derives the same validated XSA filename for both
producers and consumers; changing it does not silently select a cached default.
Defaults: SDK 2025.2, `ps7_cortexa9_0`, standalone domain
`standalone_ps7_cortexa9_0`, platform `gpgpu_platform`, host `gpgpu_host`.
Configured host sources are `software/host/xc7z020/gpgpu_driver.c` and `main.c`,
with adjacent headers as real build dependencies.

Provide the licensed SDK environment or set `tools.vitis.command` in ignored
`config/local.yaml`. No SDK is downloaded by this flow. Use a new build root to
avoid pre-existing reference projects:

```bash
./gpgpu --set paths.build.root=build-axi-2025-2 vivado system:build
./gpgpu --set paths.build.root=build-axi-2025-2 vitis project
./gpgpu --set paths.build.root=build-axi-2025-2 vitis build:platform
./gpgpu --set paths.build.root=build-axi-2025-2 vitis build:host
./gpgpu --set paths.build.root=build-axi-2025-2 vitis build:all --plain
```

## What each stage owns

- **project:** generate the editable platform via `create_platform_component`
  from the current XSA, including hardware-derived inputs. On an XSA change,
  preserve the previous component as a backup and regenerate the platform;
  never reuse the archived GPIO SDT/BSP as current hardware.
- **build:platform:** build and verify the exported XSA, XPFM and PS init Tcl.
  FSBL/boot BSP generation remains enabled through SDK defaults.
- **build:host:** create the application only after the platform exists, using
  `create_app_component` with the exported XPFM and standalone domain.
  Update the SDK-generated **actual `UserConfig.cmake`** source list and include
  paths to the configured driver/main/headers. The configured AXI base is passed
  as `GPGPU_BASEADDR`, overriding the driver's fallback consistently with BD.
  No driver/UART/application protocol is redesigned and IRQ operation stays on.
- **build:all:** the aggregate depends on the host, thus the platform-before-host
  graph.

Existing app-owned files/settings are preserved across hardware regeneration;
previous generated components are backed up. Normal builds do not rewrite
tracked templates or the ZIP. Source/header/settings/platform changes invalidate
host outputs; unchanged builds skip completed stages.

The prior BSP fixes remain: restore missing `lib/` output directories from BSP
`CMakeLists.txt` discovery and recover vendor-owned `xilrsa/src/librsa.a` from
the **active SDK**. Do not disable FSBL/RSA or alter `ps7_init.c` to hide failures.
Missing/ambiguous SDK inputs fail explicitly.

## Outputs, logs and export

```text
<build-root>/software/vitis/gpgpu_platform/export/gpgpu_platform/hw/<xsa_name>.xsa
<build-root>/software/vitis/gpgpu_platform/export/gpgpu_platform/hw/sdt/ps7_init.tcl
<build-root>/software/vitis/gpgpu_platform/export/gpgpu_platform/gpgpu_platform.xpfm
<build-root>/software/vitis/gpgpu_host/build/gpgpu_host.elf
```

The programming bitstream stays at
`<build-root>/hardware/bitstream/design_1_wrapper.bit`. Together with Vitis
`ps7_init.tcl` and host ELF it preserves the FPGA upload/program artifact
contract. Building does **not** upload or operate the board.

The existing JSON-backed run monitor records stage status and persistent logs;
`--plain` streams output without the interactive dashboard. Nonzero vendor or
missing-output failures propagate to the CLI.

Save/close the GUI before explicit synchronization:

```bash
./gpgpu --set paths.build.root=build-axi-2025-2 vitis export
```

Export remains outside the build graph. It atomically replaces the portable
archive, excludes generated binaries/hardware products and normalizes paths.
Review that intentional source change before committing. Builds consume only
portable application settings from the archive; stale platform/BSP/SDT is never
used as a substitute for regeneration from the new XSA.

See [Vivado flow](vivado-cli.md) for packaging/system safety and reference state.
