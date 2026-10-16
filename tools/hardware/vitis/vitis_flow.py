"""Vitis Python CLI entry point for component builds.

Run through the vendor launcher, for example:
    vitis -s vitis_flow.py -- build --workspace <path> --component <name>
"""

from __future__ import annotations

from pathlib import Path
import argparse
import shutil
import sys
import re
import uuid
import zipfile
from contextlib import contextmanager

import vitis


def installed_rsa_archive() -> Path:
    """Locate the GNU RSA input in the SDK that provided the active Vitis API."""
    module_file = getattr(vitis, "__file__", None)
    if module_file:
        for parent in Path(module_file).resolve().parents:
            services = parent / "data/embeddedsw/lib/sw_services"
            if not services.is_dir():
                continue
            exact = services / "xilrsa/src/librsa.a"
            if exact.is_file():
                return exact
            candidates = sorted(services.glob("xilrsa_v*/src/librsa.a"))
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                raise RuntimeError(f"Ambiguous installed RSA archives: {candidates}")
    raise FileNotFoundError(
        "Missing vendor input xilrsa/src/librsa.a. Could not locate it in "
        "data/embeddedsw/lib/sw_services of the active Vitis SDK. "
        "Check that the matching Vitis embedded software installation is complete."
    )


def prepare_bsp_output_directories(component_root: Path) -> None:
    """Restore BSP directories and SDK inputs omitted by portable archives."""
    for cmake_source in component_root.rglob("CMakeLists.txt"):
        bsp_root = cmake_source.parent
        if not (bsp_root / "libsrc").is_dir():
            continue
        source = cmake_source.read_text(encoding="utf-8")
        if "BSP_LIBSRC_SUBDIRS" not in source or "CMAKE_LIBRARY_PATH" not in source:
            continue
        library_dir = bsp_root / "lib"
        repaired = False
        if not library_dir.is_dir():
            library_dir.mkdir()
            repaired = True
            print(f"INFO: Restored BSP library directory: {library_dir}", flush=True)
        rsa_source = bsp_root / "libsrc/xilrsa/src"
        rsa_archive = rsa_source / "librsa.a"
        if (rsa_source / "CMakeLists.txt").is_file() and not rsa_archive.is_file():
            vendor_archive = installed_rsa_archive()
            shutil.copy2(vendor_archive, rsa_archive)
            repaired = True
            print(f"INFO: Restored vendor RSA input from active SDK: {vendor_archive}", flush=True)
        # Vendor CMake checks lib/../libsrc, which fails when lib is absent.
        # Touch only after repair so an existing build graph reconfigures and
        # discovers the previously skipped targets without discarding its cache.
        if repaired:
            cmake_source.touch()


def set_workspace(client, workspace: Path) -> None:
    """Initialize portable workspace metadata without masking unrelated failures."""
    workspace_path = str(workspace.resolve())
    try:
        client.set_workspace(workspace_path)
    except Exception as error:
        if "cannot recognize the workspace version" not in str(error).lower():
            raise
        client.update_workspace(path=workspace_path)
        client.set_workspace(workspace_path)


@contextmanager
def fresh_component(workspace: Path, name: str):
    """Keep prior editable state as a backup; restore it if SDK regeneration fails."""
    if Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError(f"Invalid component name: {name!r}")
    root = workspace / name
    if workspace.is_symlink() or root.is_symlink():
        raise ValueError(f"Refusing symbolic-link workspace/component: {root}")
    workspace.mkdir(parents=True, exist_ok=True)
    backup = None
    if root.exists():
        backups = workspace.parent / "vitis-backups"
        backups.mkdir(exist_ok=True)
        backup = backups / f"{name}-{uuid.uuid4().hex}"
        root.rename(backup)
        print(f"INFO: Preserved prior component in {backup}", flush=True)
    try:
        yield root, backup
    except Exception:
        if root.exists():
            shutil.rmtree(root)
        if backup is not None:
            backup.rename(root)
        raise


