"""Generate the host driver's platform header from the RTL and configuration.

The RTL decides what the host sees: every package declaration marked with the
SystemVerilog attribute named by software.host.export_attribute is exported as
``<software.host.define_prefix><NAME>`` with the value pyslang elaborates for it. A marked parameter exports its value
(an unpacked array parameter as a C initializer list); a marked enum typedef exports each of its members and, when they
are numbered 0 to N-1, ``<TYPE>_NAMES``: their names as a C initializer list indexed by value (TYPE is the typedef's
name in capitals without its ``_t``). The interface version and the
driver's interrupt settings come from the configuration. The base address is
not here: the Vitis flow defines GPGPU_BASEADDR from
hardware.vivado.peripheral.base_address. The generated header is committed so
the Vitis host build needs no generation step of its own.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, NamedTuple

from doit.tools import config_changed
from pyslang import ast, syntax
from src.hardware_contract import rtl_root, rtl_sources, string_list
from src.rtl_packages import elaborate_packages, package_trees, parse_sources

if TYPE_CHECKING:
    from config import ResolvedConfig


class Export(NamedTuple):
    package: str
    name: str
    value: int | tuple[int, ...] | tuple[str, ...]  # a tuple: a C initializer list
    hex_digits: int | None  # None: decimal (integer types and enum members)


def _positive_int(config: ResolvedConfig, key: str) -> int:
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _identifier(config: ResolvedConfig, key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"{key} must be an identifier")
    return value


def host_settings(config: ResolvedConfig) -> dict[str, Any]:
    """Configuration values the generated header carries."""

    use_irq = config.get("software.host.use_irq")
    if not isinstance(use_irq, bool):
        raise ValueError("software.host.use_irq must be true or false")
    return {
        "export_attribute": _identifier(config, "software.host.export_attribute"),
        "define_prefix": _identifier(config, "software.host.define_prefix"),
        "interface_version": _positive_int(config, "architecture.interface_version"),
        "use_irq": use_irq,
        "irq_id": _positive_int(config, "software.host.irq_id"),
    }


def production_sources(config: ResolvedConfig) -> tuple[list[Path], list[Path]]:
    """(sources, headers) of the production IP: the RTL the host talks to."""

    return rtl_sources(config, string_list(config, "hardware.vivado.exclude_sources"))


def _integer(symbol: Any, value: Any, attribute: str) -> int:
    number = value.value
    if number.hasUnknown:
        raise ValueError(f"(* {attribute} *) {symbol.name} has unknown bits: {number}")
    result = int(number)
    if result < 0:
        raise ValueError(f"(* {attribute} *) {symbol.name} is negative: {result}")
    return result


def _hex_digits(kind: Any) -> int | None:
    return None if kind.isPredefinedInteger or kind.isEnum else (kind.bitWidth + 3) // 4


def _symbol_exports(package: str, symbol: Any, attribute: str) -> list[Export]:
    if symbol.kind == ast.SymbolKind.Parameter:
        kind = symbol.type.canonicalType
        if kind.isUnpackedArray:
            values = tuple(_integer(symbol, element, attribute) for element in symbol.value.value)
            return [Export(package, symbol.name, values, _hex_digits(kind.elementType.canonicalType))]
        return [Export(package, symbol.name, _integer(symbol, symbol.value, attribute), _hex_digits(kind))]
    if symbol.kind == ast.SymbolKind.TypeAlias and symbol.targetType.type.canonicalType.isEnum:
        members = [(member.name, _integer(member, member.value, attribute))
                   for member in symbol.targetType.type.canonicalType]
        exports = [Export(package, name, value, None) for name, value in members]
        if [value for _, value in members] == list(range(len(members))):
            table = re.sub(r"_t$", "", symbol.name).upper() + "_NAMES"
            exports.append(Export(package, table, tuple(name for name, _ in members), None))
        return exports
    raise ValueError(
        f"(* {attribute} *) supports parameters and enum typedefs; "
        f"{package}::{symbol.name} is a {symbol.kind.name}"
    )


def collect_exports(trees: list[Any], source_manager: Any, options: Any,
                    attribute: str) -> list[Export]:
    """Exports of every package member marked ``(* attribute *)``, in source order.

    Only files declaring a package are elaborated: the exports are package
    constants, and the rest of the design need not satisfy slang's checks.
    Every marker in *trees* must be on a package member.
    """

    packages = package_trees(trees)
    compilation = elaborate_packages(packages, source_manager, options)

    order = {tree.root.sourceRange.start.buffer: index for index, tree in enumerate(packages)}
    marked = []
    for package in compilation.getPackages():
        for symbol in package:
            if any(spec.name == attribute for spec in compilation.getAttributes(symbol)):
                marked.append(((order[symbol.location.buffer], symbol.location.offset), package.name, symbol))
    exports = [export for _, package, symbol in sorted(marked, key=lambda item: item[0])
               for export in _symbol_exports(package, symbol, attribute)]

    attributes = 0

    def count(node: Any) -> None:
        nonlocal attributes
        if node.kind == syntax.SyntaxKind.AttributeSpec and node.name.valueText == attribute:
            attributes += 1

    for tree in trees:
        tree.root.visit(count)
    if attributes != len(marked):
        raise ValueError(
            f"{attributes} (* {attribute} *) attributes but {len(marked)} on package members: "
            f"only package parameters and enum typedefs can be exported"
        )
    names = [export.name for export in exports]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"(* {attribute} *) exports these names twice: {', '.join(duplicates)}")
    if not exports:
        raise ValueError(f"No (* {attribute} *) declarations found in the RTL packages")
    return exports


def read_exports(sources: list[Path], include_directory: Path, attribute: str) -> list[Export]:
    trees, source_manager, options = parse_sources(sources, include_directory)
    return collect_exports(trees, source_manager, options, attribute)


def include_guard(header: Path) -> str:
    """The include guard derived from the header's file name."""

    return re.sub(r"\W", "_", header.name).upper()


