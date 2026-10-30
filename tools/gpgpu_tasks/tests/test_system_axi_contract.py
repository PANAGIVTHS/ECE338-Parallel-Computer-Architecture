"""Portable AXI system contracts; no reference project is opened by these tests."""
from pathlib import Path
import re
import os
import shutil
import subprocess

import pytest


def run_tcl(script):
    executable = os.environ.get("TCLSH") or shutil.which("tclsh")
    if not executable:
        pytest.skip("Tcl interpreter unavailable (set TCLSH to enable execution tests)")
    result = subprocess.run([executable], input=(
        "if {[catch {\n" + script + "\n} failure]} {puts stderr $failure; exit 1}\n"
    ), text=True, capture_output=True)
    return result


RECORDING_API = r'''
proc version {args} {return 2025.2}
proc create_bd_cell {args} {puts [list create_bd_cell {*}$args]; return [lindex $args end]}
proc set_property {args} {puts [list set_property {*}$args]}
proc get_bd_pins {args} {return [lindex $args end]}
proc get_bd_ports {args} {return [lindex $args end]}
proc get_bd_intf_ports {args} {return [lindex $args end]}
proc get_bd_intf_pins {args} {return [lindex $args end]}
foreach command {create_bd_design current_bd_design create_bd_intf_port create_bd_port connect_bd_net connect_bd_intf_net} {
    proc $command {args} {puts [list [lindex [info level 0] 0] {*}$args]}
}
'''

ROOT = Path(__file__).resolve().parents[3]
VIVADO = ROOT / "tools/hardware/vivado"


def test_bootstrap_uses_saved_ps_user_settings_not_computed_overrides():
    text = (VIVADO / "create_block_design.tcl").read_text()
    # The fabric clock is configuration-owned (hardware.vivado.fabric_clock_mhz).
    assert re.search(r"CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ\s+\$FCLK0_MHZ", text)
    assert "CONFIG.PCW_UIPARAM_DDR_PARTNO {MT41K256M16 RE-125}" in text
    assert "CONFIG.PCW_UIPARAM_DDR_BUS_WIDTH {16 Bit}" in text
    assert "CONFIG.PCW_UIPARAM_DDR_ECC {Disabled}" in text
    assert "CONFIG.PCW_UART0_UART0_IO {EMIO}" in text
    assert "CONFIG.PCW_ACT_" not in text
    assert "CONFIG.PCW_UIPARAM_ACT_" not in text
    assert "CONFIG.PCW_PERIPHERAL_BOARD_PRESET" not in text


CONFIGURATION_API = r'''
set props [dict create gpgpu_axi_0,VLNV user.org:user:gpgpu_axi:1.0 \
    gpgpu_axi_0,CONFIG.SP_PER_SM 8 mapped,OFFSET 0x43C00000 mapped,RANGE 64K \
    processing_system7_0,CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ 35]
proc get_bd_cells {args} {
    set name [lindex $args end]
    if {$name eq "GPGPU_0" || [string match "axi_gpio*" $name]} {return {}}
    if {[lsearch $args -filter] >= 0} {return rst_ps7_0_35M}
    return $name
}
proc get_property {key object} {
    global props
    if {[dict exists $props $object,$key]} {return [dict get $props $object,$key]}
    return {}
}
proc set_property {key value object} {
    global props
    dict set props $object,$key $value
    puts [list SET $key $value $object]
}
proc get_bd_addr_spaces {args} {return processing_system7_0/Data}
proc get_bd_addr_segs {args} {
    if {[lindex $args end] eq "gpgpu_axi_0/s00_axi/reg0"} {return gpgpu_axi_0/s00_axi/reg0}
    return mapped
}
proc assign_bd_address {args} {puts [list MAP {*}$args]}
'''


def test_configuration_updates_only_owned_core_and_address_settings():
    result = run_tcl(CONFIGURATION_API + f'''
set NUM_CORES 4
set AXI_BASE 0x40000000
set AXI_RANGE 0x10000
set FCLK0_MHZ 35
source {{{VIVADO / 'configure_block_design.tcl'}}}
puts [list CHANGED [configure_block_design]]
''')
    assert result.returncode == 0, result.stderr
    assert "SET CONFIG.SP_PER_SM 4 gpgpu_axi_0" in result.stdout
    assert "MAP -offset 0x40000000 -range 0x10000" in result.stdout
    assert "gpgpu_axi_0/s00_axi/reg0" in result.stdout
    assert "CHANGED 1" in result.stdout
    assert "PCW_" not in result.stdout


