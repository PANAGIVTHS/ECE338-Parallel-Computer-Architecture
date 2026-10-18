# Production customization: SP_PER_SM is user-owned; AXI widths are fixed at 32.
proc init_gui {IPINST} {
    ipgui::add_param $IPINST -name Component_Name
    set page [ipgui::add_page $IPINST -name Configuration]
    ipgui::add_param $IPINST -name SP_PER_SM -parent $page
}
proc validate_PARAM_VALUE.SP_PER_SM {PARAM_VALUE.SP_PER_SM} {
    set value [get_property value ${PARAM_VALUE.SP_PER_SM}]
    return [expr {[string is integer -strict $value] && $value > 0}]
}
proc update_PARAM_VALUE.SP_PER_SM {PARAM_VALUE.SP_PER_SM} {}
proc update_MODELPARAM_VALUE.SP_PER_SM {MODELPARAM_VALUE.SP_PER_SM PARAM_VALUE.SP_PER_SM} {
    set_property value [get_property value ${PARAM_VALUE.SP_PER_SM}] ${MODELPARAM_VALUE.SP_PER_SM}
}
proc update_MODELPARAM_VALUE.C_S00_AXI_DATA_WIDTH {MODELPARAM_VALUE.C_S00_AXI_DATA_WIDTH PARAM_VALUE.C_S00_AXI_DATA_WIDTH} {
    set_property value [get_property value ${PARAM_VALUE.C_S00_AXI_DATA_WIDTH}] ${MODELPARAM_VALUE.C_S00_AXI_DATA_WIDTH}
}
proc update_MODELPARAM_VALUE.C_S00_AXI_ADDR_WIDTH {MODELPARAM_VALUE.C_S00_AXI_ADDR_WIDTH PARAM_VALUE.C_S00_AXI_ADDR_WIDTH} {
    set_property value [get_property value ${PARAM_VALUE.C_S00_AXI_ADDR_WIDTH}] ${MODELPARAM_VALUE.C_S00_AXI_ADDR_WIDTH}
}
