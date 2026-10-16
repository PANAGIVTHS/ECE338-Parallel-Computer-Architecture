# Package ONLY the project created by create_ip_project.tcl into fresh staging.
# Reference development projects/component.xml are never opened or imported.
# ipx::package_project/import, infer/associate and checksum APIs are demonstrated
# in AMD Vitis-Tutorials 2025.2 rtlpacker_generic.tcl and counter/pack_kernel.tcl.
set flow_dir [file normalize [file dirname [info script]]]
source [file join $flow_dir common.tcl]
source [file join $flow_dir production_sources.tcl]

if {$FLOW_VERSION ne "2025.2" || [version -short] ne "2025.2"} {
    error "Production IP packaging requires Vivado 2025.2"
}
if {$TOP_NAME ne "gpgpu_axi"} {error "Production IP top must be gpgpu_axi"}
if {[file exists $IP_REPO_DIR] && [llength [glob -nocomplain -directory $IP_REPO_DIR * .*]] > 2} {
    error "IP package destination must be empty staging: $IP_REPO_DIR"
}
if {![file isfile $PROJECT_FILE]} {error "Missing production IP project: $PROJECT_FILE"}
set marker_file [file join $PROJECT_DIR .production-ip-project]
if {![file isfile $marker_file]} {error "Not a CLI-created production IP project: $PROJECT_DIR"}
set marker [open $marker_file r]
set identity [string trim [read $marker]]
close $marker
if {$identity ne "gpgpu_axi production project v1"} {error "Invalid production IP project marker"}
set inputs [production_source_paths $RTL_DIR $flow_dir]
foreach input $inputs {
    if {![file isfile [file join $PROJECT_DIR src [file tail $input]]]} {
        error "Missing staged production source: [file tail $input]"
    }
}
open_project $PROJECT_FILE
ipx::package_project -root_dir $IP_REPO_DIR -vendor user.org -library user -taxonomy /UserIP -import_files -set_current true
set core [ipx::current_core]
set_property name gpgpu_axi $core
set_property version 1.0 $core
set_property display_name {GPGPU AXI4-Lite} $core
set_property description {Production GPGPU peripheral: 32-bit AXI4-Lite, 64-KiB decoded aperture} $core
set_property core_revision $IP_REVISION $core

# Pin names are lowercase in the public contract; fail rather than guess aliases.
foreach {name bus} {
    s00_axi xilinx.com:interface:aximm_rtl:1.0
    s00_axi_aclk xilinx.com:signal:clock_rtl:1.0
    s00_axi_aresetn xilinx.com:signal:reset_rtl:1.0
    irq xilinx.com:signal:interrupt_rtl:1.0
} {
    if {[llength [ipx::get_bus_interfaces $name -of_objects $core]] == 0} {
        ipx::infer_bus_interface $name $bus $core
    }
    if {[llength [ipx::get_bus_interfaces $name -of_objects $core]] != 1} {
        error "Required packaged interface not inferred: $name"
    }
}
ipx::associate_bus_interfaces -busif s00_axi -clock s00_axi_aclk $core
ipx::associate_bus_interfaces -clock s00_axi_aclk -reset s00_axi_aresetn $core
proc set_ip_bus_parameter {core bus name value} {
    set interface [ipx::get_bus_interfaces $bus -of_objects $core]
    set parameter [ipx::get_bus_parameters $name -of_objects $interface]
    if {[llength $parameter] == 0} {set parameter [ipx::add_bus_parameter $name $interface]}
    set_property value $value $parameter
}
set_ip_bus_parameter $core s00_axi PROTOCOL AXI4LITE
set_ip_bus_parameter $core s00_axi DATA_WIDTH 32
set_ip_bus_parameter $core s00_axi ADDR_WIDTH 32
set_ip_bus_parameter $core s00_axi_aclk ASSOCIATED_BUSIF s00_axi
set_ip_bus_parameter $core s00_axi_aclk ASSOCIATED_RESET s00_axi_aresetn
set_ip_bus_parameter $core s00_axi_aresetn POLARITY ACTIVE_LOW
set_ip_bus_parameter $core irq SENSITIVITY LEVEL_HIGH

# MMIOController decodes CSR, IMEM 0x2000..0x3fff, DMEM 0x4000..0x5fff.
# 32 address wires do NOT imply a 4-GiB peripheral aperture.
set memory_map [ipx::get_memory_maps s00_axi -of_objects $core]
if {[llength $memory_map] == 0} {set memory_map [ipx::add_memory_map s00_axi $core]}
set block [ipx::get_address_blocks reg0 -of_objects $memory_map]
if {[llength $block] == 0} {set block [ipx::add_address_block reg0 $memory_map]}
set_property slave_memory_map_ref s00_axi [ipx::get_bus_interfaces s00_axi -of_objects $core]
set_property base_address 0 $block
set_property range 65536 $block
set_property range_resolve_type immediate $block
set_property range_dependency {} $block
set_property width 32 $block
set_property usage register $block

foreach {name value} [list SP_PER_SM $NUM_CORES C_S00_AXI_DATA_WIDTH 32 C_S00_AXI_ADDR_WIDTH 32] {
    set user [ipx::get_user_parameters $name -of_objects $core]
    if {[llength $user] == 0} {set user [ipx::add_user_parameter $name $core]}
    set_property value $value $user
    set_property value_format long $user
    set_property value_resolve_type user $user
    if {$name ne "SP_PER_SM"} {set_property enablement_value false $user}
    set model [ipx::get_hdl_parameters $name -of_objects $core]
    if {[llength $model] != 1} {error "Required HDL parameter missing: $name"}
    set_property value $value $model
    set_property value_resolve_type generated $model
    set_property value_dependency "spirit:decode(id('PARAM_VALUE.$name'))" $model
}

# Explicitly normalize both imported filesets. This avoids vendor compile-order
# inference including headers as modules or placing SV interfaces after users.
file mkdir [file join $IP_REPO_DIR src]
set package_files {}
foreach input $inputs {
    set relative "src/[file tail $input]"
    if {![file exists [file join $IP_REPO_DIR $relative]]} {
        file copy [file join $PROJECT_DIR src [file tail $input]] [file join $IP_REPO_DIR $relative]
    }
    lappend package_files $relative
}
foreach group_name {xilinx_anylanguagesynthesis_view_fileset xilinx_anylanguagebehavioralsimulation_view_fileset} {
    set group [ipx::get_file_groups $group_name -of_objects $core]
    if {[llength $group] != 1} {error "Missing packaged HDL fileset: $group_name"}
    foreach old [ipx::get_files -of_objects $group] {
        ipx::remove_file [get_property name $old] $group
    }
    foreach relative $package_files {
        set entry [ipx::add_file $relative $group]
        if {[file tail $relative] eq "empty.mem"} {
            set_property type mif $entry
        } else {
            set_property type systemVerilogSource $entry
        }
        if {[file tail $relative] eq "constants.svh"} {
            set_property is_include true $entry
        }
    }
}
ipx::create_xgui_files $core
file mkdir [file join $IP_REPO_DIR xgui]
file copy -force [file join $flow_dir ip xgui gpgpu_axi_v1_0.tcl] [file join $IP_REPO_DIR xgui gpgpu_axi_v1_0.tcl]
ipx::update_checksums $core
ipx::check_integrity $core
ipx::save_core $core
close_project
# The Python caller validates component.xml and all local source paths, then
# publishes atomically. This script must never replace a live IP repository.
