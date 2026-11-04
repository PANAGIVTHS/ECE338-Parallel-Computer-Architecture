# Production customization: SP_PER_SM and CLOCK_KHZ are set by the block design;
# INTERFACE_VERSION, BUILD_HASH, BUILD_DIRTY and DDR_ENABLE are fixed at
# packaging; AXI widths are fixed at 32.
proc init_gui {IPINST} {
    ipgui::add_param $IPINST -name Component_Name
    set page [ipgui::add_page $IPINST -name Configuration]
    ipgui::add_param $IPINST -name SP_PER_SM -parent $page
    ipgui::add_param $IPINST -name CLOCK_KHZ -parent $page
}
proc validate_PARAM_VALUE.SP_PER_SM {PARAM_VALUE.SP_PER_SM} {
    set value [get_property value ${PARAM_VALUE.SP_PER_SM}]
    if {[string is integer -strict $value] && $value > 0} {
        return true
    }
    return false
}
proc update_PARAM_VALUE.SP_PER_SM {PARAM_VALUE.SP_PER_SM} {}
proc update_MODELPARAM_VALUE.SP_PER_SM {MODELPARAM_VALUE.SP_PER_SM PARAM_VALUE.SP_PER_SM} {
    set_property value [get_property value ${PARAM_VALUE.SP_PER_SM}] ${MODELPARAM_VALUE.SP_PER_SM}
}
proc validate_PARAM_VALUE.CLOCK_KHZ {PARAM_VALUE.CLOCK_KHZ} {
    set value [get_property value ${PARAM_VALUE.CLOCK_KHZ}]
    if {[string is integer -strict $value] && $value > 0} {
        return true
    }
    return false
}
proc update_PARAM_VALUE.CLOCK_KHZ {PARAM_VALUE.CLOCK_KHZ} {}
proc update_MODELPARAM_VALUE.CLOCK_KHZ {MODELPARAM_VALUE.CLOCK_KHZ PARAM_VALUE.CLOCK_KHZ} {
    set_property value [get_property value ${PARAM_VALUE.CLOCK_KHZ}] ${MODELPARAM_VALUE.CLOCK_KHZ}
}
proc update_MODELPARAM_VALUE.BUILD_HASH {MODELPARAM_VALUE.BUILD_HASH PARAM_VALUE.BUILD_HASH} {
    set_property value [get_property value ${PARAM_VALUE.BUILD_HASH}] ${MODELPARAM_VALUE.BUILD_HASH}
}
proc update_MODELPARAM_VALUE.BUILD_DIRTY {MODELPARAM_VALUE.BUILD_DIRTY PARAM_VALUE.BUILD_DIRTY} {
    set_property value [get_property value ${PARAM_VALUE.BUILD_DIRTY}] ${MODELPARAM_VALUE.BUILD_DIRTY}
}
proc update_MODELPARAM_VALUE.DDR_ENABLE {MODELPARAM_VALUE.DDR_ENABLE PARAM_VALUE.DDR_ENABLE} {
    set_property value [get_property value ${PARAM_VALUE.DDR_ENABLE}] ${MODELPARAM_VALUE.DDR_ENABLE}
}
proc update_MODELPARAM_VALUE.INTERFACE_VERSION {MODELPARAM_VALUE.INTERFACE_VERSION PARAM_VALUE.INTERFACE_VERSION} {
    set_property value [get_property value ${PARAM_VALUE.INTERFACE_VERSION}] ${MODELPARAM_VALUE.INTERFACE_VERSION}
}
proc update_MODELPARAM_VALUE.C_S00_AXI_DATA_WIDTH {MODELPARAM_VALUE.C_S00_AXI_DATA_WIDTH PARAM_VALUE.C_S00_AXI_DATA_WIDTH} {
    set_property value [get_property value ${PARAM_VALUE.C_S00_AXI_DATA_WIDTH}] ${MODELPARAM_VALUE.C_S00_AXI_DATA_WIDTH}
}
proc update_MODELPARAM_VALUE.C_S00_AXI_ADDR_WIDTH {MODELPARAM_VALUE.C_S00_AXI_ADDR_WIDTH PARAM_VALUE.C_S00_AXI_ADDR_WIDTH} {
    set_property value [get_property value ${PARAM_VALUE.C_S00_AXI_ADDR_WIDTH}] ${MODELPARAM_VALUE.C_S00_AXI_ADDR_WIDTH}
}
