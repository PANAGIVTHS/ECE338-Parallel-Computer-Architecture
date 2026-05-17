# Default target
all: testsuite

# ==============================================================================
# MODULAR TEST SUITE PIPELINE
# ==============================================================================

testsuite: assemble expected simulate

assemble:
	python3 assembler.py

expected:
	python3 expected_generator.py

compile:
	iverilog -Wall -Wno-timescale -Winfloop -o main -I ../src tb_StreamingProcessor.v \
                                                       ../src/ALU.v \
                                                       ../src/Decoder.v \
                                                       ../src/GUCounter.v \
                                                       ../src/MemoryDualPort.v \
                                                       ../src/MemorySinglePort.v \
                                                       ../src/Regfile.v \
                                                       ../src/ForwardingUnit.v \
                                                       ../src/HazardUnit.v \
                                                       ../src/ClockDivider.v \
                                                       ../src/StreamingProcessor.v \
                                                       ../src/MemoryCrossbarNxM.v \
                                                       ../src/StreamingMultiprocessor.v

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
	rm -f ./test*/program.mem
	rm -f ./test*/trace.csv
	rm -f ./test*/data.mem          
	rm -f ./test*/regfile_c*.mem    
	rm -f ./main
	rm -f ./dumpfile.vcd
	rm -f ./simulation.log