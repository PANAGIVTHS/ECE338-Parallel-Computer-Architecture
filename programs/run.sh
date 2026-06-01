#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROGRAMS_DIR="$SCRIPT_DIR"

mapfile -t PROGRAMS < <(
    find "$PROGRAMS_DIR" -mindepth 1 -maxdepth 1 -type d ! -name '__pycache__' \
    | xargs -r -n1 basename \
    | sort
)

if [[ ${#PROGRAMS[@]} -eq 0 ]]; then
    echo "No program directories found."
    exit 1
fi

SELECTED=""
TARGET="all"

RUN_X86=""
RUN_FPGA=0
VISUALIZE=""

FPGA_PORT=""
FPGA_BAUD=115200
FPGA_KERNEL_CALLS=""
FPGA_SKIP_LOAD_IMEM=0
FPGA_VERBOSE=0
FPGA_EXTRA_ARGS=()

RUN_FLAG_PROVIDED=0
VISUALIZE_FLAG_PROVIDED=0

usage() {
    cat <<EOF
Usage:
  $0
  $0 -p PROGRAM
  $0 --program NAME

Optional build targets:
  all     (default)
  riscv
  x86
  clean

Generic run options:
  -x, --x86, --run-x86            Run the compiled native x86 binary
  --no-x86                        Do not run the native x86 binary
  -v, --visualize                 Run visualize.py if the program has one
  --no-visualize                  Do not run visualization
  --fpga                          Run the program on FPGA through UART
  --port PORT                     UART serial port for --fpga, e.g. /dev/ttyUSB1
  --baud BAUD                     UART baud rate for --fpga (default: 115200)
  --kernel-calls N                Number of FPGA kernel launches
  --skip-load-imem                Reuse already-loaded IMEM for --fpga
  --fpga-verbose                  Print verbose FPGA/UART framework logs

Adapter-specific FPGA options:
  Put program-specific options after -- and they will be forwarded to fpga_run.py
  and then to programs/<program>/fpga.py.

Examples:
  $0 -p nbody riscv --fpga --port /dev/ttyUSB1 --kernel-calls 1000 --visualize -- --steps 1
  $0 -p mandelbrot riscv --fpga --port /dev/ttyUSB1 --kernel-calls 10240 --visualize -- --frames 160
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--program)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for $1"
                exit 1
            fi
            SELECTED="$2"
            shift 2
            ;;
        all|riscv|x86|clean)
            TARGET="$1"
            shift
            ;;
        -x|--x86|--run-x86)
            RUN_X86=1
            RUN_FLAG_PROVIDED=1
            shift
            ;;
        --no-x86)
            RUN_X86=0
            RUN_FLAG_PROVIDED=1
            shift
            ;;
        -v|--visualize)
            VISUALIZE=1
            VISUALIZE_FLAG_PROVIDED=1
            shift
            ;;
        --no-visualize)
            VISUALIZE=0
            VISUALIZE_FLAG_PROVIDED=1
            shift
            ;;
        --fpga)
            RUN_FPGA=1
            shift
            ;;
        --port)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for $1"
                exit 1
            fi
            FPGA_PORT="$2"
            shift 2
            ;;
        --baud)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for $1"
                exit 1
            fi
            FPGA_BAUD="$2"
            shift 2
            ;;
        --kernel-calls)
            if [[ $# -lt 2 ]]; then
                echo "Missing value for $1"
                exit 1
            fi
            FPGA_KERNEL_CALLS="$2"
            shift 2
            ;;
        --skip-load-imem)
            FPGA_SKIP_LOAD_IMEM=1
            shift
            ;;
        --fpga-verbose)
            FPGA_VERBOSE=1
            shift
            ;;
        --)
            shift
            FPGA_EXTRA_ARGS+=("$@")
            break
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown generic option: $1"
            echo ""
            echo "If this is a program-specific FPGA option, put it after --."
            echo "Example:"
            echo "  $0 -p nbody --fpga --port /dev/ttyUSB1 --kernel-calls 1000 -- --steps 1"
            echo ""
            usage
            exit 1
            ;;
    esac
done

yes_no_prompt() {
    local prompt="$1"
    local answer=""

    while true; do
        read -rp "$prompt [y/n]: " answer
        case "$answer" in
            [Yy]|[Yy][Ee][Ss]) return 0 ;;
            [Nn]|[Nn][Oo]) return 1 ;;
            *) echo "Please answer y or n." ;;
        esac
    done
}

