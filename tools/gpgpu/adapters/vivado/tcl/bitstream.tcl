# Continue the implemented run through bitstream generation and publish the .bit file.

source [file join [file dirname [info script]] "common.tcl"]
set_param general.maxThreads $JOBS
open_project $PROJECT_FILE

# A failed or previously completed bitstream step must be reset before retrying.
# Reset only write_bitstream and preserve the routed implementation checkpoint.
reset_run impl_1 -from_step write_bitstream
launch_runs impl_1 -to_step write_bitstream -jobs $JOBS
wait_on_run impl_1

set generated_bitstream [file join \
    $PROJECT_DIR \
    "$PROJECT_NAME.runs" \
    "impl_1" \
    "${TOP_NAME}.bit"]
if {![file isfile $generated_bitstream]} {
    error "Vivado did not produce the expected bitstream: $generated_bitstream"
}

file mkdir $BITSTREAM_DIR
set output_bitstream [file join $BITSTREAM_DIR "${TOP_NAME}.bit"]
file copy -force $generated_bitstream $output_bitstream

close_project
puts "INFO: Bitstream generated: $output_bitstream"