def create_project(workspace: Path, xsa: Path, platform_name: str,
                   cpu: str, os_name: str, domain: str) -> None:
    """Regenerate SDT/BSP using the running SDK, never an archived hardware tree.

    API contract: AMD Vitis-Tutorials 2025.2, Embedded_Software/
    Feature_Tutorials/04-vitis_scripting_flows/scripts/unified_workspace.py;
    domain_name is documented in Embedded-Design-Tutorials 2025.2 vitis_apps.py.
    FSBL generation uses SDK defaults; it is not disabled to avoid RSA inputs.
    """
    if not xsa.is_file():
        raise FileNotFoundError(f"Vivado XSA not found: {xsa}")
    with fresh_component(workspace, platform_name) as (root, _):
        client = vitis.create_client()
        set_workspace(client, workspace)
        component = client.create_platform_component(
            name=platform_name, hw_design=str(xsa.resolve()), os=os_name,
            cpu=cpu, domain_name=domain,
        )
        if component is None or component is False:
            raise RuntimeError(f"Vitis platform creation failed: {platform_name}")
        if not (root / "vitis-comp.json").is_file():
            raise FileNotFoundError(f"Vitis did not create platform metadata: {root}")


def configure_host(host_root: Path, sources: list[Path], base_address: str) -> None:
    """Edit the SDK's actual CMake input (2025.2 root or older src layout)."""
    candidates = [host_root / "UserConfig.cmake", host_root / "src/UserConfig.cmake"]
    existing = [path for path in candidates if path.is_file()]
    if len(existing) != 1:
        raise ValueError(f"Expected exactly one UserConfig.cmake in {host_root}: {existing}")
    path = existing[0]
    text = path.read_text(encoding="utf-8")
    def replace_variable(variable: str, values: list[str]) -> None:
        nonlocal text
        replacement = f"set({variable}\n" + "".join(f'"{value}"\n' for value in values) + ")"
        text, count = re.subn(r"set\(" + variable + r"\b[^)]*\)",
                             lambda _: replacement, text, count=1, flags=re.DOTALL)
        if count != 1:
            raise ValueError(f"Missing {variable} in {path}")
    replace_variable("USER_COMPILE_SOURCES", [str(source.resolve()) for source in sources])
    match = re.search(r"set\(USER_INCLUDE_DIRECTORIES\b([^)]*)\)", text, re.DOTALL)
    if match is None:
        raise ValueError(f"Missing USER_INCLUDE_DIRECTORIES in {path}")
    includes = match.group(1).strip()
    directories = list(dict.fromkeys(str(source.parent.resolve()) for source in sources))
    extra = "".join(f'\n"{directory}"' for directory in directories if f'"{directory}"' not in includes)
    text = text[:match.start(1)] + "\n" + (includes + extra).strip() + "\n" + text[match.end(1):]
    match = re.search(r"set\(USER_COMPILE_DEFINITIONS\b([^)]*)\)", text, re.DOTALL)
    if match is None:
        raise ValueError(f"Missing USER_COMPILE_DEFINITIONS in {path}")
    definitions = '\n' + re.sub(r'"?GPGPU_BASEADDR=[^\s";)]+"?', '', match.group(1)).strip()
    definitions += f'\n"GPGPU_BASEADDR={base_address}"\n'
    text = text[:match.start(1)] + definitions + text[match.end(1):]
    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")


