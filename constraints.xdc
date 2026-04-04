# Clock Signal (100 MHz onboard clock)
set_property -dict { PACKAGE_PIN Y9 IOSTANDARD LVCMOS33 } [get_ports { clk }];
create_clock -add -name sys_clk -period 16.00 -waveform {0 5} [get_ports { clk }];

# Button(s)
# NOTE: Buttons are on Bank 34. This expects the VADJ jumper (J18) to be set to 2.5V.
set_property -dict { PACKAGE_PIN P16 IOSTANDARD LVCMOS25 } [get_ports { rst }];

# Connect to leds
set_property PACKAGE_PIN T22 [get_ports {o_leds[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {o_leds[0]}]

set_property PACKAGE_PIN T21 [get_ports {o_leds[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {o_leds[1]}]

set_property PACKAGE_PIN U22 [get_ports {o_leds[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {o_leds[2]}]

set_property PACKAGE_PIN U21 [get_ports {o_leds[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {o_leds[3]}]

set_property PACKAGE_PIN V22 [get_ports {o_leds[4]}]
set_property IOSTANDARD LVCMOS33 [get_ports {o_leds[4]}]

set_property PACKAGE_PIN W22 [get_ports {o_leds[5]}]
set_property IOSTANDARD LVCMOS33 [get_ports {o_leds[5]}]

set_property PACKAGE_PIN U19 [get_ports {o_leds[6]}]
set_property IOSTANDARD LVCMOS33 [get_ports {o_leds[6]}]

set_property PACKAGE_PIN U14 [get_ports {o_leds[7]}]
set_property IOSTANDARD LVCMOS33 [get_ports {o_leds[7]}]

# Connect to switch
set_property PACKAGE_PIN F22 [get_ports i_dummy_wen]
set_property IOSTANDARD LVCMOS33 [get_ports i_dummy_wen]