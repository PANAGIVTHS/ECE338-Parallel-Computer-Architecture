# ZedBoard pins (ZedBoard Hardware User's Guide). The PS UART (UART1 on MIO
# 48/49), SD card and DDR3 are PS pins and need no constraints here.

# 100 MHz PL oscillator (IC17) on bank 13. clk_wiz_0 defines its clock from
# the block design port frequency.
set_property -dict {PACKAGE_PIN Y9 IOSTANDARD LVCMOS33} [get_ports clk_100m]

# GPGPU status on user LEDs LD0 and LD1 (bank 33, 3.3 V).
set_property -dict {PACKAGE_PIN T22 IOSTANDARD LVCMOS33} [get_ports o_core_idle_0]
set_property -dict {PACKAGE_PIN T21 IOSTANDARD LVCMOS33} [get_ports o_core_running_0]

# ADV7511 HDMI transmitter on bank 35 (3.3 V): 16-bit YCbCr 4:2:2 video from
# adv7511_video (HD-CLK, HD-DE, HD-HSYNC, HD-VSYNC, HD_D[15:0]).
set_property -dict {PACKAGE_PIN W18 IOSTANDARD LVCMOS33} [get_ports hdmi_clk]
set_property -dict {PACKAGE_PIN U16 IOSTANDARD LVCMOS33} [get_ports hdmi_de]
set_property -dict {PACKAGE_PIN V17 IOSTANDARD LVCMOS33} [get_ports hdmi_hsync]
set_property -dict {PACKAGE_PIN W17 IOSTANDARD LVCMOS33} [get_ports hdmi_vsync]
set_property -dict {PACKAGE_PIN Y13  IOSTANDARD LVCMOS33} [get_ports {hdmi_d[0]}]
set_property -dict {PACKAGE_PIN AA12 IOSTANDARD LVCMOS33} [get_ports {hdmi_d[1]}]
set_property -dict {PACKAGE_PIN AA14 IOSTANDARD LVCMOS33} [get_ports {hdmi_d[2]}]
set_property -dict {PACKAGE_PIN Y14  IOSTANDARD LVCMOS33} [get_ports {hdmi_d[3]}]
set_property -dict {PACKAGE_PIN AB15 IOSTANDARD LVCMOS33} [get_ports {hdmi_d[4]}]
set_property -dict {PACKAGE_PIN AB16 IOSTANDARD LVCMOS33} [get_ports {hdmi_d[5]}]
set_property -dict {PACKAGE_PIN AA16 IOSTANDARD LVCMOS33} [get_ports {hdmi_d[6]}]
set_property -dict {PACKAGE_PIN AB17 IOSTANDARD LVCMOS33} [get_ports {hdmi_d[7]}]
set_property -dict {PACKAGE_PIN AA17 IOSTANDARD LVCMOS33} [get_ports {hdmi_d[8]}]
set_property -dict {PACKAGE_PIN Y15  IOSTANDARD LVCMOS33} [get_ports {hdmi_d[9]}]
set_property -dict {PACKAGE_PIN W13  IOSTANDARD LVCMOS33} [get_ports {hdmi_d[10]}]
set_property -dict {PACKAGE_PIN W15  IOSTANDARD LVCMOS33} [get_ports {hdmi_d[11]}]
set_property -dict {PACKAGE_PIN V15  IOSTANDARD LVCMOS33} [get_ports {hdmi_d[12]}]
set_property -dict {PACKAGE_PIN U17  IOSTANDARD LVCMOS33} [get_ports {hdmi_d[13]}]
set_property -dict {PACKAGE_PIN V14  IOSTANDARD LVCMOS33} [get_ports {hdmi_d[14]}]
set_property -dict {PACKAGE_PIN V13  IOSTANDARD LVCMOS33} [get_ports {hdmi_d[15]}]

# ADV7511 I2C (HD-SCL, HD-SDA) from PS I2C0 over EMIO; the wrapper makes the
# IOBUFs of the IIC_0 interface port.
set_property -dict {PACKAGE_PIN AA18 IOSTANDARD LVCMOS33} [get_ports IIC_0_scl_io]
set_property -dict {PACKAGE_PIN Y16  IOSTANDARD LVCMOS33} [get_ports IIC_0_sda_io]