def _c_value(value: int | tuple[int, ...] | tuple[str, ...], hex_digits: int | None) -> str:
    """A C literal for an exported value; a tuple is an initializer list."""

    if isinstance(value, tuple):
        return "{ " + ", ".join(f'"{item}"' if isinstance(item, str) else _c_value(item, hex_digits)
                                for item in value) + " }"
    return f"{value}U" if hex_digits is None else f"0x{value:0{hex_digits}X}U"


def render_header(exports: list[Export], settings: dict[str, Any], guard: str) -> str:
    """The C header text for the given exports and host settings."""

    lines = []

    def define(name: str, value: str) -> None:
        lines.append(f"#define {settings['define_prefix']}{name:<28} {value}")

    lines += [
        "/* Generated by tools/software/host_platform.py (task software:host:platform)",
        f" * from the (* {settings['export_attribute']} *) declarations in the RTL and the configuration.",
        " * Do not edit: change the RTL or the configuration and regenerate.",
        " */",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "/* Interface version reported in INFO[31:16] (architecture.interface_version). */",
    ]
    define("INTERFACE_VERSION", f"{settings['interface_version']}U")
    package = None
    for export in exports:
        if export.package != package:
            package = export.package
            lines += ["", f"/* {package} */"]
        define(export.name, _c_value(export.value, export.hex_digits))
    lines += ["", "/* Completion wait: PS interrupt or IRQ_STATUS polling (software.host). */"]
    define("USE_IRQ", "1" if settings["use_irq"] else "0")
    define("IRQ_ID", f"{settings['irq_id']}U")
    lines += ["", f"#endif /* {guard} */", ""]
    return "\n".join(lines)


def header_path(config: ResolvedConfig) -> Path:
    value = config.get("software.host.platform_header")
    if not isinstance(value, str) or not value.endswith(".h"):
        raise ValueError("software.host.platform_header must be a repository-relative .h path")
    return config.repo_root / value


def write_header(sources: list[Path], include_directory: Path, settings: dict[str, Any],
                 output: Path) -> None:
    exports = read_exports(sources, include_directory, settings["export_attribute"])
    output.write_text(render_header(exports, settings, include_guard(output)), encoding="utf-8")


def create_tasks(config: ResolvedConfig) -> list[dict[str, Any]]:
    """The platform-header generation task."""

    sources, headers = production_sources(config)
    settings = host_settings(config)
    output = header_path(config)
    return [
        {
            "name": "software:host:platform",
            "actions": [(write_header, [sources, rtl_root(config), settings, output])],
            "file_dep": [*map(str, (*sources, *headers)), str(Path(__file__).resolve())],
            "targets": [str(output)],
            "uptodate": [config_changed(settings)],
        }
    ]
