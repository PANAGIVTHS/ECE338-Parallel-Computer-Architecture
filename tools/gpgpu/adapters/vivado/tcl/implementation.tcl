# Run implementation through routing (and post-route phys_opt when configured).
# Bitstream generation is a later stage.

source [file join [file dirname [info script]] "common.tcl"]
set_param general.maxThreads $JOBS
open_project $PROJECT_FILE

# Configuration-owned: applied on every run so disabling it also takes effect.
set impl_run [get_runs impl_1]
reset_run impl_1
set_property STEPS.POST_ROUTE_PHYS_OPT_DESIGN.IS_ENABLED $POST_ROUTE_PHYS_OPT $impl_run
set_property STEPS.POST_ROUTE_PHYS_OPT_DESIGN.ARGS.DIRECTIVE $POST_ROUTE_PHYS_OPT_DIRECTIVE $impl_run
# Without -to_step the run executes every enabled step before write_bitstream
# (-to_step has no name for the post-route phys_opt step).
launch_runs impl_1 -jobs $JOBS
wait_on_run impl_1

set run_dir [file join $PROJECT_DIR "$PROJECT_NAME.runs" "impl_1"]
set checkpoints [list [file join $run_dir "${TOP_NAME}_routed.dcp"]]
if {$POST_ROUTE_PHYS_OPT} {
    lappend checkpoints [file join $run_dir "${TOP_NAME}_postroute_physopt.dcp"]
}
foreach checkpoint $checkpoints {
    if {![file isfile $checkpoint]} {
        error "Implementation did not produce the checkpoint: $checkpoint"
    }
}

close_project
puts "INFO: Implementation completed successfully: [lindex $checkpoints end]"
