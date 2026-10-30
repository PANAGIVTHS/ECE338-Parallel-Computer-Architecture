# Portable production IP development project; caller owns disposable build roots.
set flow_dir [file normalize [file dirname [info script]]]
source [file join $flow_dir common.tcl]
source [file join $flow_dir production_sources.tcl]

if {$FLOW_VERSION ne "2025.2" || [version -short] ne "2025.2"} {
    error "Production IP packaging requires Vivado 2025.2"
}
if {$TOP_NAME ne "gpgpu_axi"} {error "Production IP top must be gpgpu_axi"}
if {[file exists $PROJECT_DIR]} {
    # The Python runner creates this directory, its canonical identity marker,
    # and stage logs before launching Vivado. Existence alone is not a conflict.
    # Accept only that fresh managed layout; never adopt a saved/reference IP.
    set identity_file [file join $PROJECT_DIR .gpgpu-managed.json]
    if {![file isdirectory $PROJECT_DIR] || ![file isfile $identity_file] ||
        [file type $identity_file] ne "file"} {
        error "IP creation refuses an unmanaged directory: $PROJECT_DIR"
    }
    set identity_channel [open $identity_file r]
    set identity [string trim [read $identity_channel]]
    close $identity_channel
    # Matches prepare_managed_project's sorted schema-1 JSON without requiring
    # a third-party Tcl JSON package in the vendor interpreter.
    set expected [format {{"kind": "ip", "part": "%s", "project": "%s", "schema": 1}} $FPGA_PART $PROJECT_NAME]
    if {$identity ne $expected} {
        error "IP creation refuses an incompatible managed identity: $PROJECT_DIR"
    }
    foreach entry [glob -nocomplain -directory $PROJECT_DIR -tails * .*] {
        if {$entry in {. .. .gpgpu-managed.json}} {continue}
        set path [file join $PROJECT_DIR $entry]
        # .Xil is Vivado's own startup cache, created before the script executes.
        if {$entry in {.gpgpu .Xil} && [file isdirectory $path] && [file type $path] eq "directory"} {continue}
        error "IP creation requires fresh managed state; refusing existing entry: $path"
    }
}
# Resolve every required input before creating any project or copying sources.
lassign [read_source_manifest $SOURCES_MANIFEST] MEMORY_INIT RTL_SOURCES HEADER_SOURCES
set inputs [production_source_paths $MEMORY_INIT $RTL_SOURCES $HEADER_SOURCES]
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
# Every macro consumer includes its sibling header explicitly.
# Global-include state is not preserved by ipx::package_project.
foreach header $HEADER_SOURCES {
    set staged [get_files [file join $source_dir [file tail $header]]]
    set_property file_type {SystemVerilog Header} $staged
    set_property is_global_include false $staged
}
set_property file_type {Memory Initialization Files} [get_files [file join $source_dir [file tail $MEMORY_INIT]]]
# All staged RTL and the header share src/: no development-project include path
# may be imported as an IP-XACT dependency by the packager.
set_property include_dirs {} [get_filesets sources_1]
set_property include_dirs {} [get_filesets sim_1]
set_property top $TOP_NAME [get_filesets sources_1]
set_property generic "SP_PER_SM=$NUM_CORES" [get_filesets sources_1]
# Manual source management retains the explicit interface-first compile order.
# No board XDC, reference component.xml, external IP repo, TB or experiments.
close_project
set marker [open [file join $PROJECT_DIR .production-ip-project] w]
puts $marker "gpgpu_axi production project v1"
close $marker
