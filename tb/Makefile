# Default target
all: testsuite run

# ==============================================================================
# MODULAR TEST SUITE PIPELINE
# ==============================================================================

# 1. The main testsuite target (Executes in order: Assemble -> Expected -> Simulate)
testsuite: assemble expected simulate

# 2. Assembles the .asm files into .mem files
assemble:
	python3 assembler.py

# 3. Generates the golden regfile and data memories
expected:
	python3 expected_generator.py

# 4. Compiles the Verilog code
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
                                                       ../src/MemoryCrossbarNx2.v \
                                                       ../src/StreamingMultiprocessor.v

# 5. Runs the testbench (without opening the GUI)
simulate: compile
	vvp ./main

# ==============================================================================
# UTILITY TARGETS
# ==============================================================================

# Runs the simulation AND opens the waveform viewer
run: simulate
	gtkwave ./dumpfile.vcd ./waveform.gtkw

visualize:
	open http://0.0.0.0:8000/visualizer.html
	python3 -m http.server

# Cleans up all generated files
clean:
	rm -f ./test*/program.mem
	rm -f ./test*/trace.csv
	rm -f ./test*/data.mem          
	rm -f ./test*/regfile_c*.mem    
	rm -f ./main
	rm -f ./dumpfile.vcd