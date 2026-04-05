all: compile assemble run	

run: compile
	vvp ./main
	gtkwave ./dumpfile.vcd ./waveform.gtkw

compile:
	iverilog -Wall -Winfloop -o main -I ../src tb_StreamingProcessor.v ../src/ALU.v ../src/Decoder.v ../src/GUCounter.v ../src/Memory.v ../src/Regfile.v ../src/HazardUnit.v ../src/StreamingProcessor.v

assemble:
	python3 assembler.py

clean:
	rm ./main
