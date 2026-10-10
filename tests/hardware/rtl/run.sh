#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
TEST_TOOLS_DIR="$REPO_ROOT/tests/tools"
cd "$SCRIPT_DIR"


# Resolve repository fixtures/tools independently of the caller's directory.
CALLER_DIR="$PWD"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

ITERS=100
MODE="standard"
VISUALIZE=false
TB_MODE="e2e"
TB_FILE="tb_GPGPU_e2e.sv"
RANGE_START=""
RANGE_END=""

UART_PORT="/dev/ttyACM0"
UART_BAUD="115200"

print_help() {
    echo "=================================================================="
    echo " Streaming Multiprocessor / GPGPU Test Pipeline"
    echo "=================================================================="
    echo "Usage: ./run.sh [OPTIONS]"
    echo ""
    echo "Modes:"
    echo "  -s,  --standard          Compile/run SystemVerilog tests with Verilator"
    echo "  -r,  --rand              Run simulation testsuite, then random fuzzer"
    echo "       --host              Run tests on real board through UART"
    echo "       --gen-only          Only run assembler and expected generator"
    echo ""
    echo "Options:"
    echo "  -h,  --help              Show this help message"
    echo "  -i,  --iters NUM         Random fuzzer iterations"
    echo "       --range N           Run only test N"
    echo "       --range A-B         Run tests A through B inclusive"
    echo "  -c,  --clean             Clean generated files"
    echo "  -v,  --visualize         Open GTKWave after simulation"
    echo ""
    echo "Testbench selection:"
    echo "       --tb smx            Use tb_GPGPU.sv"
    echo "       --tb e2e            Use tb_GPGPU_e2e.sv"
    echo "       --tb-file FILE      Use a custom testbench file"
    echo ""
    echo "UART options:"
    echo "       --port PORT         Serial port, default: /dev/ttyACM0"
    echo "       --baud BAUD         Baud rate, default: 115200"
    echo ""
    echo "Examples:"
    echo "  ./run.sh --standard --tb e2e"
    echo "  ./run.sh --standard --tb smx --range 14"
    echo "  ./run.sh --standard --tb smx --range 10-14"
    echo "  ./run.sh --host --port /dev/ttyUSB1"
    echo "  ./run.sh --gen-only"
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

        --range)
            if [[ -z "$2" || "$2" == -* ]]; then
                echo "[ERROR] --range requires N or A-B"
                exit 1
            fi

            if [[ "$2" =~ ^[0-9]+$ ]]; then
                RANGE_START="$2"
                RANGE_END="$2"
            elif [[ "$2" =~ ^([0-9]+)-([0-9]+)$ ]]; then
                RANGE_START="${BASH_REMATCH[1]}"
                RANGE_END="${BASH_REMATCH[2]}"
            else
                echo "[ERROR] Invalid --range value: $2"
                echo "        Expected N or A-B, e.g. --range 14 or --range 10-14"
                exit 1
            fi

            if (( RANGE_START < 1 || RANGE_END < RANGE_START )); then
                echo "[ERROR] Invalid --range bounds: $2"
                exit 1
            fi

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
                    TB_FILE="tb_GPGPU.sv"
                    ;;
                e2e)
                    TB_FILE="tb_GPGPU_e2e.sv"
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
            if [[ "$TB_FILE" != /* && -f "$CALLER_DIR/$TB_FILE" ]]; then
                TB_FILE="$CALLER_DIR/$TB_FILE"
            fi
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

SIM_PLUSARGS="${PLUSARGS:-}"
if [[ "$VISUALIZE" == true ]]; then
    SIM_PLUSARGS="${SIM_PLUSARGS:+$SIM_PLUSARGS }+DUMP"
fi

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
if [[ -n "$RANGE_START" ]]; then
    echo " Test Range: $RANGE_START-$RANGE_END"
else
    echo " Test Range: all"
fi
echo " UART Port:  $UART_PORT"
echo " UART Baud:  $UART_BAUD"
echo " Iterations: $ITERS"
echo " Visualize:  $VISUALIZE"
echo "=================================================================="

case "$MODE" in
    gen-only)
        if [[ -n "$RANGE_START" ]]; then
            for ((test_num = RANGE_START; test_num <= RANGE_END; test_num++)); do
                test_dir="cases/test${test_num}"
                if [[ ! -f "$test_dir/program.asm" ]]; then
                    echo "[ERROR] Test not found: $test_dir/program.asm"
                    exit 1
                fi

                python3 "$TEST_TOOLS_DIR/assembler.py" "$test_dir" || exit $?
                python3 "$TEST_TOOLS_DIR/expected_generator.py" "$test_dir" || exit $?
            done
            exit 0
        else
            make gen
            exit $?
        fi
        ;;

    host)
        make host UART_PORT="$UART_PORT" UART_BAUD="$UART_BAUD"
        exit $?
        ;;

    standard|rand)
        TESTSUITE_FAILED=false

        echo -e "\n[Step 1/2] Running Verilator testsuite with $TB_FILE..."

        if [[ -n "$RANGE_START" ]]; then
            for ((test_num = RANGE_START; test_num <= RANGE_END; test_num++)); do
                test_dir="cases/test${test_num}"
                if [[ ! -f "$test_dir/program.asm" ]]; then
                    echo "[ERROR] Test not found: $test_dir/program.asm"
                    exit 1
                fi

                python3 "$TEST_TOOLS_DIR/assembler.py" "$test_dir" || TESTSUITE_FAILED=true
                python3 "$TEST_TOOLS_DIR/expected_generator.py" "$test_dir" || TESTSUITE_FAILED=true
            done

            if [ "$TESTSUITE_FAILED" = false ]; then
                if ! make simulate TB="$TB_FILE" EXTRA_FLAGS="-DSIM" \
                    PLUSARGS="+TEST_IDX=$RANGE_START +TEST_END=$RANGE_END $SIM_PLUSARGS"; then
                    TESTSUITE_FAILED=true
                fi
            fi
        elif ! make testsuite TB="$TB_FILE" EXTRA_FLAGS="-DSIM" PLUSARGS="$SIM_PLUSARGS"; then
            echo -e "\n[WARNING] Standard testsuite failed!"
            TESTSUITE_FAILED=true
        fi

        if [ "$VISUALIZE" = true ]; then
            echo -e "\n[Optional] Opening GTKWave..."

            if [ -f "./dumpfile.vcd" ]; then
                (gtkwave ./dumpfile.vcd ./waveform.gtkw > ./gtkwave.log 2>&1 &)
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

            python3 "$TEST_TOOLS_DIR/random_tester.py" --iterations "$ITERS"
        fi
        ;;

    *)
        echo "[ERROR] Unknown mode: $MODE"
        exit 1
        ;;
esac