def test_configuration_is_noop_when_owned_values_match():
    result = run_tcl(CONFIGURATION_API + f'''
set NUM_CORES 8
set AXI_BASE 0x43C00000
set AXI_RANGE 0x10000
set FCLK0_MHZ 35.0
source {{{VIVADO / 'configure_block_design.tcl'}}}
puts [list CHANGED [configure_block_design]]
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CHANGED 0"


def test_configuration_applies_fabric_clock_to_saved_design():
    result = run_tcl(CONFIGURATION_API + f'''
set NUM_CORES 8
set AXI_BASE 0x43C00000
set AXI_RANGE 0x10000
set FCLK0_MHZ 50
source {{{VIVADO / 'configure_block_design.tcl'}}}
puts [list CHANGED [configure_block_design]]
''')
    assert result.returncode == 0, result.stderr
    assert "SET CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ 50 processing_system7_0" in result.stdout
    assert "CHANGED 1" in result.stdout
    assert "MAP" not in result.stdout and "SP_PER_SM" not in result.stdout


def system_script(tmp_path, existing=False, missing_cell=None, wrong_vlnv=False):
    for name in ("create_block_design.tcl", "configure_block_design.tcl", "create_system.tcl"):
        if (VIVADO / name).exists():
            shutil.copy(VIVADO / name, tmp_path / name)
    project = tmp_path / "generated"
    project.mkdir()
    if existing:
        (project / "system.xpr").touch()
    (tmp_path / "board.xdc").touch()
    (tmp_path / "common.tcl").write_text(f'''
set PROJECT_DIR {{{project}}}
set PROJECT_FILE {{{project / 'system.xpr'}}}
set PROJECT_NAME system
set FPGA_PART xc7z020clg484-1
set BD_NAME design_1
set TOP_NAME design_1_wrapper
set IP_REPO_DIR {{{tmp_path / 'ip'}}}
set XDC_FILE {{{tmp_path / 'board.xdc'}}}
set NUM_CORES 8
set AXI_BASE 0x43C00000
set AXI_RANGE 0x10000
set FCLK0_MHZ 35
''')
    return RECORDING_API + CONFIGURATION_API + f'''
set missing {{{missing_cell or ''}}}
set existing {int(existing)}
set present {int(existing)}
set trace {{}}
proc get_projects {{args}} {{return {{}}}}
proc current_project {{args}} {{return system}}
proc get_filesets {{args}} {{return [lindex $args end]}}
proc get_files {{args}} {{
    global present
    if {{[string match *.bd [lindex $args end]]}} {{
        if {{$present}} {{return design_1.bd}}
        return {{}}
    }}
    return {{}}
}}
proc get_ipdefs {{args}} {{
    if {{[lindex $args end] eq "user.org:user:gpgpu_axi:*"}} {{return user.org:user:gpgpu_axi:1.0}}
    return [lindex $args end]
}}
rename get_bd_cells original_get_bd_cells
proc get_bd_cells {{args}} {{
    global missing
    if {{[lindex $args end] eq $missing ||
          ([lsearch $args -filter] >= 0 && $missing eq "rst_ps7_0_35M")}} {{return {{}}}}
    return [original_get_bd_cells {{*}}$args]
}}
rename create_bd_design original_create_bd_design
proc create_bd_design {{name}} {{
    global present
    set present 1
    original_create_bd_design $name
}}
rename get_property original_get_property
proc get_property {{key object}} {{
    if {{$key eq "PART"}} {{return xc7z020clg484-1}}
    if {{$key eq "VLNV"}} {{
        switch -- $object {{
            processing_system7_0 {{return xilinx.com:ip:processing_system7:5.5}}
            axi_smc {{return xilinx.com:ip:smartconnect:1.0}}
            rst_ps7_0_35M {{return xilinx.com:ip:proc_sys_reset:5.0}}
            irq_concat {{return xilinx.com:ip:xlconcat:2.1}}
            irq_zero - reset_locked {{return xilinx.com:ip:xlconstant:1.1}}
        }}
    }}
    return [original_get_property $key $object]
}}
foreach command {{create_project open_project close_project update_ip_catalog open_bd_design upgrade_bd_cells validate_bd_design save_bd_design generate_target add_files update_compile_order}} {{
    proc $command {{args}} {{puts [list [lindex [info level 0] 0] {{*}}$args]}}
}}
proc make_wrapper {{args}} {{puts make_wrapper; return {{{tmp_path / 'design_1_wrapper.v'}}}}}
{('dict set props gpgpu_axi_0,VLNV user.org:user:gpgpu_axi:9.0' if wrong_vlnv else '')}
source {{{tmp_path / 'create_system.tcl'}}}
'''


def test_system_creates_catalog_first_then_products_wrapper_and_top(tmp_path):
    result = run_tcl(system_script(tmp_path))
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert out.index("update_ip_catalog") < out.index("create_bd_design design_1")
    assert out.index("validate_bd_design") < out.index("save_bd_design") < out.index("generate_target")
    assert out.index("generate_target") < out.index("make_wrapper") < out.index("update_compile_order")
    assert "SET top design_1_wrapper sources_1" in out
    assert "gpgpu_axi_0/s00_axi" in out
    assert "connect_bd_net gpgpu_axi_0/irq irq_concat/In0" in out
    assert "connect_bd_net irq_zero/dout irq_concat/In1" in out
    assert "connect_bd_net irq_concat/dout processing_system7_0/IRQ_F2P" in out
    assert "CONFIG.IN1_WIDTH 15" in out
    assert "SET CONFIG.C_EXT_RESET_HIGH 0 rst_ps7_0_35M" in out


def test_system_reuses_saved_gui_design_without_bootstrap(tmp_path):
    result = run_tcl(system_script(tmp_path, existing=True))
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "open_project" in out and "open_bd_design" in out
    assert "create_bd_design" not in out and "create_project" not in out
    assert "upgrade_bd_cells gpgpu_axi_0" in out
    assert "PCW_FPGA0" not in out
    assert "SET CONFIG.SP_PER_SM" not in out


@pytest.mark.parametrize("missing", ["gpgpu_axi_0", "axi_smc", "irq_concat", "irq_zero", "rst_ps7_0_35M"])
def test_incomplete_saved_design_refused_before_refresh_or_save(tmp_path, missing):
    result = run_tcl(system_script(tmp_path, existing=True, missing_cell=missing))
    assert result.returncode != 0
    assert "Expected" in result.stderr
    assert "upgrade_bd_cells" not in result.stdout
    assert "save_bd_design" not in result.stdout
    assert "create_bd_design" not in result.stdout


def test_wrong_saved_gpu_vlnv_refused_before_refresh(tmp_path):
    result = run_tcl(system_script(tmp_path, existing=True, wrong_vlnv=True))
    assert result.returncode != 0
    assert "VLNV" in result.stderr
    assert "upgrade_bd_cells" not in result.stdout


def test_saved_gui_reset_cell_name_is_preserved(tmp_path):
    script = system_script(tmp_path, existing=True)
    # A GUI rename is not permission to rebuild or rename the saved reset cell.
    script = script.replace("rst_ps7_0_35M", "saved_reset")
    result = run_tcl(script)
    assert result.returncode == 0, result.stderr
    assert "create_bd_cell" not in result.stdout


def test_catalog_version_change_is_refused_before_saved_cell_upgrade(tmp_path):
    script = system_script(tmp_path, existing=True)
    script = script.replace(
        'if {[lindex $args end] eq "user.org:user:gpgpu_axi:*"} {return user.org:user:gpgpu_axi:1.0}',
        'if {[lindex $args end] eq "user.org:user:gpgpu_axi:*"} '
        '{return {user.org:user:gpgpu_axi:1.0 user.org:user:gpgpu_axi:2.0}}',
    )
    result = run_tcl(script)
    assert result.returncode != 0
    assert "VLNV" in result.stderr
    assert "upgrade_bd_cells" not in result.stdout


def test_obsolete_gpio_refused_before_saved_cell_upgrade(tmp_path):
    script = system_script(tmp_path, existing=True)
    script = script.replace(
        'if {$name eq "GPGPU_0" || [string match "axi_gpio*" $name]} {return {}}',
        'if {$name eq "GPGPU_0"} {return {}}\n'
        'if {[string match "axi_gpio*" $name]} {return axi_gpio_status}',
    )
    result = run_tcl(script)
    assert result.returncode != 0
    assert "Obsolete" in result.stderr
    assert "upgrade_bd_cells" not in result.stdout


def test_xdc_matches_uart_and_two_state_outputs_without_drc_waivers():
    text = (ROOT / "hardware/constraints/smart_zynq.xdc").read_text()
    for pin, port in [("L17", "UART_0_0_txd"), ("M17", "UART_0_0_rxd"),
                      ("P20", "o_core_idle_0"), ("P21", "o_core_running_0")]:
        assert re.search(rf"PACKAGE_PIN {pin}[^\n]*\[get_ports {port}\]", text)
        assert re.search(rf"IOSTANDARD LVCMOS33[^\n]*\[get_ports {port}\]", text)
    assert "SEVERITY" not in text


def test_system_scripts_are_portable_and_do_not_register_raw_rtl():
    texts = [(VIVADO / name).read_text() for name in
             ("create_system.tcl", "create_block_design.tcl", "configure_block_design.tcl")]
    for text in texts:
        assert not re.search(r"/(?:home|workspace|opt/data)/", text)
        assert "file delete" not in text
    system = texts[0]
    assert "RTL_DIR" not in system
    assert "create_project $PROJECT_NAME $PROJECT_DIR -part $FPGA_PART -force" not in system


@pytest.mark.parametrize("version", ["2024.2", "2025.1", "2026.1", "2025.20"])
def test_wrong_vivado_version_refused_before_project_open(tmp_path, version):
    script = system_script(tmp_path, existing=True).replace("return 2025.2", f"return {version}")
    result = run_tcl(script)
    assert result.returncode != 0
    assert "requires Vivado 2025.2" in result.stderr
    assert "open_project" not in result.stdout
    assert "upgrade_bd_cells" not in result.stdout
