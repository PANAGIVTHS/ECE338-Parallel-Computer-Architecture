#!/usr/bin/env bash
# Interactive nbody FPGA demo entrypoint.  Kept separate from programs/run.sh so
# the normal program build/run workflow stays clean.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROGRAMS_DIR="$REPO_ROOT/programs"
PROGRAM="nbody"
NBODY_DIR="$PROGRAMS_DIR/$PROGRAM"

PORT=""
BAUD=115200
STEPS_PER_FRAME=1
FPS=12
DATASET="default"
HTTP_HOST="0.0.0.0"
HTTP_PORT=8765
FAKE=0
SKIP_LOAD_IMEM=0
NO_BROWSER=0
VERBOSE=0
BUILD=1

usage() {
    cat <<EOF
Usage:
  $0 --port PORT [options]        # Run interactive demo against FPGA over UART
  $0 --fake [options]             # Run interactive demo with software backend

Options:
  --program NAME                  Demo program: nbody or nbody-3d (default: nbody)
  --port PORT                     UART serial port, e.g. /dev/ttyUSB1 or /dev/ttyACM0
  --baud BAUD                     UART baud rate (default: 115200)
  --steps N, --steps-per-frame N  Simulation steps per displayed frame (default: 1)
  --fps FPS                       Target play-mode frame launches per second (default: 12)
  --dataset NAME_OR_PATH          nbody-3d fake backend dataset (default: default)
  --fake                          Use deterministic software backend, no board needed
  --skip-load-imem                Reuse already-loaded instruction memory in FPGA mode
  --no-build                      Do not build nbody before starting the demo
  --http-host HOST                UI bind host (default: 0.0.0.0)
  --http-port PORT                UI bind port (default: 8765)
  --no-browser                    Do not auto-open browser
  --verbose                       Print UART transfer details
  -h, --help                      Show this help

Examples:
  $0 --fake --steps 4 --no-browser
  $0 --program nbody-3d --fake --steps 4 --no-browser
  $0 --program nbody-3d --fake --dataset rings --no-browser
  $0 --port /dev/ttyUSB1 --steps 1
  $0 --port /dev/ttyACM0 --baud 115200 --steps-per-frame 8 --http-port 8777
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --program)
            PROGRAM="${2:?Missing value for --program}"
            shift 2
            ;;
        --port)
            PORT="${2:?Missing value for --port}"
            shift 2
            ;;
        --baud)
            BAUD="${2:?Missing value for --baud}"
            shift 2
            ;;
        --steps|--steps-per-frame)
            STEPS_PER_FRAME="${2:?Missing value for $1}"
            shift 2
            ;;
        --fps)
            FPS="${2:?Missing value for --fps}"
            shift 2
            ;;
        --dataset)
            DATASET="${2:?Missing value for --dataset}"
            shift 2
            ;;
        --fake)
            FAKE=1
            shift
            ;;
        --skip-load-imem)
            SKIP_LOAD_IMEM=1
            shift
            ;;
        --no-build)
            BUILD=0
            shift
            ;;
        --http-host)
            HTTP_HOST="${2:?Missing value for --http-host}"
            shift 2
            ;;
        --http-port)
            HTTP_PORT="${2:?Missing value for --http-port}"
            shift 2
            ;;
        --no-browser)
            NO_BROWSER=1
            shift
            ;;
        --verbose)
            VERBOSE=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo
            usage
            exit 1
            ;;
    esac
done

if [[ "$PROGRAM" != "nbody" && "$PROGRAM" != "nbody-3d" ]]; then
    echo "--program must be either nbody or nbody-3d"
    exit 1
fi
NBODY_DIR="$PROGRAMS_DIR/$PROGRAM"
SCRIPT="interactive.py"
if [[ "$PROGRAM" == "nbody-3d" ]]; then
    SCRIPT="interactive_3d.py"
fi

if [[ "$FAKE" -eq 0 && -z "$PORT" ]]; then
    echo "FPGA mode requires --port PORT. Use --fake for local UI testing."
    exit 1
fi

if [[ "$BUILD" -eq 1 ]]; then
    if [[ "$FAKE" -eq 1 ]]; then
        make -C "$PROGRAMS_DIR" PROG="$PROGRAM" x86
    else
        make -C "$PROGRAMS_DIR" PROG="$PROGRAM" riscv
        make -C "$PROGRAMS_DIR" PROG="$PROGRAM" "$PROGRAM/${PROGRAM}_instructions.mem"
    fi
fi

ARGS=(
    --steps-per-frame "$STEPS_PER_FRAME"
    --fps "$FPS"
    --http-host "$HTTP_HOST"
    --http-port "$HTTP_PORT"
)

if [[ "$FAKE" -eq 1 ]]; then
    ARGS+=(--fake)
else
    ARGS+=(--port "$PORT" --baud "$BAUD" --imem "$NBODY_DIR/${PROGRAM}_instructions.mem")
fi
if [[ "$SKIP_LOAD_IMEM" -eq 1 ]]; then
    ARGS+=(--skip-load-imem)
fi
if [[ "$NO_BROWSER" -eq 1 ]]; then
    ARGS+=(--no-browser)
fi
if [[ "$PROGRAM" == "nbody-3d" ]]; then
    ARGS+=(--dataset "$DATASET")
fi
if [[ "$VERBOSE" -eq 1 ]]; then
    ARGS+=(--verbose)
fi

echo "Starting interactive nbody demo..."
echo "  UI      : http://$HTTP_HOST:$HTTP_PORT/"
echo "  Program : $PROGRAM"
echo "  Backend : $([[ "$FAKE" -eq 1 ]] && echo fake || echo fpga-uart)"
echo "  Steps/frame: $STEPS_PER_FRAME"
python3 "$SCRIPT_DIR/$SCRIPT" "${ARGS[@]}"
