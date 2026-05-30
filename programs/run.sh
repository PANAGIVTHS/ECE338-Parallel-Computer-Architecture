#!/usr/bin/env bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROGRAMS_DIR="$SCRIPT_DIR"

# ==========================================
# Discover available programs
# ==========================================
mapfile -t PROGRAMS < <(
    find "$PROGRAMS_DIR" -mindepth 1 -maxdepth 1 -type d ! -name '__pycache__' \
    | xargs -n1 basename \
    | sort
)

if [ ${#PROGRAMS[@]} -eq 0 ]; then
    echo "No program directories found."
    exit 1
fi

# ==========================================
# Defaults
# ==========================================
SELECTED=""
TARGET="all"
RUN_X86=""
VISUALIZE=""
RUN_FPGA=0
FPGA_PORT=""
FPGA_BAUD=115200
FPGA_SKIP_LOAD_IMEM=0
PROGRAM_ARGS=()
RUN_FLAG_PROVIDED=0
VISUALIZE_FLAG_PROVIDED=0

# ==========================================
# Print usage
# ==========================================
usage() {
    echo "Usage:"
    echo "  $0                              # Interactive selection"
    echo "  $0 -p PROGRAM                   # Compile selected program"
    echo "  $0 --program NAME"
    echo ""
    echo "Optional build targets:"
    echo "  all     (default)"
    echo "  riscv"
    echo "  x86"
    echo "  clean"
    echo ""
    echo "Run options:"
    echo "  -x, --x86, --run-x86            Run the compiled native x86 binary"
    echo "  --no-x86                        Do not run the native x86 binary"
    echo "  -v, --visualize                 Run visualize.py if the program has one"
    echo "  --no-visualize                  Do not run visualization"
    echo "  --fpga                          Run the program on FPGA through UART"
    echo "  --port PORT                     UART serial port for --fpga, e.g. /dev/ttyUSB1"
    echo "  --baud BAUD                     UART baud rate for --fpga (default: 115200)"
    echo "  --skip-load-imem                Reuse already-loaded IMEM for --fpga"
    echo "  -- [PROGRAM ARGS...]            Forward args to x86 binary and/or FPGA adapter"
    echo ""
    echo "If neither x86, FPGA, nor visualization options are provided, the script prompts."
    echo "x86 output is written to: programs/<program>/data.csv"
}

# ==========================================
# Parse arguments
# ==========================================
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
        --skip-load-imem)
            FPGA_SKIP_LOAD_IMEM=1
            shift
            ;;
        --)
            shift
            PROGRAM_ARGS+=("$@")
            break
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            PROGRAM_ARGS+=("$1")
            shift
            ;;
    esac
done

# ==========================================
# Helpers
# ==========================================
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

# ==========================================
# Interactive selection if needed
# ==========================================
if [[ -z "$SELECTED" ]]; then
    echo "Available programs:"
    echo ""

    for i in "${!PROGRAMS[@]}"; do
        printf "  [%d] %s\n" "$((i+1))" "${PROGRAMS[$i]}"
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

# ==========================================
# Validate selected program
# ==========================================
VALID=0

for p in "${PROGRAMS[@]}"; do
    if [[ "$p" == "$SELECTED" ]]; then
        VALID=1
        break
    fi
done

if [[ $VALID -eq 0 ]]; then
    echo "Program '$SELECTED' does not exist."
    exit 1
fi

PROGRAM_DIR="$PROGRAMS_DIR/$SELECTED"
X86_EXE="$PROGRAM_DIR/${SELECTED}_x86"
DATA_CSV="$PROGRAM_DIR/data.csv"
VISUALIZE_SCRIPT="$PROGRAM_DIR/visualize.py"

if [[ ${#PROGRAM_ARGS[@]} -eq 1 && ( "${PROGRAM_ARGS[0]}" == "--help" || "${PROGRAM_ARGS[0]}" == "-h" ) ]]; then
    python3 "$PROGRAMS_DIR/fpga_run.py" --program "$SELECTED" --adapter-help
    exit 0
fi

# ==========================================
# Prompt for run/visualize behavior if needed
# ==========================================
if [[ "$TARGET" == "clean" ]]; then
    RUN_X86=0
    VISUALIZE=0
elif [[ "$RUN_FPGA" -eq 1 && $RUN_FLAG_PROVIDED -eq 0 && $VISUALIZE_FLAG_PROVIDED -eq 0 ]]; then
    RUN_X86=0
    VISUALIZE=0
elif [[ $RUN_FLAG_PROVIDED -eq 0 && $VISUALIZE_FLAG_PROVIDED -eq 0 ]]; then
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

# Visualization normally needs fresh data from the native run. If the user asked
# for visualization but did not make an explicit x86/no-x86 choice, enable x86
# automatically so programs/<program>/data.csv is regenerated first.
if [[ "$VISUALIZE" -eq 1 && "$RUN_X86" -eq 0 && "$RUN_FPGA" -eq 0 && $RUN_FLAG_PROVIDED -eq 0 ]]; then
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

if [[ ${#PROGRAM_ARGS[@]} -gt 0 && "$RUN_X86" -eq 0 && "$RUN_FPGA" -eq 0 ]]; then
    echo "Program-specific argument(s) provided but neither x86 nor FPGA execution is enabled: ${PROGRAM_ARGS[*]}"
    echo "Use --x86 or --fpga, or remove the arguments after --."
    exit 1
fi

# ==========================================
# Build
# ==========================================
echo ""
echo "=========================================="
echo "Program   : $SELECTED"
echo "Target    : $TARGET"
echo "Run x86   : $RUN_X86"
echo "Run FPGA  : $RUN_FPGA"
echo "Visualize : $VISUALIZE"
echo "=========================================="
echo ""

make -C "$PROGRAMS_DIR" PROG="$SELECTED" clean
make -C "$PROGRAMS_DIR" PROG="$SELECTED" "$TARGET"

if [[ "$RUN_FPGA" -eq 1 ]]; then
    make -C "$PROGRAMS_DIR" PROG="$SELECTED" "$SELECTED/${SELECTED}_instructions.mem"
fi

# ==========================================
# Optional x86 run
# ==========================================
if [[ "$RUN_X86" -eq 1 ]]; then
    if [[ ! -x "$X86_EXE" ]]; then
        echo "x86 executable not found or not executable: $X86_EXE"
        echo "Build with target 'all' or 'x86' to create it."
        exit 1
    fi

    echo ""
    echo "Running x86 program..."
    echo "Output: $DATA_CSV"
    "$X86_EXE" "${PROGRAM_ARGS[@]}" > "$DATA_CSV"
fi


# ==========================================
# Optional FPGA run
# ==========================================
if [[ "$RUN_FPGA" -eq 1 ]]; then
    FPGA_ARGS=(
        --program "$SELECTED"
        --port "$FPGA_PORT"
        --baud "$FPGA_BAUD"
    )

    if [[ "$FPGA_SKIP_LOAD_IMEM" -eq 1 ]]; then
        FPGA_ARGS+=(--skip-load-imem)
    fi
    if [[ "$VISUALIZE" -eq 0 ]]; then
        FPGA_ARGS+=(--no-visualize)
    fi
    FPGA_ARGS+=("${PROGRAM_ARGS[@]}")

    echo ""
    echo "Running FPGA program through UART..."
    python3 "$PROGRAMS_DIR/fpga_run.py" "${FPGA_ARGS[@]}"
fi

# ==========================================
# Optional visualization
# ==========================================
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
