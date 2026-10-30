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
SRC_DIR ?= $(REPO_ROOT)/hardware/rtl/gpgpu
BUILD_DIR ?= $(abspath .sim/$(TOP))
SIM_EXE := $(BUILD_DIR)/$(notdir $(OUT))

# Source discovery (mirrors the runner's tests.rtl.sources.* config).
#   SRC_DIR        : RTL root to scan.
#   EXCLUDE_DIRS   : path segments to skip.
#   ORDERED_SOURCES: the single source of truth for compile order — every
#                    order-sensitive file (packages + interfaces) in DEPENDENCY
#                    order, relative to SRC_DIR. Verilator compiles in
#                    command-line order and needs a package/interface declared
#                    before anything that uses its types (including other
#                    packages). Anything NOT listed here is a module and is
#                    globbed after (module order is irrelevant). No implicit
#                    detection: a package you forget to list fails loudly with
#                    "reference before declaration". Headers come in via -I.
EXCLUDE_DIRS ?= 
ORDERED_SOURCES ?= 

_PRUNE   := $(foreach d,$(EXCLUDE_DIRS),-not -path '*/$(d)/*')
_ORDERED := $(addprefix $(SRC_DIR)/,$(ORDERED_SOURCES))
_REST    := $(filter-out $(_ORDERED),$(shell find $(SRC_DIR) -name '*.sv' $(_PRUNE) | sort))
VERILOG_SOURCES := $(_ORDERED) $(_REST)

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