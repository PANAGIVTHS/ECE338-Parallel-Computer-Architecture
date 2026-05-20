#!/usr/bin/env bash

set -e

PROGRAMS_DIR="."

# ==========================================
# Discover available programs
# ==========================================
mapfile -t PROGRAMS < <(
    find "$PROGRAMS_DIR" -mindepth 1 -maxdepth 1 -type d \
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

# ==========================================
# Print usage
# ==========================================
usage() {
    echo "Usage:"
    echo "  $0                 # Interactive selection"
    echo "  $0 -p PROGRAM      # Select program directly"
    echo "  $0 --program NAME"
    echo ""
    echo "Optional targets:"
    echo "  all     (default)"
    echo "  riscv"
    echo "  x86"
    echo "  clean"
    echo ""
    echo "Examples:"
    echo "  $0"
    echo "  $0 -p nbody"
    echo "  $0 --program simple riscv"
    echo "  $0 -p differences clean"
}

# ==========================================
# Parse arguments
# ==========================================
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--program)
            SELECTED="$2"
            shift 2
            ;;
        all|riscv|x86|clean)
            TARGET="$1"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo ""
            usage
            exit 1
            ;;
    esac
done

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

    # Validate numeric input
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

# ==========================================
# Build
# ==========================================
echo ""
echo "=========================================="
echo "Program : $SELECTED"
echo "Target  : $TARGET"
echo "=========================================="
echo ""

make -C "$PROGRAMS_DIR" PROG="$SELECTED" clean
make -C "$PROGRAMS_DIR" PROG="$SELECTED" "$TARGET"
