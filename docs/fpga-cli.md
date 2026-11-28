# FPGA CLI flow

The `fpga:*` namespace contains board-operation tasks, separate from the Vivado
and Vitis build stages.

## Run a program

A program (`software/programs/<program>/` with `<program>.c` and `host.c`,
docs/runtime-spec.md) is an A9 executable that the monitor loads and runs:

```bash
./gpgpu fpga programs:memspaces:run
./gpgpu --set 'software.runtime.arguments=["8"]' fpga programs:memspaces:run
```

The task builds `<program>_a9.elf` (`software programs:<program>:host`),
copies it to `hardware.fpga.upload.directory` and, on the board's machine,
sends its loadable segments to the monitor with `load` (each with its CRC-32),
then starts it with `run <program> <arguments>`. The program's console output
is shown as it arrives; the task ends when the program returns to the monitor
(`RUN_RETURN <status>`), with the program's status. A program that hangs the
A9 never returns: the client gives up after 600 s, and the board needs
`./gpgpu fpga deploy`. Programs load one after another without a reset.

The CLI streams the repository's shared `tools/board/xc7z020/uart.py` and a small
driver to the board machine's Python over SSH stdin; it does not install
files or packages remotely. File names use the SSH upload namespace
(`/home/njason/upload`), not the Agent namespace (`/app`).

Default UART configuration:

```yaml
hardware:
  fpga:
    uart:
      port: /dev/ttyUSB0
      baud: 115200
      sudo: true
      python: python3
```

Override these in `config/local.yaml` or with global `--set` options. For example,
if the SSH user already has serial access:

```bash
./gpgpu --set hardware.fpga.uart.sudo=false fpga programs:simple:run
```

The board machine's interpreter must have `pyserial` installed. With
`sudo: true`, commands use `sudo -n`; password prompts are never handled. Close
minicom and coordinate UART ownership with the Agent or other serial clients
first. The driver uses a nonblocking per-port advisory lock and pyserial
exclusive opening, but unrelated clients that do not cooperate with those
locks can still interfere.

The board must run a bitstream and a monitor built from the same branch. A
monitor without the loader answers `load` with an unknown command. These tasks
do not reset the board, change mode, or depend on `fpga:program`/`fpga:deploy`.

## A program in place of the monitor

```bash
./gpgpu --set 'software.runtime.arguments=["0"]' software programs:ripple:boot
./gpgpu --set software.host.boot_program=ripple fpga deploy
```

With `software.host.boot_program` set, `fpga:upload` sends that program's
`<program>_boot_a9.elf` under the monitor's remote name, so `fpga:program`
starts it instead of the monitor. Its arguments are `software.runtime.arguments`
at the time of the `:boot` build. It has no monitor to return to and stops when
`gpgpu_main` returns; `./gpgpu fpga deploy` with `boot_program: null` puts the
monitor back.

## Program only or upload and program

```bash
./gpgpu fpga program  # use the files already uploaded to the board
./gpgpu fpga deploy   # upload existing local artifacts, then program
```

`fpga:program` preserves its program-only behavior: no local build or upload.
`fpga:deploy` explicitly runs `fpga:upload` first, then the complete existing
program sequence: preflight → reset → PROJECT mode → PL → PS/host ELF.
It does **not** invoke Vivado or Vitis. Build the local artifacts beforehand.
Both flows run again on every invocation; deploy always resends all three files.

Deploy checks all local upload inputs before the first transfer. If any is
missing, no transfer or board operation is attempted. An SCP failure stops
before remote preflight/reset/mode/programming. After successful upload, a
failed remote preflight likewise prevents all board operations. Successful
upload does not bypass programming validation or helper-response checks.
Upload and each programming stage retain their own logs and monitor status.

## Upload programming artifacts

From the repository root:

```bash
./gpgpu vivado system:build
./gpgpu vitis build:all
./gpgpu fpga upload
```

`fpga:upload` transfers the existing programming artifacts via SCP to the
board-connected machine. It does **not** program the FPGA, initialize the PS,
execute the host ELF, or trigger a build. Build first; the upload stops before
any transfer if a file is missing, and warns if a build is out of date. Every explicit invocation
uploads again, even when the files are unchanged.

