# 50 MHz PL oscillator (X2, CLK_50M) on a clock-capable pin of bank 34, the
# HDMI bank. clk_wiz_0 defines its clock from the block design port frequency.
set_property -dict {PACKAGE_PIN M19 IOSTANDARD LVCMOS33} [get_ports clk_50m]

## Map i_rst to Slide Switch SW0 (Down = 0/Reset, Up = 1/Run)
#set_property -dict {PACKAGE_PIN F22 IOSTANDARD LVCMOS33} [get_ports rst]

# Connect to leds (Bank 33, 3.3V)
set_property PACKAGE_PIN L17 [get_ports UART_0_0_txd]
set_property PACKAGE_PIN M17 [get_ports UART_0_0_rxd]
set_property IOSTANDARD LVCMOS33 [get_ports UART_0_0_txd]
set_property IOSTANDARD LVCMOS33 [get_ports UART_0_0_rxd]
# HDMI TMDS (rgb2dvi). The _n pins follow their pairs. TMDS_33 is also set by
# rgb2dvi's OBUFDS; stating it here makes a wrong bank fail at placement.
set_property IOSTANDARD TMDS_33 [get_ports {TMDS_0_clk_p {TMDS_0_data_p[*]}}]
# HDMI TMDS clock
set_property PACKAGE_PIN N19 [get_ports TMDS_0_clk_p]
# HDMI TMDS data lane 0
set_property PACKAGE_PIN M21 [get_ports {TMDS_0_data_p[0]}]
# HDMI TMDS data lane 1
set_property PACKAGE_PIN L21 [get_ports {TMDS_0_data_p[1]}]
# HDMI TMDS data lane 2
set_property PACKAGE_PIN J21 [get_ports {TMDS_0_data_p[2]}]

set_property -dict {PACKAGE_PIN P20 IOSTANDARD LVCMOS33} [get_ports o_core_idle_0]
set_property -dict {PACKAGE_PIN P21 IOSTANDARD LVCMOS33} [get_ports o_core_running_0]

