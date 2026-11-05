## Vitis Setup

1) In vivado, go to File > Export > Export Hardware, select include bitstream, but not binary, name it, for example, `gpgpu_platform.xsa`.

2) Open Vitis Tools > Launch Vitis IDE

3) Create Platform: File > New Component > Platform, select the `gpgpu_platform.xsa` file vivado generated.

4) Create ARM application: New Component > Application, name it, for example, `gpgpu_host`, select Platform > `gpgpu_platform`, in the Source Files page select add the sources and select the repo's `software/host/xc7z020/` directory.

5) Select VITIS COMPONENTS > `gpgpu_platform`, FLOW > select `gpgpu_platform` > Build.

6) Select VITIS COMPONENTS > `gpgpu_host`, FLOW > select `gpgpu_host` > Build.

Or, using the cli:

The CLI recreates the repository's portable Vitis default project from the
Vivado XSA and enforces platform-before-host build ordering:

```bash
./gpgpu run vitis:project
./gpgpu run vitis:build:all
```

The editable workspace is `build/software/vitis`. Interactive CLI builds show a
[JSON-backed build monitor](run-monitor.md) with stage progress, durations, and
live logs; use `./gpgpu run vitis:build:all --plain` for streaming plain output.
Open the workspace directory in Vitis
to change the `gpgpu_platform` or `gpgpu_host` components. After saving and
closing Vitis, explicitly synchronize those changes back to the committed
portable default:

```bash
./gpgpu run vitis:export
```

The expected programming artifacts are:

```text
build/software/vitis/gpgpu_platform/export/gpgpu_platform/hw/sdt/ps7_init.tcl
build/software/vitis/gpgpu_host/build/gpgpu_host.elf
```

The `.bit` is the Vivado-published artifact, not a standalone file under the
Vitis platform export's `hw/sdt` directory.

## Upload to the board-connected machine

After building, transfer the three artifacts with:

```bash
./gpgpu run fpga:upload
```

The upload preserves the remote filenames `gpgpu_platform.bit`, `ps7_init.tcl`,
and `gpgpu_host.elf` used by the manual programming workflow. It does not rebuild
or program the board. See [FPGA CLI flow](fpga-cli.md) for SSH configuration,
prerequisites, and the local-to-remote artifact mapping.

## Program through the FPGA Agent

After uploading the artifacts, program the board with:

```bash
./gpgpu run fpga:program
```

To upload the existing local artifacts and then run the same programming flow
with one command instead:

```bash
./gpgpu run fpga:deploy
```

Deploy orders upload before the entire preflight/reset/mode/program sequence.
Missing local files fail before any transfer; a transfer failure prevents all
board operations. It never invokes a vendor build, and resends the artifacts
on every invocation. `fpga:program` remains program-only for already uploaded
files. Upload and programming stages have separate logs and monitor status.

This first validates all programming settings and checks the uploaded bitstream,
`ps7_init.tcl`, and host ELF with read-only `test -f` in the VM upload directory.
If any is missing or is not a file, it fails before reset, mode, or programming.
The logged order is `fpga:preflight` → `fpga:program:reset` →
`fpga:mode:project` → `fpga:program`. After preflight it resets while preserving
the current mode, switches to PROJECT, programs PL, then initializes and starts
PS with the host ELF. It never builds or uploads automatically. Standalone
`fpga:reset`, `fpga:mode:project`, and `fpga:mode:demo` remain independent of
uploaded files; mode commands do not reset. Configure the FPGA device and any
Agent-visible directory override as described in [FPGA CLI flow](fpga-cli.md).
SSH opens the board-connected shell; interactive Bash loads its shortcuts from
`~/.bashrc`. Preflight uses no board helper. Each mutating session selects the
device with `fuse`; the flow uses `fr`, `fm project`, `fpl <bitstream>`, and
`fps <ps7_init.tcl> <host.elf>`. Socket/container access is handled by the
installed helpers, not by this CLI. VM file checks do not prove Agent/container
mount visibility; checked helper responses remain necessary for mapping/API
errors.

See [Vitis CLI flow](vitis-cli.md) for configuration, individual build stages,
and export portability guarantees.
