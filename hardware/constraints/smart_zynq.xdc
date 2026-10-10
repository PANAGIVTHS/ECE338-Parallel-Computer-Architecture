### Clock Signal (100 MHz onboard clock)
#set_property -dict {PACKAGE_PIN Y9 IOSTANDARD LVCMOS33} [get_ports clk_in]
#create_clock -period 10.000 -name sys_clk -waveform {0.000 5.000} -add [get_ports clk_in]

## Map i_rst to Slide Switch SW0 (Down = 0/Reset, Up = 1/Run)
#set_property -dict {PACKAGE_PIN F22 IOSTANDARD LVCMOS33} [get_ports rst]

# Connect to leds (Bank 33, 3.3V)
set_property PACKAGE_PIN L17 [get_ports UART_0_0_txd]
set_property PACKAGE_PIN M17 [get_ports UART_0_0_rxd]
set_property IOSTANDARD LVCMOS33 [get_ports UART_0_0_txd]
set_property IOSTANDARD LVCMOS33 [get_ports UART_0_0_rxd]

set_property -dict {PACKAGE_PIN P20 IOSTANDARD LVCMOS33} [get_ports o_core_idle_0]
set_property -dict {PACKAGE_PIN P21 IOSTANDARD LVCMOS33} [get_ports o_core_running_0]
