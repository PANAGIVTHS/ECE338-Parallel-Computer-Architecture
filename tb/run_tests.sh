#!/bin/bash

# Default Configuration
ITERS=100
MODE="standard"
VISUALIZE=false

# Help Message Function
print_help() {
    echo "=================================================================="
    echo " Streaming Multiprocessor Test & Fuzzer Pipeline"
    echo "=================================================================="
    echo "Usage: ./run_tests.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h,  --help         Show this help message and exit"
    echo "  -s,  --standard     Run only the standard testsuite (Default)"
    echo "  -r,  --rand         Run standard tests, then launch the random fuzzer"
    echo "  -i,  --iters NUM    Specify the number of random iterations (Default: 100)"
    echo "  -c,  --clean        Clean all generated .mem, .csv, and .vcd files"
    echo "  -v,  --visualize    Open GTKWave after running standard tests"
    echo "=================================================================="
}

# Parse Command Line Arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -h|--help) print_help; exit 0 ;;
        -s|--standard) MODE="standard" ;;
        -r|--rand) MODE="rand" ;;
        -i|--iters) ITERS="$2"; shift ;;
        -c|--clean) make clean; exit 0 ;;
        -v|--visualize) VISUALIZE=true ;;
        *) echo "Unknown parameter passed: $1"; print_help; exit 1 ;;
    esac
    shift
done

# ==============================================================================
# EXECUTION LOGIC
# ==============================================================================

if [ "$MODE" == "standard" ] || [ "$MODE" == "rand" ]; then
    echo -e "\n[Step 1/2] Running Standard Testsuite..."
    # Call the Makefile to compile and run standard tests
    if ! make testsuite; then
        echo -e "\n[ERROR] Standard testsuite failed! Halting pipeline."
        exit 1
    fi
fi

if [ "$VISUALIZE" = true ]; then
    echo -e "\n[Optional] Opening GTKWave..."
    # Check if the dump file exists before trying to open it
    if [ -f "./dump.vcd" ]; then
        (gtkwave ./dump.vcd ./waveform.gtkw > /dev/shm/gtkwave.log 2>&1 &)
        echo "  -> GTKWave launched in background."
    else
        echo "  -> [Error] dump.vcd not found. Cannot open GTKWave."
    fi
fi

if [ "$MODE" == "rand" ]; then
    echo -e "\n=================================================================="
    echo " Standard Testsuite Passed! Launching Random Fuzzer..."
    echo "=================================================================="
    # Call the Python fuzzer with the specified iterations
    python3 random_tester.py --iterations "$ITERS"
fi