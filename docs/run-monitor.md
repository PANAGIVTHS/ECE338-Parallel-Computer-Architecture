# GPGPU Build Monitor

`./gpgpu <category> <task>` automatically shows a live build monitor in an interactive
terminal. It uses the same task graph and logging infrastructure as plain runs;
it does not change dependency ordering, rebuild decisions, or task commands.

```bash
./gpgpu vivado system:build
```

The display contains:

- The requested task and overall running/success/failure/interruption status.
- A progress bar counting completed or up-to-date stages out of the planned
  actionable stages. **This is stage completion, not an estimate of time
  remaining.** A long synthesis stage has the same weight as a short setup stage.
- Ordered stages: completed, running, pending, failed, or already up to date.
- Final stage durations and an updating elapsed time for the running stage.
- A bounded live-log view of the active stage, or the last available stage log
  when the run finishes. The complete logs remain on disk.

The monitor reads the invocation's exact
`logs/runs/<run-id>/run.json`, plus the stage log referenced there. It does not
follow `logs/latest`, which could refer to an older or different invocation.
Stage state is recorded before execution and after completion; the running
stage's elapsed time is calculated from its recorded `started_at` timestamp.
Metadata updates use atomic replacement, and a transient read failure retains
the previous valid snapshot.

## Plain logs and automation

Pipes, redirected output, and non-interactive runs automatically retain the
streaming plain-log format without an animated dashboard. To select that format
explicitly even in an interactive terminal:

```bash
./gpgpu vivado system:build --plain
```

To save a combined console transcript, for example:

```bash
./gpgpu vivado system:build --plain 2>&1 | tee build-console.log
```

Both display modes write the full Python and subprocess stdout/stderr into the
per-stage log files. Monitor redraws are never written into those files. Task
failures keep their nonzero CLI exit status and error details; terminal state
and output capture are restored when execution ends, including interruption.

## Run files

Each invocation creates a directory under `logs/runs/` containing `run.json`
and the log files of stages actually executed. Pending and up-to-date stages
need not have a new log file. `logs/latest` points to the finished run, and
`logs/last-failed` points to the most recent failed run.

The metadata includes the requested task, run timestamps, overall exit code,
Git metadata, and the planned stages with their statuses, log references,
execution timestamps, durations, and failure details when applicable.
