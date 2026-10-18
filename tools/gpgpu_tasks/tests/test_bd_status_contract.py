"""Guard explicit export against legacy GPIO/module-reference design state."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_export_rejects_legacy_and_verifies_abi_before_writing():
    text = (ROOT / 'tools/hardware/vivado/export_block_design.tcl').read_text()
    for token in ('user.org:user:gpgpu_axi:1.0', 'axi_gpio*', 'o_core_idle_0', 'o_core_running_0', 'gpgpu_axi_0/s00_axi/reg0'):
        assert token in text
        assert text.index(token) < text.index('write_bd_tcl -force')
    assert 'GPGPU_0' not in text


def test_board_led_uart_pin_contract_is_not_relaxed():
    xdc = (ROOT / 'hardware/constraints/smart_zynq.xdc').read_text()
    for pin in ('L17', 'M17', 'P20', 'P21'):
        assert pin in xdc
    for port in ('UART_0_0_txd', 'UART_0_0_rxd', 'o_core_idle_0', 'o_core_running_0'):
        assert port in xdc
    assert 'LVCMOS33' in xdc
    scripts = (ROOT / 'tools/hardware/vivado/bitstream.tcl').read_text()
    assert 'SEVERITY' not in scripts
