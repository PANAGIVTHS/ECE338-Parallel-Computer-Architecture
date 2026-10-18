# Portable production IP development project; caller owns disposable build roots.
set flow_dir [file normalize [file dirname [info script]]]
source [file join $flow_dir common.tcl]
source [file join $flow_dir production_sources.tcl]

if {$FLOW_VERSION ne "2025.2" || [version -short] ne "2025.2"} {
    error "Production IP packaging requires Vivado 2025.2"
}
if {$TOP_NAME ne "gpgpu_axi"} {error "Production IP top must be gpgpu_axi"}
if {[file exists $PROJECT_DIR]} {
    error "IP project creation requires a fresh directory, refusing: $PROJECT_DIR"
}
# Resolve every required input before creating any project or copying sources.
set inputs [production_source_paths $RTL_DIR $flow_dir]
create_project $PROJECT_NAME $PROJECT_DIR -part $FPGA_PART
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]
set_property source_mgmt_mode None [current_project]
set source_dir [file join $PROJECT_DIR src]
file mkdir $source_dir
set sources {}
foreach input $inputs {
    set output [file join $source_dir [file tail $input]]
    file copy $input $output
    lappend sources $output
}
add_files -norecurse -fileset sources_1 $sources
set_property file_type {SystemVerilog Header} [get_files [file join $source_dir constants.svh]]
set_property is_global_include true [get_files [file join $source_dir constants.svh]]
set_property file_type {Memory Initialization Files} [get_files [file join $source_dir empty.mem]]
set_property include_dirs [list $source_dir] [get_filesets sources_1]
set_property include_dirs [list $source_dir] [get_filesets sim_1]
set_property top $TOP_NAME [get_filesets sources_1]
set_property generic "SP_PER_SM=$NUM_CORES" [get_filesets sources_1]
# Manual source management retains the explicit interface-first compile order.
# No board XDC, reference component.xml, external IP repo, TB or experiments.
close_project
set marker [open [file join $PROJECT_DIR .production-ip-project] w]
puts $marker "gpgpu_axi production project v1"
close $marker
