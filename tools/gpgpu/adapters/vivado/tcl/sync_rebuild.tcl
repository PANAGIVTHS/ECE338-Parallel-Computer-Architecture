# Rebuild a committed BD script in a throwaway project, with no overlay: fidelity check only.
lassign $argv script bd_name ip_repo part outdir
create_project -force rt $outdir -part $part
set_property ip_repo_paths [list $ip_repo] [current_project]
update_ip_catalog
source $script
cr_bd_${bd_name} ""
set bd [get_files ${bd_name}.bd]
open_bd_design $bd
validate_bd_design -force
save_bd_design
puts "GPGPU_REBUILT $bd"
close_project
