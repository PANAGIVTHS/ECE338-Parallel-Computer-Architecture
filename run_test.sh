#!/bin/bash

ITERS=100
MODE="standard"
VISUALIZE=false
TB_MODE="e2e"
TB_FILE="tb_GPGPU_e2e.v"

UART_PORT="/dev/ttyACM0"
UART_BAUD="115200"

print_help() {
    echo "=================================================================="
    echo " Streaming Multiprocessor / GPGPU Test Pipeline"
    echo "=================================================================="
    echo "Usage: ./run_tests.sh [OPTIONS]"
    echo ""
    echo "Modes:"
    echo "  -s,  --standard          Run Verilog simulation testsuite"
    echo "  -r,  --rand              Run simulation testsuite, then random fuzzer"
    echo "       --host              Run tests on real board through UART"
    echo "       --gen-only          Only run assembler and expected generator"
    echo ""
    echo "Options:"
    echo "  -h,  --help              Show this help message"
    echo "  -i,  --iters NUM         Random fuzzer iterations"
    echo "  -c,  --clean             Clean generated files"
    echo "  -v,  --visualize         Open GTKWave after simulation"
    echo ""
    echo "Testbench selection:"
    echo "       --tb smx            Use tb_GPGPU.v"
    echo "       --tb e2e            Use tb_GPGPU_e2e.v"
    echo "       --tb-file FILE      Use a custom testbench file"
    echo ""
    echo "UART options:"
    echo "       --port PORT         Serial port, default: /dev/ttyACM0"
    echo "       --baud BAUD         Baud rate, default: 115200"
    echo ""
    echo "Examples:"
    echo "  ./run_tests.sh --standard --tb e2e"
    echo "  ./run_tests.sh --host --port /dev/ttyUSB1"
    echo "  ./run_tests.sh --gen-only"
    echo "=================================================================="
}

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

        --host)
            MODE="host"
            ;;

        --gen-only)
            MODE="gen-only"
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

        --port)
            UART_PORT="$2"
            shift
            ;;

        --baud)
            UART_BAUD="$2"
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

if [[ "$MODE" != "host" && "$MODE" != "gen-only" ]]; then
    if [ ! -f "$TB_FILE" ]; then
        echo "[ERROR] Testbench file not found: $TB_FILE"
        exit 1
    fi
fi

echo "=================================================================="
echo " Configuration"
echo "=================================================================="
echo " Mode:       $MODE"
echo " Testbench:  $TB_FILE"
echo " UART Port:  $UART_PORT"
echo " UART Baud:  $UART_BAUD"
echo " Iterations: $ITERS"
echo " Visualize:  $VISUALIZE"
echo "=================================================================="

case "$MODE" in
    gen-only)
        make gen
        exit $?
        ;;

    host)
        make host UART_PORT="$UART_PORT" UART_BAUD="$UART_BAUD"
        exit $?
        ;;

    standard|rand)
        TESTSUITE_FAILED=false

        echo -e "\n[Step 1/2] Running Verilog testsuite with $TB_FILE..."

        if ! make testsuite TB="$TB_FILE" IVERILOG_FLAGS="-Wall -Wno-timescale -Winfloop -I ../src -DSIM"; then
            echo -e "\n[WARNING] Standard testsuite failed!"
            TESTSUITE_FAILED=true
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
        ;;

    *)
        echo "[ERROR] Unknown mode: $MODE"
        exit 1
        ;;
esac