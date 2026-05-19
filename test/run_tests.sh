#!/bin/bash

# Default Configuration
ITERS=100
MODE="standard"
VISUALIZE=false
TB_MODE="e2e"

# Help Message Function
print_help() {
    echo "=================================================================="
    echo " Streaming Multiprocessor / GPGPU Test & Fuzzer Pipeline"
    echo "=================================================================="
    echo "Usage: ./run_tests.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h,  --help              Show this help message and exit"
    echo "  -s,  --standard          Run only the standard testsuite (Default)"
    echo "  -r,  --rand              Run standard tests, then launch the random fuzzer"
    echo "  -i,  --iters NUM         Specify random iterations (Default: 100)"
    echo "  -c,  --clean             Clean generated .mem, .csv, .vcd, logs"
    echo "  -v,  --visualize         Open GTKWave after running standard tests"
    echo ""
    echo "Testbench selection:"
    echo "       --tb smx            Use tb_GPGPU.v (Default)"
    echo "       --tb e2e            Use tb_GPGPU_e2e.v"
    echo "       --tb-file FILE      Use a custom testbench file"
    echo ""
    echo "Examples:"
    echo "  ./run_tests.sh --standard --tb smx"
    echo "  ./run_tests.sh --standard --tb e2e"
    echo "  ./run_tests.sh --rand --iters 500 --tb smx"
    echo "  ./run_tests.sh --tb-file tb_custom.v"
    echo "=================================================================="
}

# Default testbench file
TB_FILE="tb_GPGPU_e2e.v"

# Parse Command Line Arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -h|--help)
            print_help
            exit 0
            ;;

        -s|--standard)
            MODE="standard"
            ;;

        -r|--rand)
            MODE="rand"
            ;;

        -i|--iters)
            ITERS="$2"
            shift
            ;;

        -c|--clean)
            make clean
            exit 0
            ;;

        -v|--visualize)
            VISUALIZE=true
            ;;

        --tb)
            TB_MODE="$2"
            shift

            case "$TB_MODE" in
                smx)
                    TB_FILE="tb_GPGPU.v"
                    ;;
                e2e)
                    TB_FILE="tb_GPGPU_e2e.v"
                    ;;
                *)
                    echo "Unknown --tb option: $TB_MODE"
                    echo "Valid options: smx, e2e"
                    exit 1
                    ;;
            esac
            ;;

        --tb-file)
            TB_FILE="$2"
            shift
            ;;

        *)
            echo "Unknown parameter passed: $1"
            print_help
            exit 1
            ;;
    esac
    shift
done

# Validate selected testbench exists
if [ ! -f "$TB_FILE" ]; then
    echo "[ERROR] Testbench file not found: $TB_FILE"
    exit 1
fi

echo "=================================================================="
echo " Configuration"
echo "=================================================================="
echo " Mode:       $MODE"
echo " Testbench:  $TB_FILE"
echo " Iterations: $ITERS"
echo " Visualize:  $VISUALIZE"
echo "=================================================================="

# ==============================================================================
# EXECUTION LOGIC
# ==============================================================================

TESTSUITE_FAILED=false

if [ "$MODE" == "standard" ] || [ "$MODE" == "rand" ]; then
    echo -e "\n[Step 1/2] Running Standard Testsuite with $TB_FILE..."

    if ! make testsuite TB="$TB_FILE" IVERILOG_FLAGS="-Wall -Wno-timescale -Winfloop -I ../src -DSIM"; then
        echo -e "\n[WARNING] Standard testsuite failed!"
        TESTSUITE_FAILED=true
    fi
fi

if [ "$VISUALIZE" = true ]; then
    echo -e "\n[Optional] Opening GTKWave..."

    if [ -f "./dumpfile.vcd" ]; then
        (gtkwave ./dumpfile.vcd ./waveform.gtkw > /dev/shm/gtkwave.log 2>&1 &)
        echo "  -> GTKWave launched in background."
    else
        echo "  -> [Error] dumpfile.vcd not found. Cannot open GTKWave."
    fi
fi

if [ "$TESTSUITE_FAILED" = true ]; then
    echo -e "\n[ERROR] Standard testsuite failed! Halting pipeline."
    exit 1
fi

if [ "$MODE" == "rand" ]; then
    echo -e "\n=================================================================="
    echo " Standard Testsuite Passed! Launching Random Fuzzer..."
    echo "=================================================================="

    python3 random_tester.py --iterations "$ITERS"
fi