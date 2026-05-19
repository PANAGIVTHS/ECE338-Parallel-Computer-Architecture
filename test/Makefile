# Default target
all: testsuite

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Default testbench
TB ?= tb_GPGPU.v

# Output executable
OUT ?= main

# Include/source directories
SRC_DIR := ../src

VERILOG_SOURCES := \
	$(SRC_DIR)/*.vh \
	$(SRC_DIR)/*.v \
	$(SRC_DIR)/memory/*.v \
	$(SRC_DIR)/sp/*.v

IVERILOG_FLAGS := -Wall -Wno-timescale -Winfloop -I $(SRC_DIR)

# ==============================================================================
# MODULAR TEST SUITE PIPELINE
# ==============================================================================

testsuite: assemble expected simulate

assemble:
	python3 assembler.py

expected:
	python3 expected_generator.py

compile:
	@echo "Compiling testbench: $(TB)"
	iverilog $(IVERILOG_FLAGS) -o $(OUT) $(TB) $(VERILOG_SOURCES)

simulate: compile
	vvp ./main | tee simulation.log
	@if grep -qE "\[FAIL\]|\[Error\]" simulation.log; then \
		exit 1; \
	fi

# ==============================================================================
# UTILITY TARGETS
# ==============================================================================

visualize:
	open http://0.0.0.0:8000/visualizer.html
	python3 -m http.server

clean:
	rm -f ./tests/test*/program.mem
	rm -f ./tests/test*/trace.csv
	rm -f ./tests/test*/data.mem          
	rm -f ./tests/test*/regfile_c*.mem    
	rm -f ./main
	rm -f ./dumpfile.vcd
	rm -f ./*.log
	rm -f ./*.jou