# Owns the complete catalog -> BD -> products -> wrapper system stage.
# The Python action guards managed/protected paths and saved-BD JSON before launch.
set system_script_dir [file normalize [file dirname [info script]]]
source [file join $system_script_dir common.tcl]
source [file join $system_script_dir configure_block_design.tcl]
source [file join $system_script_dir create_block_design.tcl]

proc assert_system_bd_cells {} {
    foreach {name vlnv} {
        processing_system7_0 xilinx.com:ip:processing_system7:5.5
        gpgpu_axi_0 user.org:user:gpgpu_axi:1.0
        axi_smc xilinx.com:ip:smartconnect:1.0
        irq_concat xilinx.com:ip:xlconcat:2.1
        irq_zero xilinx.com:ip:xlconstant:1.1
        reset_locked xilinx.com:ip:xlconstant:1.1
    } {
        set cell [get_bd_cells -quiet $name]
        if {[llength $cell] != 1 || [get_property VLNV $cell] ne $vlnv} {
            error "Expected cell $name with VLNV $vlnv; refusing saved design mutation"
        }
    }
    # The reset instance may have a user-chosen name in saved GUI state.
    set resets [get_bd_cells -quiet -hierarchical -filter {VLNV == xilinx.com:ip:proc_sys_reset:5.0}]
    if {[llength $resets] != 1} {
        error "Expected exactly one proc_sys_reset cell; refusing saved design mutation"
    }
    foreach pattern {GPGPU_0 axi_gpio*} {
        if {[llength [get_bd_cells -quiet $pattern]]} {
            error "Obsolete GPIO/module-reference host interface ($pattern); explicit migration required"
        }
    }
}

if {[version -short] ne "2025.2"} { error "This system requires Vivado 2025.2" }
if {$TOP_NAME ne "${BD_NAME}_wrapper"} { error "Top must be ${BD_NAME}_wrapper" }
if {![file isfile $XDC_FILE]} { error "Constraint file does not exist: $XDC_FILE" }
set existing_project [file isfile $PROJECT_FILE]
if {$existing_project} {
    open_project $PROJECT_FILE
    if {[get_property PART [current_project]] ne $FPGA_PART} {
        error "Saved project part does not match configured FPGA part"
    }
} else {
    # Never overwrite a project or delete generated state.
    create_project $PROJECT_NAME $PROJECT_DIR -part $FPGA_PART
    set_property target_language Verilog [current_project]
    set_property simulator_language Mixed [current_project]
    set_property default_lib xil_defaultlib [current_project]
}

# This must precede both open_bd_design and create_bd_design.
set_property ip_repo_paths [list $IP_REPO_DIR] [current_project]
update_ip_catalog
foreach vlnv {
    user.org:user:gpgpu_axi:1.0
    xilinx.com:ip:processing_system7:5.5
    xilinx.com:ip:smartconnect:1.0
    xilinx.com:ip:proc_sys_reset:5.0
    xilinx.com:ip:xlconcat:2.1
    xilinx.com:ip:xlconstant:1.1
} {
    if {[llength [get_ipdefs -all -quiet $vlnv]] == 0} {
        error "Required IP missing from configured catalog: $vlnv"
    }
}
# upgrade_bd_cells selects the newest definition. Refuse any alternate version
# rather than silently replacing this system's exact host peripheral VLNV.
foreach definition [get_ipdefs -all -quiet user.org:user:gpgpu_axi:*] {
    if {$definition ne "user.org:user:gpgpu_axi:1.0"} {
        error "Unexpected GPGPU catalog VLNV: $definition; only user.org:user:gpgpu_axi:1.0 is supported"
    }
}
set bd_files [get_files -quiet *.bd]
set bd_file [get_files -quiet ${BD_NAME}.bd]
if {$existing_project} {
    if {[llength $bd_files] != 1 || [llength $bd_file] != 1} {
        error "Expected exactly one saved ${BD_NAME}.bd; refusing to bootstrap over existing project"
    }
    open_bd_design $bd_file
    assert_system_bd_cells
    # UG835: upgrade_bd_cells refreshes configurable IP from the updated catalog,
    # including a repackaged revision. Never upgrade the entire saved design.
    upgrade_bd_cells [get_bd_cells gpgpu_axi_0]
    assert_system_bd_cells
} else {
    if {[llength $bd_files]} { error "Unexpected saved BD in new project" }
    create_block_design
    assert_system_bd_cells
    set bd_file [get_files -quiet ${BD_NAME}.bd]
}
configure_block_design
validate_bd_design
save_bd_design
if {[llength $bd_file] != 1} { error "Expected generated ${BD_NAME}.bd" }
generate_target all $bd_file
set wrappers [make_wrapper -files $bd_file -top]
if {[llength $wrappers] != 1} { error "Expected exactly one generated HDL wrapper" }
if {[llength [get_files -quiet [lindex $wrappers 0]]] == 0} {
    add_files -norecurse $wrappers
}
if {[llength [get_files -quiet $XDC_FILE]] == 0} {
    add_files -fileset constrs_1 -norecurse $XDC_FILE
}
set_property top $TOP_NAME [get_filesets sources_1]
update_compile_order -fileset sources_1
close_project
puts "INFO: AXI system products and $TOP_NAME are ready: $PROJECT_FILE"
