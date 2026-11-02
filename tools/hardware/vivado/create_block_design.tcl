# Clean-checkout bootstrap only. Existing saved designs are never sourced over.
# PS user inputs transcribed from the authoritative saved 2025.2 design_1.bd;
# the fabric clock comes from hardware.vivado.fabric_clock_mhz.
# Computed PCW_ACT_* / clock outputs are intentionally left to Vivado.
#
# Two masters reach PS DDR, each through its own HP port so that they meet only
# in the DDR controller (HP0/HP1 and HP2/HP3 share its ports): the GPGPU's
# m00_axi (DDR backend) on HP0 and the VDMA on HP2. The VDMA reads the
# framebuffer for HDMI scanout (VDMA -> 4-to-3-byte subset converter ->
# AXI4-Stream video out -> rgb2dvi). Each master has a 1x1 SmartConnect, which
# also converts AXI4 to the HP port's AXI3. Everything runs on FCLK_CLK0
# except the 74.25 MHz (720p60) pixel clock.
proc create_block_design {} {
    global BD_NAME FCLK0_MHZ
    if {[version -short] ne "2025.2"} { error "This system requires Vivado 2025.2" }
    create_bd_design $BD_NAME
    current_bd_design $BD_NAME

    create_bd_intf_port -mode Master -vlnv xilinx.com:interface:ddrx_rtl:1.0 DDR
    create_bd_intf_port -mode Master -vlnv xilinx.com:display_processing_system7:fixedio_rtl:1.0 FIXED_IO
    create_bd_intf_port -mode Master -vlnv xilinx.com:interface:uart_rtl:1.0 UART_0_0
    create_bd_intf_port -mode Master -vlnv digilentinc.com:interface:tmds_rtl:1.0 TMDS_0
    create_bd_port -dir O o_core_idle_0
    create_bd_port -dir O o_core_running_0

    # GP0: GPGPU CSRs. GP1: VDMA registers. HP0: GPGPU to DDR. HP2: VDMA to DDR.
    set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0]
    set_property -dict [list \
        CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ $FCLK0_MHZ \
        CONFIG.PCW_FPGA_FCLK0_ENABLE {1} \
        CONFIG.PCW_USE_M_AXI_GP0 {1} \
        CONFIG.PCW_USE_M_AXI_GP1 {1} \
        CONFIG.PCW_USE_S_AXI_HP0 {1} \
        CONFIG.PCW_USE_S_AXI_HP2 {1} \
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
    # Vivado 2025.2 inline HDL replaces xlconcat/xlconstant; widths follow the connections.
    create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilconcat:1.0 irq_concat
    set zero [create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilconstant:1.0 irq_zero]
    set_property -dict [list CONFIG.CONST_WIDTH {15} CONFIG.CONST_VAL {0}] $zero
    create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilconstant:1.0 reset_locked

    # One SmartConnect per DDR master
    foreach name {gpgpu_ddr vdma_ddr} {
        set ddr_smc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 $name]
        set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] $ddr_smc
    }
    # GP1 to the VDMA's AXI4-Lite registers
    set vdma_smc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_smc_1]
    set_property CONFIG.NUM_SI {1} $vdma_smc

    # Scanout: read-only VDMA of 32-bit pixels (one framebuffer word each),
    # two frame stores (FB0, FB1), 16-beat bursts.
    set vdma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_vdma:6.3 axi_vdma_0]
    set_property -dict [list \
        CONFIG.c_include_s2mm {0} \
        CONFIG.c_m_axis_mm2s_tdata_width {32} \
        CONFIG.c_mm2s_genlock_mode {0} \
        CONFIG.c_mm2s_linebuffer_depth {4096} \
        CONFIG.c_mm2s_max_burst_length {16} \
        CONFIG.c_num_fstores {2}] $vdma
    # 0x00RRGGBB pixels to the 24-bit AXI4-Stream video order {R, B, G}.
    # TKEEP/TREADY/TSTRB/TID/TDEST follow the connected streams.
    set pixels [create_bd_cell -type ip -vlnv xilinx.com:ip:axis_subset_converter:1.1 axis_subset_converter_0]
    set_property -dict [list \
        CONFIG.S_TDATA_NUM_BYTES {4} CONFIG.M_TDATA_NUM_BYTES {3} \
        CONFIG.S_TUSER_WIDTH {1} CONFIG.M_TUSER_WIDTH {1} \
        CONFIG.S_HAS_TLAST {1} CONFIG.M_HAS_TLAST {1} \
        CONFIG.TDATA_REMAP {tdata[23:16],tdata[7:0],tdata[15:8]}] $pixels
    set vid_out [create_bd_cell -type ip -vlnv xilinx.com:ip:v_axi4s_vid_out:4.0 v_axi4s_vid_out_0]
    set_property -dict [list \
        CONFIG.C_ADDR_WIDTH {12} \
        CONFIG.C_HAS_ASYNC_CLK {1} \
        CONFIG.C_HYSTERESIS_LEVEL {16} \
        CONFIG.C_S_AXIS_VIDEO_DATA_WIDTH {8} \
        CONFIG.C_S_AXIS_VIDEO_FORMAT {2} \
        CONFIG.C_VTG_MASTER_SLAVE {1}] $vid_out
    # Video timing generator only (its default mode), no register interface.
    set vtc [create_bd_cell -type ip -vlnv xilinx.com:ip:v_tc:6.2 v_tc_0]
    set_property -dict [list \
        CONFIG.HAS_AXI4_LITE {false} \
        CONFIG.enable_detection {false} \
        CONFIG.max_clocks_per_line {2048} \
        CONFIG.max_lines_per_frame {1024}] $vtc
    # 720p60 pixel clock from FCLK_CLK0; the MMCM settings are Vivado's.
    set pixel_clk [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz:6.0 clk_wiz_0]
    set_property -dict [list CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {74.25} CONFIG.USE_RESET {false}] $pixel_clk
    set pixel_rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 proc_sys_reset_0]
    set_property CONFIG.C_EXT_RESET_HIGH {0} $pixel_rst
    # kClkRange 3 is rgb2dvi's "< 80 MHz (720p)" range. Its serial PLL runs at
    # PixelClk * (kClkRange + 1) * 5 = 1485 MHz, inside the -1 grade's
    # 800-1600 MHz; the default 1 (">= 120 MHz") gives 742.5 MHz, below it.
    set hdmi [create_bd_cell -type ip -vlnv digilentinc.com:ip:rgb2dvi:1.4 rgb2dvi_0]
    set_property CONFIG.kClkRange {3} $hdmi
    # Clock enables tied on; field id tied to 0 (progressive).
    create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilconstant:1.0 clk_en
    set field [create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilconstant:1.0 clk_en1]
    set_property CONFIG.CONST_VAL {0} $field

    foreach name {DDR FIXED_IO} {
        connect_bd_intf_net [get_bd_intf_ports $name] [get_bd_intf_pins processing_system7_0/$name]
    }
    connect_bd_intf_net [get_bd_intf_ports UART_0_0] [get_bd_intf_pins processing_system7_0/UART_0]
    connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP0] [get_bd_intf_pins axi_smc/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins axi_smc/M00_AXI] [get_bd_intf_pins gpgpu_axi_0/s00_axi]
    connect_bd_intf_net [get_bd_intf_pins gpgpu_axi_0/m00_axi] [get_bd_intf_pins gpgpu_ddr/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins gpgpu_ddr/M00_AXI] [get_bd_intf_pins processing_system7_0/S_AXI_HP0]
    connect_bd_intf_net [get_bd_intf_pins axi_vdma_0/M_AXI_MM2S] [get_bd_intf_pins vdma_ddr/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins vdma_ddr/M00_AXI] [get_bd_intf_pins processing_system7_0/S_AXI_HP2]
    connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP1] [get_bd_intf_pins axi_smc_1/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins axi_smc_1/M00_AXI] [get_bd_intf_pins axi_vdma_0/S_AXI_LITE]
    connect_bd_intf_net [get_bd_intf_pins axi_vdma_0/M_AXIS_MM2S] [get_bd_intf_pins axis_subset_converter_0/S_AXIS]
    connect_bd_intf_net [get_bd_intf_pins axis_subset_converter_0/M_AXIS] [get_bd_intf_pins v_axi4s_vid_out_0/video_in]
    connect_bd_intf_net [get_bd_intf_pins v_tc_0/vtiming_out] [get_bd_intf_pins v_axi4s_vid_out_0/vtiming_in]
    connect_bd_intf_net [get_bd_intf_pins rgb2dvi_0/TMDS] [get_bd_intf_ports TMDS_0]

    # FCLK_CLK0: the GPGPU, every AXI interface and the pixel clock's source
    connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
        [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK] [get_bd_pins processing_system7_0/M_AXI_GP1_ACLK] \
        [get_bd_pins processing_system7_0/S_AXI_HP0_ACLK] [get_bd_pins processing_system7_0/S_AXI_HP2_ACLK] \
        [get_bd_pins axi_smc/aclk] [get_bd_pins gpgpu_ddr/aclk] [get_bd_pins vdma_ddr/aclk] \
        [get_bd_pins axi_smc_1/aclk] \
        [get_bd_pins gpgpu_axi_0/aclk] [get_bd_pins rst_ps7_0_35M/slowest_sync_clk] \
        [get_bd_pins axi_vdma_0/s_axi_lite_aclk] [get_bd_pins axi_vdma_0/m_axi_mm2s_aclk] \
        [get_bd_pins axi_vdma_0/m_axis_mm2s_aclk] [get_bd_pins axis_subset_converter_0/aclk] \
        [get_bd_pins v_axi4s_vid_out_0/aclk] [get_bd_pins clk_wiz_0/clk_in1]
    connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] \
        [get_bd_pins rst_ps7_0_35M/ext_reset_in] [get_bd_pins proc_sys_reset_0/ext_reset_in]
    connect_bd_net [get_bd_pins reset_locked/dout] [get_bd_pins rst_ps7_0_35M/dcm_locked]
    connect_bd_net [get_bd_pins rst_ps7_0_35M/peripheral_aresetn] \
        [get_bd_pins gpgpu_axi_0/aresetn] [get_bd_pins axi_smc/aresetn] \
        [get_bd_pins gpgpu_ddr/aresetn] [get_bd_pins vdma_ddr/aresetn] \
        [get_bd_pins axi_smc_1/aresetn] [get_bd_pins axi_vdma_0/axi_resetn] \
        [get_bd_pins axis_subset_converter_0/aresetn] [get_bd_pins v_axi4s_vid_out_0/aresetn]
    # Pixel clock domain
    connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] \
        [get_bd_pins proc_sys_reset_0/slowest_sync_clk] [get_bd_pins v_axi4s_vid_out_0/vid_io_out_clk] \
        [get_bd_pins v_tc_0/clk] [get_bd_pins rgb2dvi_0/PixelClk]
    connect_bd_net [get_bd_pins clk_wiz_0/locked] [get_bd_pins proc_sys_reset_0/dcm_locked]
    connect_bd_net [get_bd_pins proc_sys_reset_0/peripheral_aresetn] [get_bd_pins v_tc_0/resetn]
    connect_bd_net [get_bd_pins proc_sys_reset_0/peripheral_reset] \
        [get_bd_pins v_axi4s_vid_out_0/vid_io_out_reset] [get_bd_pins rgb2dvi_0/aRst]
    connect_bd_net [get_bd_pins clk_en/dout] \
        [get_bd_pins v_axi4s_vid_out_0/aclken] [get_bd_pins v_axi4s_vid_out_0/vid_io_out_ce] \
        [get_bd_pins v_tc_0/clken] [get_bd_pins v_tc_0/gen_clken]
    connect_bd_net [get_bd_pins clk_en1/dout] [get_bd_pins v_axi4s_vid_out_0/fid]
    foreach {pin rgb} {vid_active_video vid_pVDE vid_data vid_pData vid_hsync vid_pHSync vid_vsync vid_pVSync} {
        connect_bd_net [get_bd_pins v_axi4s_vid_out_0/$pin] [get_bd_pins rgb2dvi_0/$rgb]
    }
    # In0 is bit 0 of the 16-bit fabric IRQ bus (PS interrupt ID 61).
    connect_bd_net [get_bd_pins gpgpu_axi_0/irq] [get_bd_pins irq_concat/In0]
    connect_bd_net [get_bd_pins irq_zero/dout] [get_bd_pins irq_concat/In1]
    connect_bd_net [get_bd_pins irq_concat/dout] [get_bd_pins processing_system7_0/IRQ_F2P]
    foreach signal {idle running} {
        connect_bd_net [get_bd_pins gpgpu_axi_0/o_core_$signal] [get_bd_ports o_core_${signal}_0]
    }

    # The GPGPU CSR aperture is configuration-owned (configure_block_design).
    # Both DDR masters see the PS DDR identity-mapped, each through its port.
    assign_bd_address -offset 0x83000000 -range 0x00010000 \
        -target_address_space [get_bd_addr_spaces processing_system7_0/Data] \
        [get_bd_addr_segs axi_vdma_0/S_AXI_LITE/Reg] -force
    foreach {space segment} {
        gpgpu_axi_0/m00_axi processing_system7_0/S_AXI_HP0/HP0_DDR_LOWOCM
        axi_vdma_0/Data_MM2S processing_system7_0/S_AXI_HP2/HP2_DDR_LOWOCM
    } {
        assign_bd_address -offset 0x00000000 -range 0x20000000 \
            -target_address_space [get_bd_addr_spaces $space] [get_bd_addr_segs $segment] -force
    }
}
