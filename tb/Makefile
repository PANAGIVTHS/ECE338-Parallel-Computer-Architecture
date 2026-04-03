all:
	iverilog -Wall -Winfloop -o main -I ../src tb_StreamingProcessor.v ../src/ALU.v ../src/Decoder.v ../src/GUCounter.v ../src/Memory.v ../src/Regfile.v ../src/StreamingProcessor.v

run: all
	vvp ./main
	gtkwave ./dumpfile.vcd ./waveform.gtkw

clean:
	rm ./main
