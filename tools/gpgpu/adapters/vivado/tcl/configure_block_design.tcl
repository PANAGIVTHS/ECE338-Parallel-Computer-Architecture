# Only architecture, the mapped aperture, the DDR windows of the AXI masters and
# the fabric clock (and the GPGPU's CLOCK_KHZ derived from it) are
# configuration-owned.
# All other saved GUI properties and wiring remain authoritative.
proc bd_range_bytes {value} {
    if {[string is entier -strict $value]} { return [expr {wide($value)}] }
    if {[regexp -nocase {^([0-9]+)([KMG])$} $value -> amount unit]} {
        return [expr {wide($amount) << [dict get {K 10 M 20 G 30} [string toupper $unit]]}]
    }
    error "Unrecognized BD address range: $value"
}

proc configure_block_design {} {
    global NUM_CORES AXI_BASE AXI_RANGE DDR_BYTES FCLK0_MHZ
    set gpgpu [get_bd_cells -quiet gpgpu_axi_0]
    if {[llength $gpgpu] != 1 || [get_property VLNV $gpgpu] ne "user.org:user:gpgpu_axi:1.0"} {
        error "Expected gpgpu_axi_0 with VLNV user.org:user:gpgpu_axi:1.0"
    }
    # Resolve the entire address contract before making any configuration changes.
    set space [get_bd_addr_spaces -quiet processing_system7_0/Data]
    set segment [get_bd_addr_segs -quiet gpgpu_axi_0/s00_axi/reg0]
    if {[llength $space] != 1 || [llength $segment] != 1} {
        error "Missing processing_system7_0/Data or gpgpu_axi_0/s00_axi/reg0"
    }
    set mapped [get_bd_addr_segs -quiet ${space}/SEG_gpgpu_axi_0_reg0]
    set changed 0
    if {[get_property CONFIG.SP_PER_SM $gpgpu] ne $NUM_CORES} {
        set_property CONFIG.SP_PER_SM $NUM_CORES $gpgpu
        set changed 1
    }
    # FCLK_CLK0 clocks the GPGPU, its AXI interconnect and reset (requested
    # value; the PS derives the nearest achievable frequency from its dividers).
    set ps [get_bd_cells -quiet processing_system7_0]
    if {[llength $ps] != 1} {error "Missing processing_system7_0"}
    set fclk [get_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ $ps]
    if {![string is double -strict $fclk] || $fclk != $FCLK0_MHZ} {
        set_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ $FCLK0_MHZ $ps
        set changed 1
    }
    # INFO_CLOCK reports the frequency the PS dividers actually produce, which
    # may differ from the requested one.
    set achieved [get_property CONFIG.PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ $ps]
    if {![string is double -strict $achieved] || $achieved <= 0} {
        error "Missing achieved FCLK_CLK0 frequency (PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ): $achieved"
    }
    set clock_khz [expr {round($achieved * 1000.0)}]
    if {[get_property CONFIG.CLOCK_KHZ $gpgpu] ne $clock_khz} {
        set_property CONFIG.CLOCK_KHZ $clock_khz $gpgpu
        set changed 1
    }
    # architecture.memory.ddr_bytes must be the PS's DDR, which comes from the
    # board's DDR part, not from the configuration.
    set ddr_high [get_property CONFIG.PCW_DDR_RAM_HIGHADDR $ps]
    if {[expr {wide($ddr_high) + 1}] != [bd_range_bytes $DDR_BYTES]} {
        error "architecture.memory.ddr_bytes ($DDR_BYTES) is not the PS's DDR (PCW_DDR_RAM_HIGHADDR $ddr_high)"
    }
    # The GPGPU (HP0) and the display's VDMA (HP2) reach all of DDR from 0:
    # the framebuffers and GMEM of the DDR map lie anywhere in it.
    foreach {master slave} {
        gpgpu_axi_0/m00_axi processing_system7_0/S_AXI_HP0/HP0_DDR_LOWOCM
        axi_vdma_0/Data_MM2S processing_system7_0/S_AXI_HP2/HP2_DDR_LOWOCM
    } {
        set master_space [get_bd_addr_spaces -quiet $master]
        set slave_segment [get_bd_addr_segs -quiet $slave]
        if {[llength $master_space] != 1 || [llength $slave_segment] != 1} {error "Missing $master or $slave"}
        set window [get_bd_addr_segs -quiet ${master_space}/SEG_processing_system7_0_[lindex [split $slave /] end]]
        if {[llength $window] != 1 || [bd_range_bytes [get_property OFFSET $window]] != 0 ||
            [bd_range_bytes [get_property RANGE $window]] != [bd_range_bytes $DDR_BYTES]} {
            assign_bd_address -offset 0x00000000 -range $DDR_BYTES -target_address_space $master_space $slave_segment -force
            set changed 1
        }
    }
    if {[llength $mapped] != 1 ||
        [bd_range_bytes [get_property OFFSET $mapped]] != [bd_range_bytes $AXI_BASE] ||
        [bd_range_bytes [get_property RANGE $mapped]] != [bd_range_bytes $AXI_RANGE]} {
        assign_bd_address -offset $AXI_BASE -range $AXI_RANGE \
            -with_name SEG_gpgpu_axi_0_reg0 -target_address_space $space $segment -force
        set changed 1
    }
    return $changed
}
