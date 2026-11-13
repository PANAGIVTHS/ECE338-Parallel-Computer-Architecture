# Replace the project's BD from the committed script, then apply the config overlay.
lassign $argv xpr script overlay bd_name top NUM_CORES AXI_BASE AXI_RANGE FCLK0_MHZ
open_project $xpr
update_ip_catalog
source $overlay
set old [get_files ${bd_name}.bd]
set folder [file dirname $old]
set wrappers [get_files -quiet ${top}.v]
if {[llength $wrappers]} {remove_files $wrappers}
remove_files $old
file delete -force $folder
file delete -force [file join [get_property DIRECTORY [current_project]] "[get_property NAME [current_project]].gen" sources_1 bd $bd_name]
source $script
cr_bd_${bd_name} ""
set bd [get_files ${bd_name}.bd]
open_bd_design $bd
configure_block_design
validate_bd_design
save_bd_design
generate_target all $bd
set wrapper [make_wrapper -files $bd -top]
add_files -norecurse $wrapper
set_property top $top [get_filesets sources_1]
update_compile_order -fileset sources_1
close_project
puts "GPGPU_PUSHED $bd"
