# Export the block design as a script: what `gpgpu project pull` proposes to commit.
# First bring the design up to date, as a build does: a GUI save need not have validated it,
# and write_bd_tcl marks a design whose IP was repackaged as unusable.
lassign $argv xpr bd_name out
open_project $xpr
update_ip_catalog
open_bd_design [get_files ${bd_name}.bd]
upgrade_bd_cells [get_bd_cells gpgpu_axi_0]
validate_bd_design
save_bd_design
write_bd_tcl -force -no_project_wrapper -exclude_layout $out
close_project
