# Export the implemented hardware platform with its bitstream for later Vitis use.

source [file join [file dirname [info script]] "common.tcl"]
open_project $PROJECT_FILE

set impl_run [get_runs -quiet impl_1]
if {[llength $impl_run] != 1} {
    error "Vivado implementation run impl_1 does not exist"
}
if {[get_property PROGRESS $impl_run] ne "100%"} {
    error "Vivado implementation run impl_1 is not complete"
}

open_run impl_1
file mkdir $PLATFORM_DIR
set output_xsa [file join $PLATFORM_DIR "${XSA_NAME}.xsa"]
write_hw_platform -fixed -include_bit -force -file $output_xsa
if {![file isfile $output_xsa]} {
    error "Vivado did not produce the expected hardware platform: $output_xsa"
}

close_project
puts "INFO: Hardware platform exported with bitstream: $output_xsa"
