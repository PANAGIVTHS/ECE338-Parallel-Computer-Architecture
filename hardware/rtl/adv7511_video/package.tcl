# Packages src/adv7511_video.v as user.org:user:adv7511_video:1.0 in this
# directory (component.xml and xgui/), which the build publishes into the IP
# repository like the other vendor IP (hardware.vivado.vendor_ip). Rerun it
# after changing the RTL or its ports, and commit the result:
#
#   vivado -mode batch -nojournal -nolog -source hardware/rtl/adv7511_video/package.tcl
if {[version -short] ne "2025.2"} { error "This IP is packaged with Vivado 2025.2" }
set root [file normalize [file dirname [info script]]]
set source [file join $root src adv7511_video.v]

create_project -in_memory -part xc7z020clg484-1
add_files -norecurse $source
set_property top adv7511_video [current_fileset]
update_compile_order -fileset sources_1

# Files stay where they are (src/), referenced relative to component.xml.
ipx::package_project -root_dir $root -vendor user.org -library user -taxonomy /UserIP \
    -import_files false -set_current true -force
set core [ipx::current_core]
set_property -dict [list \
    name adv7511_video \
    version 1.0 \
    display_name {ADV7511 16-bit YCbCr 4:2:2 video output} \
    description {RGB video to the 16-bit YCbCr 4:2:2 input of an ADV7511 HDMI transmitter (ZedBoard)} \
    supported_families {zynq Production}] $core
ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::check_integrity $core
ipx::save_core $core
puts "INFO: packaged [get_property vlnv $core] in $root"
