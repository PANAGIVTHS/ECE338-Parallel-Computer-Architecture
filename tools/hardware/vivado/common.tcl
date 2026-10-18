# Runtime inputs shared by IP packaging and Zynq system stages. No workstation paths.
set SCRIPT_DIR [file normalize [file dirname [info script]]]
array set options {
    -project-dir "" -project-name "" -part "" -bd-name "" -top ""
    -rtl-dir "" -xdc-file "" -bitstream-dir "" -platform-dir ""
    -xsa-name "" -export-file "" -num-cores "" -jobs ""
    -repo-root "" -ip-repo-dir "" -axi-base "" -axi-range "" -version "" -ip-revision 1
}
foreach {key value} $argv {
    if {![info exists options($key)] || $value eq ""} {error "Invalid/missing Vivado argument: $key"}
    set options($key) $value
}
foreach key [array names options] {
    if {$options($key) eq ""} {error "Required Vivado argument missing: $key"}
}
foreach {key name} {
    -project-dir PROJECT_DIR -project-name PROJECT_NAME -part FPGA_PART
    -bd-name BD_NAME -top TOP_NAME -rtl-dir RTL_DIR -xdc-file XDC_FILE
    -bitstream-dir BITSTREAM_DIR -platform-dir PLATFORM_DIR -xsa-name XSA_NAME
    -export-file EXPORT_FILE -num-cores NUM_CORES -jobs JOBS -repo-root REPO_ROOT
    -ip-repo-dir IP_REPO_DIR -axi-base AXI_BASE -axi-range AXI_RANGE -version FLOW_VERSION
    -ip-revision IP_REVISION
} {set $name $options($key)}
foreach name {PROJECT_DIR RTL_DIR XDC_FILE BITSTREAM_DIR PLATFORM_DIR EXPORT_FILE REPO_ROOT IP_REPO_DIR} {
    set $name [file normalize [set $name]]
}
set PROJECT_FILE [file join $PROJECT_DIR "$PROJECT_NAME.xpr"]
foreach name {NUM_CORES JOBS IP_REVISION} {
    if {![string is integer -strict [set $name]] || [set $name] < 1} {error "$name must be positive"}
}
foreach name {AXI_BASE AXI_RANGE} {
    if {![regexp {^0[xX][0-9a-fA-F]{1,8}$} [set $name]]} {error "Invalid $name"}
}
if {$AXI_RANGE != 0x10000 || $AXI_BASE % $AXI_RANGE != 0 || $AXI_BASE + $AXI_RANGE > 0x100000000} {
    error "GPGPU AXI aperture must be 64 KiB with an aligned 32-bit base"
}
if {[string first $FLOW_VERSION [version -short]] != 0} {
    error "Vivado $FLOW_VERSION required; running [version -short]"
}
