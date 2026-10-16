"""Shared validated hardware/software build contracts (no vendor discovery)."""
from pathlib import Path
import re


def identifier(config, key):
    value = config.get(key)
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value):
        raise ValueError(f'{key} must be a portable identifier')
    return value


def xsa_path(config):
    return config.build_root / 'hardware/platform' / (identifier(config, 'hardware.vivado.xsa_name') + '.xsa')


def axi_address(config):
    keys = ('hardware.vivado.peripheral.base_address', 'hardware.vivado.peripheral.range')
    values = [config.get(key) for key in keys]
    for key, value in zip(keys, values):
        if not isinstance(value, str) or not re.fullmatch(r'0[xX][0-9a-fA-F]{1,8}', value):
            raise ValueError(f'{key} must be a 32-bit hexadecimal string')
    base, size = (int(value, 16) for value in values)
    # The RTL decodes 16-bit local offsets; larger/smaller ranges would diverge
    # from the IP-XACT contract and host register/memory windows.
    if size != 0x10000:
        raise ValueError('hardware.vivado.peripheral.range must be 0x00010000 (64 KiB decoded aperture)')
    if base % size or base + size > 0x100000000:
        raise ValueError('hardware.vivado.peripheral.base_address must be 64-KiB aligned and fit in 32 bits')
    return f'0x{base:08X}', f'0x{size:08X}'
