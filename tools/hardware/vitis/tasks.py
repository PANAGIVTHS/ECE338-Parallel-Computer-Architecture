"""Portable staged Vitis 2025.2 SDK project, build, and export tasks."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
import json
import hashlib
import os
import re
import subprocess
import sys
import zipfile

from doit.tools import config_changed
from src.project_paths import ProjectPaths
from src.hardware_contract import axi_address, xsa_path

_TEXT_SUFFIXES = {'', '.c', '.cmake', '.h', '.ini', '.json', '.ld', '.md', '.py', '.tcl', '.txt', '.yaml', '.yml'}
_EXCLUDED_SUFFIXES = {'.a', '.bit', '.d', '.elf', '.log', '.o', '.obj', '.xsa'}
_EXCLUDED_PARTS = {'.Xil', '.lock', '.vitisWorkspace.json', '__pycache__', 'build', 'build_configs', 'CMakeFiles', 'export', 'logs'}


def _string(config, key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f'{key} must be a non-empty string')
    return value


def _string_list(config, key: str) -> tuple[str, ...]:
    value = config.get(key)
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f'{key} must be a non-empty list')
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f'{key} must contain only non-empty strings')
    return tuple(value)


def _validate_component_metadata(path: Path, expected_name: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f'Missing Vitis component metadata: {path}')
    try:
        metadata = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f'Invalid Vitis component metadata: {path}') from exc
    if not isinstance(metadata, dict) or metadata.get('name') != expected_name:
        raise ValueError(f'Vitis component at {path} is not named {expected_name!r}')
    return metadata


def _portable_text(text: str, repo_root: Path, workspace: Path, xsa: Path,
                   vendor_root: str | None) -> str:
    replacements = [(str(xsa.resolve()), '${GPGPU_XSA}'),
                    (str(workspace.resolve()), '${GPGPU_WORKSPACE}'),
                    (str(repo_root.resolve()), '${GPGPU_REPO_ROOT}')]
    if vendor_root:
        vendor_path = Path(vendor_root)
        replacements.extend([(str(vendor_path), '${XILINX_VITIS}'),
                             (str(vendor_path.parent), '${XILINX_VITIS}/..')])
    for absolute, marker in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        text = text.replace(absolute, marker)
    return text


def _vitis_vendor_root(host_root: Path) -> str | None:
    app_yaml = host_root / 'src/app.yaml'
    if not app_yaml.is_file():
        return None
    match = re.search(r'(?m)^app_src_dir:\s*(.+?)/data/embeddedsw(?:/|$)', app_yaml.read_text(encoding='utf-8'))
    if match is None or match.group(1).startswith('${'):
        return None
    return match.group(1)


def _archive_excluded(relative: Path, platform_name: str) -> bool:
    if any(part in _EXCLUDED_PARTS for part in relative.parts):
        return True
    # This is an SDK-owned *input*, not a compiled output. Do not lose FSBL/RSA.
    if relative.parts[-4:] == ('libsrc', 'xilrsa', 'src', 'librsa.a'):
        return False
    return relative.suffix.lower() in _EXCLUDED_SUFFIXES


def _write_portable_entry(output: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    output.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _mark_workspace_exported(workspace: Path, component_names: Sequence[str]) -> None:
    for component_name in component_names:
        (workspace / component_name / 'vitis-comp.json').touch()


def export_workspace(workspace: Path, archive: Path, repo_root: Path,
                     platform_name: str, host_name: str) -> None:
    """Atomically export editable state; SDK regeneration never imports hardware."""
    workspace, repo_root, archive = workspace.resolve(), repo_root.resolve(), archive.resolve()
    platform_root, host_root = workspace / platform_name, workspace / host_name
    for root in (platform_root, host_root):
        if root.is_symlink():
            raise ValueError(f'Refusing to export symbolic link: {root}')
    metadata_path = platform_root / 'vitis-comp.json'
    metadata = _validate_component_metadata(metadata_path, platform_name)
    _validate_component_metadata(host_root / 'vitis-comp.json', host_name)
    configuration = metadata.get('configuration')
    if not isinstance(configuration, Mapping):
        raise ValueError(f'Platform metadata has no configuration mapping: {metadata_path}')
    xsa_value = configuration.get('xsa')
    xsa = Path(xsa_value) if isinstance(xsa_value, str) and xsa_value else repo_root / 'missing.xsa'
    vendor_root = _vitis_vendor_root(host_root)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(prefix=f'.{archive.name}.', suffix='.tmp', dir=archive.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
            for name, root in ((platform_name, platform_root), (host_name, host_root)):
                for path in sorted(root.rglob('*')):
                    if path.is_symlink():
                        raise ValueError(f'Refusing to export symbolic link: {path}')
                    if not path.is_file():
                        continue
                    relative = path.relative_to(root)
                    if _archive_excluded(relative, platform_name):
                        continue
                    data = path.read_bytes()
                    if path.suffix.lower() in _TEXT_SUFFIXES:
                        try:
                            text = data.decode('utf-8')
                        except UnicodeDecodeError:
                            pass
                        else:
                            if path == metadata_path:
                                portable = json.loads(text)
                                portable['configuration']['xsa'] = '${GPGPU_XSA}'
                                portable['configuration']['xsaPathInPlatform'] = f'{platform_name}/hw/{platform_name}.xsa'
                                text = json.dumps(portable, indent=2, ensure_ascii=False) + '\n'
                            data = _portable_text(text, repo_root, workspace, xsa, vendor_root).encode('utf-8')
                    lowered = data.lower()
                    if any(marker in lowered for marker in (b'/home/', b'/workspace/', b'tsiantosd')):
                        raise ValueError(f'Refusing to export machine-specific path data in {path}')
                    _write_portable_entry(output, (Path(name) / relative).as_posix(), data)
        if archive.is_file() and archive.read_bytes() == temporary_path.read_bytes():
            print(f'Portable Vitis default project is already current: {archive}', file=sys.stderr)
        else:
            os.replace(temporary_path, archive)
            print(f'Updated portable Vitis default project: {archive}', file=sys.stderr)
        _mark_workspace_exported(workspace, (platform_name, host_name))
    finally:
        temporary_path.unlink(missing_ok=True)


def run_vitis(command: Sequence[str], repo_root: Path, expected_outputs: Sequence[Path]) -> None:
    subprocess.run(list(command), cwd=repo_root, check=True)
    missing = [str(path) for path in expected_outputs if not path.is_file()]
    if missing:
        raise FileNotFoundError('Vitis completed without producing required artifacts: ' + ', '.join(missing))


class EditableHostChanged:
    """Record SDK-created editable inputs *after* the build, not at discovery.

    Adding generated UserConfig.cmake to file_dep only when it exists causes a
    spurious second build. A post-action value saver tracks edits and removals
    while keeping clean-checkout task discovery free of generated inputs.
    """
    def __init__(self, root: Path):
        self.root = root

    def digest(self) -> str:
        inputs = [self.root / 'UserConfig.cmake', self.root / 'src/UserConfig.cmake']
        inputs.extend(p for p in (self.root / 'src').rglob('*') if p.suffix in {'.c', '.h', '.cpp', '.hpp'})
        digest = hashlib.sha256()
        for path in sorted(inputs):
            if path.is_file():
                digest.update(str(path.relative_to(self.root)).encode())
                digest.update(b'\0')
                digest.update(path.read_bytes())
                digest.update(b'\0')
        return digest.hexdigest()

    def configure_task(self, task) -> None:
        task.value_savers.append(lambda: {'editable_host_digest': self.digest()})

    def __call__(self, task, values) -> bool:
        return values.get('editable_host_digest') == self.digest()


def create_tasks(config) -> list[dict[str, Any]]:
    paths = ProjectPaths.from_config(config)
    repo_root = paths.repo_root
    workspace = paths.software_build / 'vitis'
    platform_name = _string(config, 'hardware.vitis.platform_name')
    host_name = _string(config, 'hardware.vitis.host_name')
    cpu = _string(config, 'hardware.vitis.cpu')
    domain = _string(config, 'hardware.vitis.domain')
    os_name = _string(config, 'hardware.vitis.os')
    template = _string(config, 'hardware.vitis.template')
    archive = repo_root / _string(config, 'hardware.vitis.default_archive')
    sources = tuple(repo_root / relative for relative in _string_list(config, 'hardware.vitis.host_sources'))
    headers = sorted({header for source in sources for header in source.parent.glob('*.h')})
    xsa = xsa_path(config)
    base_address, address_range = axi_address(config)
    launcher = _string(config, 'tools.vitis.command')
    script = repo_root / 'tools/hardware/vitis/vitis_flow.py'
    prefix = [launcher, '-s', str(script), '--']
    project_command = prefix + ['project', '--workspace', str(workspace), '--xsa', str(xsa),
                                '--platform', platform_name, '--cpu', cpu, '--os', os_name, '--domain', domain]
    platform_command = prefix + ['build', '--workspace', str(workspace), '--component', platform_name]
    host_command = prefix + ['host', '--workspace', str(workspace), '--component', host_name,
                             '--platform', platform_name, '--domain', domain, '--template', template,
                             '--base-address', base_address, '--archive', str(archive), '--repo-root', str(repo_root)]
    for source in sources:
        host_command.extend(['--source', str(source)])
    platform_root, host_root = workspace / platform_name, workspace / host_name
    platform_metadata = platform_root / 'vitis-comp.json'
    host_metadata = host_root / 'vitis-comp.json'
    platform_xsa = platform_root / f'export/{platform_name}/hw/{platform_name}.xsa'
    ps_init = platform_root / f'export/{platform_name}/hw/sdt/ps7_init.tcl'
    xpfm = platform_root / f'export/{platform_name}/{platform_name}.xpfm'
    elf = host_root / f'build/{host_name}.elf'
    return [
        {'name': 'vitis:project',
         'actions': [(run_vitis, [project_command, repo_root, (platform_metadata,)])],
         'task_dep': ['vivado:system:build'],
         'file_dep': [str(xsa), str(script)], 'targets': [str(platform_metadata)],
         'uptodate': [config_changed({'version': _string(config, 'hardware.vitis.version'), 'command': project_command})]},
        {'name': 'vitis:build:platform',
         'actions': [(run_vitis, [platform_command, repo_root, (platform_xsa, ps_init, xpfm)])],
         'task_dep': ['vitis:project'],
         'file_dep': [str(script), str(platform_metadata), str(xsa)],
         'targets': [str(platform_xsa), str(ps_init), str(xpfm)],
         'uptodate': [config_changed({'command': platform_command})], 'clean': True},
        {'name': 'vitis:build:host',
         'actions': [(run_vitis, [host_command, repo_root, (elf, host_metadata)])],
         'task_dep': ['vitis:build:platform'],
         'file_dep': [str(script), str(archive), str(platform_xsa), str(ps_init), str(xpfm),
                      *(str(p) for p in sources), *(str(p) for p in headers)],
         'targets': [str(elf), str(host_metadata)],
         'uptodate': [config_changed({'command': host_command, 'range': address_range}), EditableHostChanged(host_root)], 'clean': True},
        {'name': 'vitis:build:all', 'actions': None, 'task_dep': ['vitis:build:host']},
        {'name': 'vitis:export',
         'actions': [(export_workspace, [workspace, archive, repo_root, platform_name, host_name])],
         'uptodate': [False]},
    ]
