# Only architecture and the mapped aperture are configuration-owned.
# All other saved GUI properties and wiring remain authoritative.
proc bd_range_bytes {value} {
    if {[string is entier -strict $value]} { return [expr {wide($value)}] }
    if {[regexp -nocase {^([0-9]+)([KMG])$} $value -> amount unit]} {
        return [expr {wide($amount) << [dict get {K 10 M 20 G 30} [string toupper $unit]]}]
    }
    error "Unrecognized BD address range: $value"
}

proc configure_block_design {} {
    global NUM_CORES AXI_BASE AXI_RANGE
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
    if {[llength $mapped] != 1 ||
        [bd_range_bytes [get_property OFFSET $mapped]] != [bd_range_bytes $AXI_BASE] ||
        [bd_range_bytes [get_property RANGE $mapped]] != [bd_range_bytes $AXI_RANGE]} {
        assign_bd_address -offset $AXI_BASE -range $AXI_RANGE \
            -with_name SEG_gpgpu_axi_0_reg0 -target_address_space $space $segment -force
        set changed 1
    }
    return $changed
}