With the default configuration, the mapping is:

| Local path, relative to the repository | Remote filename |
| --- | --- |
| `build/hardware/bitstream/gpgpu_block_design_wrapper.bit` | `gpgpu_platform.bit` |
| `build/software/vitis/gpgpu_platform/export/gpgpu_platform/hw/sdt/ps7_init.tcl` | `ps7_init.tcl` |
| `build/software/vitis/gpgpu_host/build/gpgpu_host.elf` (the monitor), or `build/software/programs/<p>/<p>_boot_a9.elf` with `software.host.boot_program` | `gpgpu_host.elf` |

The default destination is `njason@192.168.1.13:/home/njason/upload/`. Renaming
the bitstream on upload keeps the existing manual programming workflow's
`gpgpu_platform.bit` filename. The bitstream comes from Vivado's published
output; do not use the obsolete Vitis platform export path
`export/gpgpu_platform/hw/sdt/gpgpu_platform.bit`.

## Remote reset, mode, and programming

```bash
./gpgpu fpga reset
./gpgpu fpga mode:project
./gpgpu fpga mode:demo
./gpgpu fpga program
```

Every invocation runs again. SSH to `hardware.fpga.upload.destination`
(default `njason@192.168.1.13`) opens the board-connected shell environment.
The CLI runs its existing shell shortcuts through `bash -ic`, loading
`~/.bashrc` even when it has an interactive-only guard. The CLI does not call
curl, Docker, or a Unix socket directly. `fpga:program` does not build or
transfer files; the explicit `fpga:deploy` flow first uploads through SCP.

Mutating SSH sessions start with `set -e; set -o pipefail` and
`fuse <device> >/dev/null`: device selection is shell-local and cannot be
carried over from a previous session. The read-only preflight session uses
`test -f` without `fuse` or any board helper.

- `fpga:reset` runs `fr`, which reads and preserves the current mode internally.
  The CLI does not fetch or parse API state. It does not require uploaded files.
- The independent mode tasks run `fm project` or `fm demo`, with no reset and
  no artifact checks.
- `fpga:preflight` validates transport, device, all artifact names, and both VM
  upload and Agent programming directories before any mutation. In one read-only
  SSH session it checks **all three** uploaded files with `test -f` under
  `hardware.fpga.upload.directory`, reports every missing/non-file path, and
  fails with status 1. Nonzero SSH/remote errors also fail closed.
- `fpga:program` runs the four always-run logged stages in order:
  `fpga:preflight` → `fpga:program:reset` → `fpga:mode:project` → `fpga:program`.
  The scoped reset depends on preflight and invokes the same `fr` action as the
  independent reset. PROJECT mode is a setup task after the scoped reset.
  If any bitstream, init Tcl, or ELF is missing or is a directory, no `fr`, `fm`,
  `fpl`, or `fps` is attempted. After successful preflight, PL and PS run in
  separate checked SSH sessions under `set -e`, so PS follows only successful
  PL. Avoid placing `fpl` on the left of `&&`: Bash then disables `errexit`
  inside that shell function, which can mask a failed internal command.
  The helpers preserve PROJECT mode; `fps` initializes/resets the processor,
  downloads the ELF, and continues execution.

Programming uses the existing uploaded `<platform_name>.bit`, `ps7_init.tcl`,
and `<host_name>.elf`. By default their programming directory is
`hardware.fpga.upload.directory`. If the Agent sees that directory at a different
path, set `hardware.fpga.agent.directory` to the Agent-visible path. Preflight
still checks the **VM upload directory**, not the container/Agent path: it does
not prove container mount visibility, API availability, or continued file
existence after the check. The API validates its own filesystem when programming.
The CLI also inspects each helper's JSON response and marks the stage failed
with the Agent's error/path even if the helper exits zero. These checks remain
necessary defense for mount mapping/API errors; PS is not invoked after a PL
error. Upload remains available independently: run `fpga:upload` before
`fpga:program`, or use `fpga:deploy` to combine both. No build or upload is
triggered by preflight/program alone.

