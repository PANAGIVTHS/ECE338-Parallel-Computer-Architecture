"""Managed packaged-IP -> Zynq system pipeline; discovery is read-only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import zipfile

from doit.tools import config_changed
from src.project_paths import ProjectPaths
from src.hardware_contract import axi_address, identifier, xsa_path


def _source_files(root):
    # Same explicit production manifest as Tcl packaging; no experimental discovery.
    manifest = Path(__file__).with_name('production_sources.tcl').read_text()
    match = re.search(r'set PRODUCTION_RTL_SOURCES\s*\{([^}]+)\}', manifest)
    if match is None:
        raise ValueError('Invalid production source manifest')
    relative = [Path(name) for name in match.group(1).split()]
    if any(p.is_absolute() or '..' in p.parts for p in relative):
        raise ValueError('Nonportable production manifest')
    return [root / path for path in relative]


def prepare_managed_project(directory, name, part, kind, recreate=False):
    """Never adopt reference/foreign state; retain complete snapshots on recreation."""
    directory = Path(directory)
    marker = directory / '.gpgpu-managed.json'
    expected = {'project': name, 'part': part, 'kind': kind, 'schema': 1}
    if directory.is_symlink():
        raise RuntimeError(f'Refusing symbolic-link project: {directory}')
    if directory.exists() and any(directory.iterdir()):
        if not marker.is_file():
            raise RuntimeError(f'Protected/unmanaged project {directory}; use a fresh paths.build.root. No automatic adoption or deletion.')
        if json.loads(marker.read_text()) != expected:
            raise RuntimeError(f'Incompatible managed project identity: {directory}')
        if recreate:
            snapshots = directory.parent / '.snapshots'
            snapshots.mkdir(exist_ok=True)
            directory.rename(snapshots / f'{name}-{uuid.uuid4().hex}')
    directory.mkdir(parents=True, exist_ok=True)
    if not marker.exists():
        marker.write_text(json.dumps(expected, sort_keys=True) + '\n')


def validate_saved_bd(path, bd_name, part):
    try:
        design = json.loads(Path(path).read_text())['design']
        info = design['design_info']
        cells = design['components']
    except (KeyError, ValueError) as exc:
        raise RuntimeError(f'Invalid saved BD: {path}') from exc
    if info.get('name') != bd_name or info.get('device') != part:
        raise RuntimeError(f'Incompatible saved BD identity: {path}')
    if cells.get('gpgpu_axi_0', {}).get('vlnv') != 'user.org:user:gpgpu_axi:1.0':
        raise RuntimeError(f'Saved BD is not the packaged AXI system: {path}')
    if not {'processing_system7_0', 'axi_smc'} <= cells.keys() or any('axi_gpio' in name for name in cells):
        raise RuntimeError(f'Legacy/incomplete saved BD: {path}')


def _check_tool(command, required):
    result = subprocess.run([command, '-version'], capture_output=True, text=True, check=True)
    if re.search(rf'(?<!\d){re.escape(required)}(?!\d)', result.stdout + result.stderr) is None:
        raise RuntimeError(f'Vivado {required} required: {result.stdout}{result.stderr}')


def tool_current(command, required):
    """Evaluated during execution, never during discovery/help."""
    _check_tool(command, required)
    return True


def run_vivado(command, cwd, project_dir, recreate_project=False):
    # Compatibility argument intentionally does not permit recursive deletion.
    if recreate_project:
        raise RuntimeError('Use managed snapshot recreation, not recursive deletion')
    project_dir = Path(project_dir)
    logs = project_dir / '.gpgpu/logs'
    logs.mkdir(parents=True, exist_ok=True)
    stage = Path(command[command.index('-source') + 1]).stem
    argv = [*command[:1], '-log', str(logs / f'{stage}.log'), '-journal', str(logs / f'{stage}.jou'), *command[1:]]
    process = subprocess.Popen(argv, cwd=project_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    with (logs / f'{stage}.console.log').open('w') as log:
        for line in process.stdout:
            print(line, end='', flush=True)
            log.write(line)
            log.flush()
    status = process.wait()
    if status:
        raise RuntimeError(f'Vivado stage {stage} failed with exit {status}; see {logs}')


def create_ip(command, repo, directory, name, part, version):
    _check_tool(command[0], version)
    prepare_managed_project(directory, name, part, 'ip', recreate=True)
    run_vivado(command, repo, directory)
    if not (directory / f'{name}.xpr').is_file():
        raise RuntimeError('IP creation did not produce the development project')


def _tree_hash(directory):
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise RuntimeError(f'Package contains symbolic link: {path}')
        if path.is_file() and path.name != '.gpgpu-package.json':
            result[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _validate_package(directory, repo):
    # Task factories may be loaded from another checkout in the same CLI process;
    # don't reuse the first checkout's cached namespace helper/RTL manifest.
    import importlib.util
    path = Path(repo) / 'tools/hardware/vivado/package.py'
    spec = importlib.util.spec_from_file_location('_gpgpu_ip_package_validator', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Cannot load package validator: {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.validate_package(directory)


def package_current(directory, repo=None):
    """A completion stamp is valid only for the complete, independently valid tree."""
    repo = repo or Path(__file__).resolve().parents[3]
    directory = Path(directory)
    try:
        metadata = json.loads((directory / '.gpgpu-package.json').read_text())
        if metadata.get('revision', 0) < 1 or metadata.get('files') != _tree_hash(directory):
            return False
        _validate_package(directory, repo)
    except (OSError, ValueError, RuntimeError):
        return False
    return True


class GeneratedIPChanged:
    """Snapshot after task completion, including IP created during first bootstrap.

    Dynamic file_dep enumeration would force a spurious second rebuild because
    generated XCI files don't exist at first discovery. A value saver observes
    their final content and also detects later same-wrapper GUI/IP edits.
    """
    def __init__(self, project):
        self.project = Path(project)

    def state(self):
        return {p.relative_to(self.project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.project.rglob('*.xci')) if '.gpgpu' not in p.parts}

    def configure_task(self, task):
        task.value_savers.append(lambda: {'generated_ip': self.state()})

    def __call__(self, task, values):
        return values.get('generated_ip') == self.state()


def package_ip(command, repo, project, ip_repo):
    project = Path(project)
    ip_repo = Path(ip_repo)
    complete = ip_repo / '.gpgpu-package.json'
    if ip_repo.exists() and any(ip_repo.iterdir()) and not complete.is_file():
        raise RuntimeError(f'Protected/unmanaged IP repository: {ip_repo}; use a fresh build root')
    staging = ip_repo.parent / f'.ip-package-{uuid.uuid4().hex}'
    staging.mkdir(parents=True)
    command = list(command)
    command[command.index('-ip-repo-dir') + 1] = str(staging)
    previous_metadata = json.loads(complete.read_text()) if complete.exists() else {}
    revision = int(previous_metadata.get('revision', 0)) + 1
    if not 1 <= revision <= 0x7FFFFFFF:
        raise ValueError('IP core revision exhausted; cannot refresh same VLNV safely')
    command.extend(['-ip-revision', str(revision)])
    # Existing valid repository remains untouched until a fully validated package exists.
    run_vivado(command, repo, project)
    _validate_package(staging, repo)
    (staging / '.gpgpu-package.json').write_text(json.dumps(
        {'revision': revision, 'files': _tree_hash(staging)}, sort_keys=True, indent=2) + '\n')
    previous = None
    if ip_repo.exists():
        previous = ip_repo.parent / f'.ip-repo-snapshot-{uuid.uuid4().hex}'
        ip_repo.rename(previous)
    try:
        staging.rename(ip_repo)
    except BaseException:
        if previous is not None:
            previous.rename(ip_repo)
        raise


def saved_current(directory, name, part, bd):
    """Validate saved state even when creation outputs otherwise look up to date."""
    directory = Path(directory)
    if directory.is_symlink():
        raise RuntimeError(f'Refusing symlinked project: {directory}')
    if directory.exists():
        marker = directory / '.gpgpu-managed.json'
        if not marker.exists():
            if any(directory.iterdir()):
                raise RuntimeError(f'Refusing to adopt unmanaged/reference project: {directory}')
        elif marker.is_symlink() or json.loads(marker.read_text()) != {'kind': 'system', 'name': name, 'part': part}:
            raise RuntimeError(f'Existing managed project identity conflicts with config: {directory}')
    if Path(bd).exists():
        validate_saved_bd(bd, Path(bd).stem, part)
    return True


def create_system(command, repo, directory, name, part, bd, wrapper, ip_repo, version):
    _check_tool(command[0], version)
    _validate_package(ip_repo, repo)
    if not (ip_repo / '.gpgpu-package.json').is_file():
        raise RuntimeError('IP repository has no completed managed publication')
    prepare_managed_project(directory, name, part, 'system')
    saved = sorted(directory.rglob('*.bd'))
    if saved and not bd.is_file():
        raise RuntimeError('Configured BD is missing; refusing to replace saved designs: ' + ', '.join(map(str, saved)))
    if bd.is_file():
        validate_saved_bd(bd, bd.stem, part)
        snapshots = directory / '.gpgpu/bd-snapshots'
        snapshots.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bd, snapshots / f'{bd.stem}-{uuid.uuid4().hex}.bd')
    run_vivado(command, repo, directory)
    if not (directory / f'{name}.xpr').is_file() or not bd.is_file() or not wrapper.is_file():
        raise RuntimeError('System creation did not produce project, BD and wrapper')
    validate_saved_bd(bd, bd.stem, part)


def run_stage(command, repo, directory, target, xsa=False):
    run_vivado(command, repo, directory)
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f'Vivado did not produce {target}')
    if xsa:
        with zipfile.ZipFile(target) as archive:
            files = archive.namelist()
            required = (any(f.endswith('.bit') for f in files), any(f.endswith('.hwh') for f in files),
                        any(Path(f).name == 'ps7_init.tcl' for f in files), any(Path(f).name == 'ps7_init.c' for f in files))
            if not all(required):
                raise RuntimeError(f'XSA lacks bitstream/handoff/PS init: {files}')


def normalize_exported_tcl(text, repo_root, bd_name):
    """Optional export normalizer, fail closed for obsolete module-reference/GPIO designs."""
    if 'user.org:user:gpgpu_axi:1.0' not in text or 'axi_gpio' in text or '-type module' in text:
        raise RuntimeError('Export is not the packaged GPGPU AXI system')
    if re.search(r'/home/|/workspace/|[A-Za-z]:[/\\]|\\\\', text):
        raise RuntimeError('Export contains machine-specific paths')
    text, count = re.subn(r'set design_name\s+\S+', 'set design_name $::BD_NAME', text, count=1)
    if count != 1:
        raise RuntimeError('Export lacks recognizable design name')
    text = re.sub(r'(CONFIG.SP_PER_SM\s+)\{[^{}]+\}', r'\1$::NUM_CORES', text)
    text = re.sub(r'(assign_bd_address\s+-offset\s+)\S+(\s+-range\s+)\S+(?=[^\n]*gpgpu_axi_0/s00_axi/reg0)',
                  r'\1$::AXI_BASE\2$::AXI_RANGE', text)
    return '\n'.join(line.rstrip() for line in text.splitlines()).rstrip() + '\n'


def create_tasks(config):
    paths = ProjectPaths.from_config(config)
    repo = config.repo_root
    scripts = repo / 'tools/hardware/vivado'
    sources = _source_files(paths.hardware_rtl_gpgpu)
    base, size = axi_address(config)
    name = identifier(config, 'hardware.vivado.project_name')
    ip_name = identifier(config, 'hardware.vivado.ip_project_name')
    bd_name = identifier(config, 'hardware.vivado.bd_name')
    top = identifier(config, 'hardware.vivado.top')
    if top != f'{bd_name}_wrapper':
        raise ValueError('hardware.vivado.top must match <bd_name>_wrapper')
    part = config.get('hardware.fpga.part')
    version = config.get('hardware.vivado.version')
    vendor = config.get('tools.vivado.command')
    cores = config.get('architecture.num_cores')
    jobs = config.get('hardware.vivado.jobs')
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 1 for v in (cores, jobs)):
        raise ValueError('architecture.num_cores and hardware.vivado.jobs must be positive integers')
    ip_dir = paths.vivado / ip_name
    system = paths.vivado / name
    ip_repo = paths.vivado / 'ip_repo'
    if ip_name == name or ip_name in ('GPU', 'ip_repo') or name in ('GPU', 'ip_repo'):
        raise ValueError('IP and system names must be distinct and cannot use protected legacy names')
    ip_xpr = ip_dir / f'{ip_name}.xpr'
    sys_xpr = system / f'{name}.xpr'
    bd = system / f'{name}.srcs/sources_1/bd/{bd_name}/{bd_name}.bd'
    wrapper = system / f'{name}.gen/sources_1/bd/{bd_name}/hdl/{top}.v'
    synth = system / f'{name}.runs/synth_1/{top}.dcp'
    route = system / f'{name}.runs/impl_1/{top}_routed.dcp'
    bit = paths.bitstream / f'{top}.bit'
    xsa = xsa_path(config)
    stamp = ip_repo / '.gpgpu-package.json'
    component = ip_repo / 'component.xml'
    xdc = paths.hardware_constraints / 'smart_zynq.xdc'

    def command(script, ip=False):
        values = {'project-dir': ip_dir if ip else system, 'project-name': ip_name if ip else name,
                  'part': part, 'bd-name': bd_name, 'top': 'gpgpu_axi' if ip else top,
                  'rtl-dir': paths.hardware_rtl_gpgpu, 'xdc-file': xdc,
                  'bitstream-dir': paths.bitstream, 'platform-dir': paths.platform,
                  'xsa-name': xsa.stem, 'export-file': system / '.gpgpu/export.raw.tcl',
                  'num-cores': cores, 'jobs': jobs, 'repo-root': repo, 'ip-repo-dir': ip_repo,
                  'axi-base': base, 'axi-range': size, 'version': version}
        return [vendor, '-mode', 'batch', '-source', str(scripts / script), '-tclargs',
                *(item for key, value in values.items() for item in ('-' + key, str(value)))]

    shared = [str(scripts / 'common.tcl'), str(Path(__file__)), str(repo / 'tools/gpgpu_tasks/src/hardware_contract.py')]
    executable = shutil.which(vendor)
    if executable:
        shared.append(str(Path(executable).resolve()))
    source_deps = list(map(str, sources)) + [str(scripts / 'ip/empty.mem')]
    result = []

    def stage(task, script, action, args, deps, targets, parent=(), ip=False):
        cmd = command(script, ip)
        result.append({'name': task, 'actions': [(action, [cmd, *args])], 'task_dep': list(parent),
                       'file_dep': [*shared, str(scripts / script), *map(str, deps)],
                       'targets': list(map(str, targets)),
                       'uptodate': [config_changed({'command': cmd}), (tool_current, [vendor, version])],
                       'clean': []})

    stage('vivado:ip:create', 'create_ip_project.tcl', create_ip,
          [repo, ip_dir, ip_name, part, version], [*source_deps, scripts / 'production_sources.tcl'], [ip_xpr], ip=True)
    stage('vivado:ip:build', 'package_ip.tcl', package_ip, [repo, ip_dir, ip_repo],
          [ip_xpr, *source_deps, scripts / 'production_sources.tcl', scripts / 'package.py', scripts / 'ip/xgui/gpgpu_axi_v1_0.tcl'],
          [component, stamp], ['vivado:ip:create'], ip=True)
    result[-1]['uptodate'].append((package_current, [ip_repo, repo]))
    stage('vivado:system:create', 'create_system.tcl', create_system,
          [repo, system, name, part, bd, wrapper, ip_repo, version],
          [component, stamp, scripts / 'create_block_design.tcl', scripts / 'configure_block_design.tcl', xdc],
          [sys_xpr, bd, wrapper], ['vivado:ip:build'])
    result[-1]['uptodate'].append((saved_current, [system, name, part, bd]))
    stage('vivado:system:_synthesis', 'synthesis.tcl', run_stage, [repo, system, synth],
          [sys_xpr, bd, wrapper, stamp, xdc, *source_deps], [synth], ['vivado:system:create'])
    result[-1]['uptodate'].append(GeneratedIPChanged(system))
    stage('vivado:system:_implementation', 'implementation.tcl', run_stage, [repo, system, route],
          [synth, bd, xdc], [route], ['vivado:system:_synthesis'])
    stage('vivado:system:_bitstream', 'bitstream.tcl', run_stage, [repo, system, bit],
          [route, xdc], [bit], ['vivado:system:_implementation'])
    stage('vivado:system:build', 'export_hardware.tcl', run_stage, [repo, system, xsa, True],
          [bit, route, bd, stamp], [xsa], ['vivado:system:_bitstream'])
    return result
