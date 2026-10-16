# Optional explicit inspection/export helper, never a build dependency.
# The caller must use a safe copy or a managed system, not a reference project.
source [file join [file dirname [info script]] "common.tcl"]
if {![file isfile $PROJECT_FILE]} {error "System project does not exist; run vivado:system:create"}
open_project $PROJECT_FILE
set bd_file [get_files -quiet "${BD_NAME}.bd"]
if {[llength $bd_file] != 1} {error "Expected exactly one ${BD_NAME}.bd"}
open_bd_design $bd_file
set cell [get_bd_cells -quiet gpgpu_axi_0]
if {[llength $cell] != 1 || [get_property VLNV $cell] ne "user.org:user:gpgpu_axi:1.0"} {
    error "Refusing export: not the packaged GPGPU AXI system"
}
if {[llength [get_bd_cells -quiet axi_gpio*]] != 0} {error "Refusing legacy GPIO export"}
foreach port {o_core_idle_0 o_core_running_0} {
    if {[llength [get_bd_ports -quiet $port]] != 1} {error "Missing system port $port"}
}
if {[llength [get_bd_addr_segs -quiet gpgpu_axi_0/s00_axi/reg0]] != 1} {error "Missing GPGPU address segment"}
validate_bd_design
file mkdir [file dirname $EXPORT_FILE]
write_bd_tcl -force $EXPORT_FILE
close_project
