# Default target
all: testsuite

SHELL := /bin/bash
.SHELLFLAGS := -o pipefail -c

# ==============================================================================
# CONFIGURATION
# ==============================================================================

TB ?= tb_GPGPU.sv
# The SMX bench's module name differs from its filename.
TOP ?= $(if $(filter tb_GPGPU.sv,$(notdir $(TB))),tb_GPGPU_smx_only,$(basename $(notdir $(TB))))
OUT ?= main
VERILATOR ?= verilator
JOBS ?= 2
PLUSARGS ?=
EXTRA_FLAGS ?=
SRC_DIR := ../hw/gpgpu
BUILD_DIR ?= $(abspath .sim/$(TOP))
SIM_EXE := $(BUILD_DIR)/$(notdir $(OUT))

# Parse the interface before consumers. Headers are included, not source units.
MEMORY_INTERFACE := $(SRC_DIR)/memory/MemoryInterface.sv
VERILOG_SOURCES := $(MEMORY_INTERFACE) $(filter-out $(MEMORY_INTERFACE),$(wildcard \
	$(SRC_DIR)/*.sv $(SRC_DIR)/control/*.sv $(SRC_DIR)/memory/*.sv $(SRC_DIR)/sp/*.sv))
# Keep existing datapath warnings visible; they must not prevent simulation.
VERILATOR_FLAGS := --binary --timing --assert --trace -Wno-fatal \
	--timescale 1ns/1ps -I$(SRC_DIR)

UART_PORT ?= /dev/ttyACM0
UART_BAUD ?= 115200

.PHONY: all testsuite gen assemble expected compile simulate host visualize clean

# ==============================================================================
# MODULAR TEST SUITE PIPELINE
# ==============================================================================

# Keep generation ordered even when the outer make uses -j.
testsuite: gen
	$(MAKE) --no-print-directory simulate

gen: assemble
	$(MAKE) --no-print-directory expected

assemble:
	python3 $(REPO_ROOT)/tests/tools/assembler.py $(TEST_CASES_DIR)

expected:
	python3 $(REPO_ROOT)/tests/tools/expected_generator.py $(TEST_CASES_DIR)

compile:
	@echo "Compiling testbench: $(TB) (Verilator, top $(TOP))"
	mkdir -p $(BUILD_DIR) $(dir $(abspath $(OUT)))
	$(VERILATOR) $(VERILATOR_FLAGS) $(EXTRA_FLAGS) --top-module $(TOP) \
		--Mdir $(BUILD_DIR) -j $(JOBS) -o $(notdir $(OUT)) $(VERILOG_SOURCES) $(TB)
	@if [[ '$(SIM_EXE)' != '$(abspath $(OUT))' ]]; then cp $(SIM_EXE) $(abspath $(OUT)); fi

simulate: compile
	$(SIM_EXE) $(PLUSARGS) | tee simulation.log
	@if grep -qiE '\[FAIL\]|\[ERROR\]|%Error|Fatal:' simulation.log; then exit 1; fi

host: gen
	python3 $(REPO_ROOT)/tests/software/host/host_uart_tester.py --port $(UART_PORT) --baud $(UART_BAUD)

# ==============================================================================
# UTILITY TARGETS
# ==============================================================================

visualize:
	open http://0.0.0.0:8000/visualizer.html
	python3 -m http.server

clean:
	rm -f ./$(TEST_CASES_DIR)/test*/program.mem
	rm -f ./$(TEST_CASES_DIR)/test*/trace.csv
	rm -f ./$(TEST_CASES_DIR)/test*/data.mem
	rm -f ./$(TEST_CASES_DIR)/test*/regfile_c*.mem
	rm -f ./main
	rm -f ./dumpfile.vcd
	rm -f ./*.log
	rm -f ./*.jou
