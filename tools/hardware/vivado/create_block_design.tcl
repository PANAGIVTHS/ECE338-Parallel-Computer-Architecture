# Clean-checkout bootstrap only. Existing saved designs are never sourced over.
# PS user inputs transcribed from the authoritative saved 2025.2 design_1.bd;
# the fabric clock comes from hardware.vivado.fabric_clock_mhz.
# Computed PCW_ACT_* / clock outputs are intentionally left to Vivado.
proc create_block_design {} {
    global BD_NAME FCLK0_MHZ
    if {[version -short] ne "2025.2"} { error "This system requires Vivado 2025.2" }
    create_bd_design $BD_NAME
    current_bd_design $BD_NAME

    create_bd_intf_port -mode Master -vlnv xilinx.com:interface:ddrx_rtl:1.0 DDR
    create_bd_intf_port -mode Master -vlnv xilinx.com:display_processing_system7:fixedio_rtl:1.0 FIXED_IO
    create_bd_intf_port -mode Master -vlnv xilinx.com:interface:uart_rtl:1.0 UART_0_0
    create_bd_port -dir O o_core_idle_0
    create_bd_port -dir O o_core_running_0

    set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]
    set_property -dict [list \
        CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ $FCLK0_MHZ \
        CONFIG.PCW_FPGA_FCLK0_ENABLE {1} \
        CONFIG.PCW_USE_M_AXI_GP0 {1} \
        CONFIG.PCW_UART0_PERIPHERAL_ENABLE {1} \
        CONFIG.PCW_UART0_UART0_IO {EMIO} \
        CONFIG.PCW_UART0_GRP_FULL_ENABLE {0} \
        CONFIG.PCW_UART_PERIPHERAL_FREQMHZ {100} \
        CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41K256M16 RE-125} \
        CONFIG.PCW_UIPARAM_DDR_BUS_WIDTH {16 Bit} \
        CONFIG.PCW_UIPARAM_DDR_ECC {Disabled} \
        CONFIG.PCW_USE_FABRIC_INTERRUPT {1} \
        CONFIG.PCW_IRQ_F2P_INTR {1}] $ps
    create_bd_cell -type ip -vlnv user.org:user:gpgpu_axi:1.0 gpgpu_axi_0
    set smc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_smc]
    set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $smc
    set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_ps7_0_35M]
    # FCLK_RESET0_N is active low; proc_sys_reset defaults to active high.
    set_property CONFIG.C_EXT_RESET_HIGH {0} $rst
    set irq [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat:2.1 irq_concat]
    set_property -dict [list CONFIG.NUM_PORTS {2} CONFIG.IN0_WIDTH {1} CONFIG.IN1_WIDTH {15}] $irq
    set zero [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 irq_zero]
    set_property -dict [list CONFIG.CONST_WIDTH {15} CONFIG.CONST_VAL {0}] $zero
    set locked [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 reset_locked]
    set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {1}] $locked

    foreach name {DDR FIXED_IO} {
        connect_bd_intf_net [get_bd_intf_ports $name] [get_bd_intf_pins processing_system7_0/$name]
    }
    connect_bd_intf_net [get_bd_intf_ports UART_0_0] [get_bd_intf_pins processing_system7_0/UART_0]
    connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP0] [get_bd_intf_pins axi_smc/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins axi_smc/M00_AXI] [get_bd_intf_pins gpgpu_axi_0/s00_axi]
    connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
        [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK] [get_bd_pins axi_smc/aclk] \
        [get_bd_pins gpgpu_axi_0/s00_axi_aclk] [get_bd_pins rst_ps7_0_35M/slowest_sync_clk]
    connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] [get_bd_pins rst_ps7_0_35M/ext_reset_in]
    connect_bd_net [get_bd_pins reset_locked/dout] [get_bd_pins rst_ps7_0_35M/dcm_locked]
    connect_bd_net [get_bd_pins rst_ps7_0_35M/peripheral_aresetn] \
        [get_bd_pins gpgpu_axi_0/s00_axi_aresetn] [get_bd_pins axi_smc/aresetn]
    # In0 is bit 0 of the 16-bit fabric IRQ bus (PS interrupt ID 61).
    connect_bd_net [get_bd_pins gpgpu_axi_0/irq] [get_bd_pins irq_concat/In0]
    connect_bd_net [get_bd_pins irq_zero/dout] [get_bd_pins irq_concat/In1]
    connect_bd_net [get_bd_pins irq_concat/dout] [get_bd_pins processing_system7_0/IRQ_F2P]
    foreach signal {idle running} {
        connect_bd_net [get_bd_pins gpgpu_axi_0/o_core_$signal] [get_bd_ports o_core_${signal}_0]
    }
}
