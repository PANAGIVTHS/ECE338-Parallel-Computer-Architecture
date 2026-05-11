all: compile assemble run	

run: compile
	vvp ./main
	gtkwave ./dumpfile.vcd ./waveform.gtkw

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
													   ../src/GPGPU_top.v

assemble:
	python3 assembler.py

visualize:
	open http://0.0.0.0:8000/visualizer.html
	python3 -m http.server

clean:
	rm -f ./test*/program.mem
	rm -f ./test*/trace.csv
	rm -f ./main
