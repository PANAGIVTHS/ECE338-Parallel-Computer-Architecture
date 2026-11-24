# Building the host

`./gpgpu vitis` builds the software platform from the current hardware platform
(XSA), and the host program on top of it, with Vitis 2025.2. The committed
`default-project.zip` only supplies the settings of the application.

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
`config/local.yaml`. No SDK is downloaded by this flow. Every task that runs
Vitis first checks that `vitis --version` reports `hardware.vitis.version`, and
stops if it does not, as the Vivado stages do. The commands, with a build root of
their own:

```bash
./gpgpu --set paths.build.root=build-new vivado system:build
./gpgpu --set paths.build.root=build-new vitis project
./gpgpu --set paths.build.root=build-new vitis build:platform
./gpgpu --set paths.build.root=build-new vitis build:host
./gpgpu --set paths.build.root=build-new vitis build:all --plain
```

## What each stage owns

- **project:** generate the editable platform via `create_platform_component`
  from the current XSA, including hardware-derived inputs. On an XSA change,
  preserve the previous component as a backup and regenerate the platform.
- **build:platform:** build and verify the exported XSA, XPFM and PS init Tcl.
  FSBL/boot BSP generation remains enabled through SDK defaults.
- **build:host:** create the application only after the platform exists, using
  `create_app_component` with the exported XPFM and standalone domain.
  Update the SDK-generated **actual `UserConfig.cmake`** source list and include
  paths to the configured driver/main/headers. The configured AXI base is passed
  as `GPGPU_BASEADDR`. The driver does not compile without it.
- **build:all:** the aggregate depends on the host, thus the platform-before-host
  graph.

Existing app-owned files/settings are preserved across hardware regeneration;
previous generated components are backed up. Normal builds do not rewrite
tracked templates or the ZIP. Source/header/settings/platform changes invalidate
host outputs; unchanged builds skip completed stages.

The build also restores missing `lib/` output directories of the BSP, and recovers
the vendor's `xilrsa/src/librsa.a` from the active SDK. Missing or ambiguous SDK
inputs fail explicitly.

## Outputs, logs and export

```text
<build-root>/software/vitis/gpgpu_platform/export/gpgpu_platform/hw/<xsa_name>.xsa
<build-root>/software/vitis/gpgpu_platform/export/gpgpu_platform/hw/sdt/ps7_init.tcl
<build-root>/software/vitis/gpgpu_platform/export/gpgpu_platform/gpgpu_platform.xpfm
<build-root>/software/vitis/gpgpu_host/build/gpgpu_host.elf
```

The programming bitstream stays at
`<build-root>/hardware/bitstream/design_1_wrapper.bit`. The board needs it, Vitis's
`ps7_init.tcl` and the host ELF. Building does **not** upload or operate the board.

The [run monitor](run-monitor.md) records stage status and persistent logs;
`--plain` streams output without the interactive dashboard. Nonzero vendor or
missing-output failures propagate to the CLI.

Save/close the GUI before explicit synchronization:

```bash
./gpgpu --set paths.build.root=build-new vitis export
```

Export remains outside the build graph. It atomically replaces the portable
archive, excludes generated binaries/hardware products and normalizes paths.
Review that intentional source change before committing. Builds consume only
portable application settings from the archive; stale platform/BSP/SDT is never
used as a substitute for regeneration from the new XSA.

See [Building the hardware](vivado.md) for the stages before this one.
