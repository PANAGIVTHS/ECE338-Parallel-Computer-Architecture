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


def fabric_clock_khz(config):
    """The requested fabric clock in kHz (simulation; the block design reports the achieved one)."""
    return round(float(fabric_clock_mhz(config)) * 1000)


# Hex digits of the short commit hash the RTL reports in BUILD_ID.
BUILD_HASH_DIGITS = 7


def build_identity(config):
    """BUILD_HASH and BUILD_DIRTY of the RTL: the last commit touching it, and
    whether it has uncommitted changes. The RTL packs both into BUILD_ID.

    Scoped to the RTL so commits that do not change the hardware do not force
    a repackage and resynthesis. Runs git, so only call it from task actions,
    never during discovery.
    """
    import subprocess

    git = config.get('tools.git.command')
    if not isinstance(git, str) or not git:
        raise ValueError('tools.git.command must be a non-empty string')
    root = rtl_root(config)

    def run(*arguments):
        return subprocess.run([git, '-C', str(config.repo_root), *arguments, '--', str(root)],
                              check=True, capture_output=True, text=True).stdout.strip()

    commit = run('log', '-1', '--format=%H')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError(f'No commit touches {root}; BUILD_ID needs one')
    return {'BUILD_HASH': int(commit[:BUILD_HASH_DIGITS], 16),
            'BUILD_DIRTY': int(bool(run('status', '--porcelain')))}


def build_identity_path(config):
    """File the hardware:identity task writes the build identity to."""
    return config.build_root / 'hardware/build_identity.txt'


def format_parameters(parameters):
    """NAME=VALUE,NAME=VALUE: one token, safe as a Vivado -tclargs value."""
    return ','.join(f'{name}={value}' for name, value in parameters.items())


def parse_parameters(text):
    parameters = {}
    for item in text.strip().split(','):
        match = re.fullmatch(r'([A-Z][A-Z0-9_]*)=([0-9]+)', item)
        if match is None or match[1] in parameters:
            raise ValueError(f'Invalid HDL parameter: {item!r}')
        parameters[match[1]] = int(match[2])
    return parameters


def write_build_identity(config, output):
    """Rewrite *output* only when the identity changed, so dependents compare equal."""
    text = format_parameters(build_identity(config)) + '\n'
    output = Path(output)
    if not output.is_file() or output.read_text() != text:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)


def build_identity_task(config):
    """Always runs (git is cheap); dependents rebuild only when the file changes."""
    output = build_identity_path(config)
    return {
        'name': 'hardware:identity',
        'actions': [(write_build_identity, [config, output])],
        'targets': [str(output)],
        'uptodate': [False],
    }


def static_hdl_parameters(config):
    """Build-time GPGPU parameters known from the configuration alone.

    Together with the build identity file these are every HDL parameter the
    RTL tests and the packaged IP set.
    """
    version = config.get('architecture.interface_version')
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError('architecture.interface_version must be a positive integer')
    ddr = config.get('architecture.ddr_enable')
    if not isinstance(ddr, bool):
        raise ValueError('architecture.ddr_enable must be true or false')
    return {
        'INTERFACE_VERSION': version,
        'CLOCK_KHZ': fabric_clock_khz(config),
        'DDR_ENABLE': int(ddr),
    }


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
