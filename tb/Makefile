all: compile assemble run	

run: compile
	vvp ./main
	gtkwave ./dumpfile.vcd ./waveform.gtkw

compile:
	iverilog -Wall -Wno-timescale -Winfloop -o main -I ../src tb_StreamingProcessor.v \
															  ../src/*.vh ../src/*.v \
															  ../src/uart/*.v \
															  ../src/memory/*.v \
															  ../src/sp/*.v

assemble:
	python3 assembler.py

visualize:
	open http://0.0.0.0:8000/visualizer.html
	python3 -m http.server

clean:
	rm -f ./test*/program.mem
	rm -f ./test*/trace.csv
	rm -f ./main
