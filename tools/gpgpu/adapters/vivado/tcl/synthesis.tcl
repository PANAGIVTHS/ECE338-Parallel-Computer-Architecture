# Run synthesis only. Project and block-design creation are separate dependencies.

source [file join [file dirname [info script]] "common.tcl"]
set_param general.maxThreads $JOBS
open_project $PROJECT_FILE

reset_run synth_1
launch_runs synth_1 -jobs $JOBS
wait_on_run synth_1

if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {
    error "synth_1 did not complete successfully: [get_property STATUS [get_runs synth_1]]"
}

close_project
puts "INFO: Synthesis completed successfully"