def build_host(workspace: Path, host_name: str, platform_name: str, domain: str,
               template: str, sources: list[Path], base_address: str, archive: Path,
               repo_root: Path | None = None) -> None:
    xpfm = workspace / platform_name / f"export/{platform_name}/{platform_name}.xpfm"
    if not xpfm.is_file():
        raise FileNotFoundError(f"Build platform before host: {xpfm}")
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(f"Host source not found: {source}")
    with fresh_component(workspace, host_name) as (root, backup):
        client = vitis.create_client()
        set_workspace(client, workspace)
        component = client.create_app_component(name=host_name, platform=str(xpfm.resolve()),
                                               domain=domain, template=template)
        if component is None or component is False:
            raise RuntimeError(f"Vitis application creation failed: {host_name}")
        # Preserve editable application inputs only, not version-owned BSP/SDT,
        # generated CMakeLists, linker memory maps or hardware metadata.
        config = root / "UserConfig.cmake"
        if not config.is_file():
            config = root / "src/UserConfig.cmake"
        if backup is not None:
            old_config = next((p for p in (backup / "UserConfig.cmake", backup / "src/UserConfig.cmake") if p.is_file()), None)
            if old_config:
                shutil.copy2(old_config, config)
            for source in (backup / "src").rglob("*"):
                if source.is_file() and source.suffix in {".c", ".h", ".cpp", ".hpp"}:
                    if source.is_symlink():
                        raise ValueError(f"Refusing symbolic link: {source}")
                    destination = root / "src" / source.relative_to(backup / "src")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
        elif archive.is_file():
            # Export archives seed editable build options only. Never extract
            # platform hardware or SDK-generated sources from an old SDK.
            with zipfile.ZipFile(archive) as exported:
                for name in (f"{host_name}/UserConfig.cmake", f"{host_name}/src/UserConfig.cmake"):
                    if name in exported.namelist():
                        config.write_bytes(exported.read(name))
                        break
                for name in exported.namelist():
                    relative = Path(name)
                    if relative.is_absolute() or '..' in relative.parts:
                        raise ValueError(f"Unsafe path in Vitis project archive: {name}")
                    if relative.parts[:2] == (host_name, 'src') and relative.suffix in {'.c', '.h', '.cpp', '.hpp'}:
                        destination = root.joinpath(*relative.parts[1:])
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(exported.read(name))
        config_text = config.read_text(encoding="utf-8")
        replacements = {'${GPGPU_WORKSPACE}': str(workspace.resolve())}
        if repo_root is not None:
            replacements['${GPGPU_REPO_ROOT}'] = str(repo_root.resolve())
        if '${XILINX_VITIS}' in config_text:
            module_file = getattr(vitis, '__file__', None)
            vendor_root = next((p for p in Path(module_file).resolve().parents
                                if (p / 'data/embeddedsw').is_dir()), None) if module_file else None
            if vendor_root is None:
                raise FileNotFoundError('Cannot restore vendor path in editable UserConfig.cmake from active SDK')
            replacements['${XILINX_VITIS}'] = str(vendor_root)
        for marker, value in replacements.items():
            config_text = config_text.replace(marker, value)
        if config_text != config.read_text(encoding="utf-8"):
            config.write_text(config_text, encoding="utf-8")
        configure_host(root, sources, base_address)
        prepare_bsp_output_directories(workspace / platform_name)
        if component.build() is False:
            raise RuntimeError(f"Vitis build failed for component {host_name!r}")


def build_component(workspace: Path, component_name: str) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Vitis workspace not found: {workspace}")
    metadata = workspace / component_name / "vitis-comp.json"
    if not metadata.is_file():
        raise FileNotFoundError(f"Vitis component not found: {metadata}")

    client = vitis.create_client()
    set_workspace(client, workspace)
    component = client.get_component(name=component_name)
    if component is None:
        raise RuntimeError(
            f"Vitis did not discover component {component_name!r} in {workspace}"
        )
    prepare_bsp_output_directories(workspace / component_name)
    status = component.build()
    if status is False:
        raise RuntimeError(f"Vitis build failed for component {component_name!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build GPGPU Vitis components")
    subparsers = parser.add_subparsers(dest="action", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--workspace", type=Path, required=True)
    build.add_argument("--component", required=True)
    project = subparsers.add_parser("project")
    project.add_argument("--workspace", type=Path, required=True)
    project.add_argument("--xsa", type=Path, required=True)
    project.add_argument("--platform", required=True)
    project.add_argument("--cpu", required=True)
    project.add_argument("--os", required=True)
    project.add_argument("--domain", required=True)
    host = subparsers.add_parser("host")
    host.add_argument("--workspace", type=Path, required=True)
    host.add_argument("--component", required=True)
    host.add_argument("--platform", required=True)
    host.add_argument("--domain", required=True)
    host.add_argument("--template", required=True)
    host.add_argument("--source", type=Path, action="append", required=True)
    host.add_argument("--base-address", required=True)
    host.add_argument("--archive", type=Path, required=True)
    host.add_argument("--repo-root", type=Path, required=True)
    # The vendor launcher may forward its argument separator to the script.
    argv = sys.argv[1:]
    if argv[:1] == ["--"]:
        argv = argv[1:]
    arguments = parser.parse_args(argv)

    if arguments.action == "build":
        build_component(arguments.workspace, arguments.component)
    elif arguments.action == "project":
        create_project(arguments.workspace, arguments.xsa, arguments.platform,
                       arguments.cpu, arguments.os, arguments.domain)
    elif arguments.action == "host":
        build_host(arguments.workspace, arguments.component, arguments.platform,
                   arguments.domain, arguments.template, arguments.source,
                   arguments.base_address, arguments.archive, arguments.repo_root)


if __name__ == "__main__":
    main()