For the verified board deployment, `/home/njason/upload` in the SSH environment
is mounted as `/app` in the Agent container. Keep `upload.directory` set to
`/home/njason/upload` and `agent.directory` set to `/app`; these settings belong
to different filesystem namespaces and are not interchangeable.

## Configuration

Override the destination in the ignored `config/local.yaml` (merge this with
any existing local settings):

```yaml
hardware:
  fpga:
    upload:
      destination: njason@192.168.1.13
      directory: /home/njason/upload
    agent:
      device: "210299730789"
      directory: /app  # Agent-visible destination of the verified upload mount
tools:
  ssh:
    command: ssh
  scp:
    command: scp
```

`destination` accepts an SSH hostname/alias or `user@host`. The remote directory
is an absolute POSIX path. Hostnames, usernames, and filenames use letters,
digits, underscores, dots, and hyphens; directory paths additionally use `/`.
Whitespace, shell metacharacters, and `..` directory components are rejected.
Use an SSH alias for IPv6 destinations or custom connection settings. SSH
aliases can supply ports and identity files via `~/.ssh/config`, without adding
credentials to this repository. Device identifiers start with a letter,
digit, or underscore. Quote numeric device IDs in YAML: the API device identifier
must be a string. The agent directory follows the same safe absolute
POSIX-path contract; only `agent.directory: null` means fallback. Empty strings,
wrong types, shell characters, and traversal are errors. `tools.ssh.command` and
`tools.scp.command` are single executable names or paths, not command lines with
embedded arguments. Invalid board settings are checked when actions run, so
unrelated task discovery remains available.

For a one-off override, global options go before the category:

```bash
./gpgpu --set hardware.fpga.upload.destination=njason@192.168.1.13 \
  --set hardware.fpga.upload.directory=/home/njason/upload fpga upload
```

Local paths follow `paths.build.root`, `hardware.vivado.top`,
`hardware.vitis.platform_name`, and `hardware.vitis.host_name`. Remote bitstream
and ELF filenames follow the configured platform and host names respectively;
`ps7_init.tcl` retains its name.

## Prerequisites and failures

- The configured SCP executable must be available on the machine running the CLI.
- The remote machine must be reachable over SSH, with working authentication.
- The destination directory must already exist and be writable by the SSH user.
- Manage SSH keys and host verification through OpenSSH; no credentials are stored
  in repository configuration and host-key checking is not disabled.

A missing local artifact fails before transferring any file. A failed SCP
command stops the task with a nonzero status. The three transfers are not
atomic: earlier files may already have been replaced if a later transfer
fails. Neither flow attempts programming after an upload failure. Fix the
issue and rerun `fpga:upload` or `fpga:deploy` to resend all three files.

Upload output and failures use the same per-task logs and `run.json` metadata
as other `./gpgpu` tasks.

Remote board actions additionally require the configured SSH executable and
Bash on the Debian VM, with `fuse`, `fr`, `fm`, `fpl`, and `fps` defined or sourced
by the SSH user's `~/.bashrc`. The existing helpers manage agent container/socket
access; no socket is configured in this CLI. SSH uses `BatchMode=yes` and
`ConnectTimeout=10`; normal host-key checking is unchanged. Establish trusted
host keys and working noninteractive SSH authentication before using these
state-changing commands. Helper argv and the enclosing `bash -ic` argv are
nested using `shlex.join`; subprocess uses argv, never a local shell.

An SSH or helper failure stops the sequence immediately; stdout/stderr remain
in the task log and the transport exit status in run metadata. Missing helpers
fail normally (Bash status 127). All programming path/name and transport
validation occurs in `fpga:preflight`, before reset and PROJECT mode setup.
Missing/non-file VM artifacts fail there too, with all missing paths in the
preflight log and a nonzero status in run metadata. Programming is not
transactional after preflight: a later mount/API/helper failure or a file
removed after the check can leave the board reset, in PROJECT mode, or with
only PL programmed. Fix the issue and explicitly rerun to repeat the complete
sequence.
