### Clock Signal (100 MHz onboard clock)
#set_property -dict {PACKAGE_PIN Y9 IOSTANDARD LVCMOS33} [get_ports clk_in]
#create_clock -period 10.000 -name sys_clk -waveform {0.000 5.000} -add [get_ports clk_in]

## Map i_rst to Slide Switch SW0 (Down = 0/Reset, Up = 1/Run)
#set_property -dict {PACKAGE_PIN F22 IOSTANDARD LVCMOS33} [get_ports rst]

# Connect to leds (Bank 33, 3.3V)
set_property -dict {PACKAGE_PIN T22 IOSTANDARD LVCMOS33} [get_ports o_loading_0]
set_property -dict {PACKAGE_PIN T21 IOSTANDARD LVCMOS33} [get_ports o_running_0]
set_property -dict {PACKAGE_PIN U22 IOSTANDARD LVCMOS33} [get_ports o_dumping_0]