if [[ -z "$SELECTED" ]]; then
    echo "Available programs:"
    echo ""

    for i in "${!PROGRAMS[@]}"; do
        printf "  [%d] %s\n" "$((i + 1))" "${PROGRAMS[$i]}"
    done

    echo ""
    read -rp "Select a program number: " CHOICE

    if ! [[ "$CHOICE" =~ ^[0-9]+$ ]]; then
        echo "Invalid selection."
        exit 1
    fi

    INDEX=$((CHOICE - 1))
    if (( INDEX < 0 || INDEX >= ${#PROGRAMS[@]} )); then
        echo "Selection out of range."
        exit 1
    fi

    SELECTED="${PROGRAMS[$INDEX]}"
fi

VALID=0
for p in "${PROGRAMS[@]}"; do
    if [[ "$p" == "$SELECTED" ]]; then
        VALID=1
        break
    fi
done

if [[ "$VALID" -eq 0 ]]; then
    echo "Program '$SELECTED' does not exist."
    exit 1
fi

PROGRAM_DIR="$PROGRAMS_DIR/$SELECTED"
X86_EXE="$PROGRAM_DIR/${SELECTED}_x86"
DATA_CSV="$PROGRAM_DIR/data.csv"
VISUALIZE_SCRIPT="$PROGRAM_DIR/visualize.py"

if [[ "$TARGET" == "clean" ]]; then
    RUN_X86=0
    VISUALIZE=0
elif [[ "$RUN_FPGA" -eq 1 && "$RUN_FLAG_PROVIDED" -eq 0 && "$VISUALIZE_FLAG_PROVIDED" -eq 0 ]]; then
    RUN_X86=0
    VISUALIZE=0
elif [[ "$RUN_FLAG_PROVIDED" -eq 0 && "$VISUALIZE_FLAG_PROVIDED" -eq 0 ]]; then
    if yes_no_prompt "Run the native x86 version after compiling?"; then
        RUN_X86=1
    else
        RUN_X86=0
    fi

    if yes_no_prompt "Run visualization if visualize.py exists?"; then
        VISUALIZE=1
    else
        VISUALIZE=0
    fi
else
    if [[ -z "$RUN_X86" ]]; then
        RUN_X86=0
    fi
    if [[ -z "$VISUALIZE" ]]; then
        VISUALIZE=0
    fi
fi

if [[ "$VISUALIZE" -eq 1 && "$RUN_X86" -eq 0 && "$RUN_FPGA" -eq 0 && "$RUN_FLAG_PROVIDED" -eq 0 ]]; then
    echo "Visualization needs $DATA_CSV, so enabling x86 run."
    RUN_X86=1
fi

if [[ "$RUN_FPGA" -eq 1 ]]; then
    if [[ -z "$FPGA_PORT" ]]; then
        echo "--fpga requires --port PORT"
        exit 1
    fi
    if [[ "$TARGET" == "x86" || "$TARGET" == "clean" ]]; then
        echo "Cannot run FPGA when build target is '$TARGET'. Use target 'all' or 'riscv'."
        exit 1
    fi
fi

if [[ "$RUN_X86" -eq 1 && "$TARGET" == "riscv" ]]; then
    echo "Cannot run x86 when build target is 'riscv'. Use target 'all' or 'x86'."
    exit 1
fi

echo ""
echo "=========================================="
echo "Program      : $SELECTED"
echo "Target       : $TARGET"
echo "Run x86      : $RUN_X86"
echo "Run FPGA     : $RUN_FPGA"
echo "Kernel calls : ${FPGA_KERNEL_CALLS:-1}"
echo "Visualize    : $VISUALIZE"
echo "=========================================="
echo ""

make -C "$PROGRAMS_DIR" PROG="$SELECTED" clean
make -C "$PROGRAMS_DIR" PROG="$SELECTED" "$TARGET"

if [[ "$RUN_FPGA" -eq 1 ]]; then
    make -C "$PROGRAMS_DIR" PROG="$SELECTED" "$SELECTED/${SELECTED}_instructions.mem"
fi

if [[ "$RUN_X86" -eq 1 ]]; then
    if [[ ! -x "$X86_EXE" ]]; then
        echo "x86 executable not found or not executable: $X86_EXE"
        echo "Build with target 'all' or 'x86' to create it."
        exit 1
    fi

    echo ""
    echo "Running x86 program..."
    echo "Output: $DATA_CSV"
    "$X86_EXE" > "$DATA_CSV"
fi

if [[ "$RUN_FPGA" -eq 1 ]]; then
    FPGA_ARGS=(
        --program "$SELECTED"
        --port "$FPGA_PORT"
        --baud "$FPGA_BAUD"
        --kernel-calls "${FPGA_KERNEL_CALLS:-1}"
    )

    if [[ "$FPGA_SKIP_LOAD_IMEM" -eq 1 ]]; then
        FPGA_ARGS+=(--skip-load-imem)
    fi
    if [[ "$VISUALIZE" -eq 0 ]]; then
        FPGA_ARGS+=(--no-visualize)
    fi
    if [[ "$FPGA_VERBOSE" -eq 1 ]]; then
        FPGA_ARGS+=(--verbose)
    fi

    FPGA_ARGS+=("${FPGA_EXTRA_ARGS[@]}")

    echo ""
    echo "Running FPGA program through UART..."
    python3 "$PROGRAMS_DIR/fpga_run.py" "${FPGA_ARGS[@]}"
fi

if [[ "$VISUALIZE" -eq 1 && "$RUN_FPGA" -eq 0 ]]; then
    if [[ -f "$VISUALIZE_SCRIPT" ]]; then
        echo ""
        echo "Running visualization: $VISUALIZE_SCRIPT"
        (
            cd "$PROGRAM_DIR"
            python3 visualize.py
        )
    else
        echo ""
        echo "No visualize.py found for '$SELECTED'; skipping visualization."
    fi
fi
