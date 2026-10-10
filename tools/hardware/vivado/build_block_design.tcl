# Reuse the saved GUI design; bootstrap from the portable template only if absent.
source [file join [file dirname [info script]] "common.tcl"]
source [file join $SCRIPT_DIR "configure_block_design.tcl"]
open_project $PROJECT_FILE
set bd_file [get_files -quiet "${BD_NAME}.bd"]
set bootstrapped 0
if {[llength $bd_file] == 0} {
    set other_designs [get_files -quiet "*.bd"]
    if {[llength $other_designs] > 0} {
        error "Configured ${BD_NAME}.bd is missing; found: $other_designs. Refusing to replace saved designs."
    }
    source [file join $SCRIPT_DIR "create_block_design.tcl"]
    set bootstrapped 1
    set bd_file [get_files -quiet "${BD_NAME}.bd"]
}
if {[llength $bd_file] != 1} {
    error "Expected exactly one block design named ${BD_NAME}.bd"
}
set ip_repo_path [file normalize "$RTL_DIR"]
set_property ip_repo_paths [list $ip_repo_path] [current_project]
update_ip_catalog -rebuild

open_bd_design $bd_file
set changed [configure_block_design]
validate_bd_design
if {$bootstrapped || $changed} {
    save_bd_design
}
close_project
puts "INFO: Built/configured block design: $bd_file"
