#!/usr/bin/env bash
# Repository-level entry point for program builds, native runs, visualization,
# and FPGA/UART execution.  The implementation lives in programs/run.sh so the
# existing per-program build paths remain unchanged.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/programs/run.sh" "$@"
