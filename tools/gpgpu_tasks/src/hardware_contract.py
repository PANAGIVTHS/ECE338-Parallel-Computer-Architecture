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



def fabric_clock_mhz(config):
    """Requested PS FCLK_CLK0 frequency; Vivado picks the nearest achievable divider."""
    value = config.get('hardware.vivado.fabric_clock_mhz')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
        raise ValueError('hardware.vivado.fabric_clock_mhz must be a positive number')
    return f'{value:g}'


def string_list(config, key):
    value = config.get(key)
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)) \
            or not all(isinstance(item, str) and item for item in value):
        raise TypeError(f'{key} must be a list of non-empty strings')
    return list(value)


def rtl_root(config):
    value = config.get('paths.rtl.sources.gpgpu')
    if not isinstance(value, str) or not value:
        raise TypeError('paths.rtl.sources.gpgpu must be a non-empty string')
    root = (config.repo_root / value).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f'paths.rtl.sources.gpgpu not found: {root}')
    return root


def rtl_sources(config, exclude):
    """Resolve hardware.sources under paths.rtl.sources.gpgpu for one consumer.

    Returns (sources, headers). Sources are every hardware.sources.extensions
    file not matching *exclude*: hardware.sources.ordered first, minus excluded
    entries, then the rest in path order. Headers are the
    hardware.sources.header_extensions files, also minus *exclude*.

    An *exclude* entry is either a bare directory or file name, matched at any
    depth (``experimental`` drops every experimental/ tree), or a path relative
    to the RTL root (``memory/bram``, ``sp/ALU.sv``) that drops exactly that
    file or directory.
    """
    root = rtl_root(config)
    entries = [tuple(entry.strip('/').split('/')) for entry in exclude]
    names = {entry[0] for entry in entries if len(entry) == 1}
    paths = [entry for entry in entries if len(entry) > 1]

    def excluded(path):
        parts = path.relative_to(root).parts
        return bool(names & set(parts)) or any(parts[:len(p)] == p for p in paths)

    def collect(extensions):
        return sorted(
            path for path in root.rglob('*')
            if path.is_file() and path.suffix in extensions and not excluded(path)
        )

    found = collect(string_list(config, 'hardware.sources.extensions'))
    first = []
    for relative in string_list(config, 'hardware.sources.ordered'):
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f'hardware.sources.ordered entry not found: {path}')
        if path in first:
            raise ValueError(f'hardware.sources.ordered lists {relative} twice')
        if path in found:
            first.append(path)
    sources = [*first, *(path for path in found if path not in first)]
    return sources, collect(string_list(config, 'hardware.sources.header_extensions'))
