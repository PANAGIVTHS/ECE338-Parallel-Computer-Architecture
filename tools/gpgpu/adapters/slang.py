"""Reads constants out of the RTL's SystemVerilog packages, as the RTL itself computes them."""
from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

import pyslang
from pyslang import ast, syntax


class Export(NamedTuple):
    package: str
    name: str
    value: int
    hex_digits: int | None  # None: decimal (integer types and enum members)


def _parse(sources: list[Path], include_directory: Path) -> tuple[list[Any], Any, Any]:
    preprocessor = pyslang.parsing.PreprocessorOptions()
    preprocessor.additionalIncludePaths = [str(include_directory)]
    options = pyslang.Bag([preprocessor])
    manager = pyslang.SourceManager()
    return [syntax.SyntaxTree.fromFile(str(path), manager, options) for path in sources], manager, options


def _package_trees(trees: list[Any]) -> list[Any]:
    def declares_package(tree: Any) -> bool:
        # A one-item text parses with that item as the root, not a compilation unit.
        items = tree.root.members if tree.root.kind == syntax.SyntaxKind.CompilationUnit else [tree.root]
        return any(item.kind == syntax.SyntaxKind.PackageDeclaration for item in items)
    return [tree for tree in trees if declares_package(tree)]


def _elaborate(packages: list[Any], manager: Any, options: Any) -> Any:
    """Compile only the packages: the rest of the design need not satisfy slang's checks."""
    compilation = ast.Compilation(options)
    for tree in packages:
        compilation.addSyntaxTree(tree)
    errors = [diagnostic for diagnostic in compilation.getAllDiagnostics() if diagnostic.isError()]
    if errors:
        engine = pyslang.DiagnosticEngine(manager)
        client = pyslang.TextDiagnosticClient()
        engine.addClient(client)
        for diagnostic in errors:
            engine.issue(diagnostic)
        raise ValueError(f"RTL packages do not elaborate:\n{client.getString()}")
    return compilation


def package_constants(sources: list[Path], include_directory: Path) -> dict[str, int]:
    """Every integer package parameter and enum member, as {"pkg::NAME": value}."""
    trees, manager, options = _parse(sources, include_directory)
    constants: dict[str, int] = {}
    for package in _elaborate(_package_trees(trees), manager, options).getPackages():
        for symbol in package:
            if symbol.kind == ast.SymbolKind.Parameter:
                members = [symbol]
            elif symbol.kind == ast.SymbolKind.TypeAlias and symbol.targetType.type.canonicalType.isEnum:
                members = list(symbol.targetType.type.canonicalType)
            else:
                continue
            for member in members:
                number = getattr(member.value, "value", None)
                if isinstance(number, pyslang.SVInt) and not number.hasUnknown:
                    constants[f"{package.name}::{member.name}"] = int(number)
    return constants


def _integer(symbol: Any, value: Any, attribute: str) -> int:
    number = value.value
    if number.hasUnknown or int(number) < 0:
        raise ValueError(f"(* {attribute} *) {symbol.name} is not a known non-negative integer: {number}")
    return int(number)


def _symbol_exports(package: str, symbol: Any, attribute: str) -> list[Export]:
    if symbol.kind == ast.SymbolKind.Parameter:
        kind = symbol.type.canonicalType
        digits = None if kind.isPredefinedInteger else (kind.bitWidth + 3) // 4
        return [Export(package, symbol.name, _integer(symbol, symbol.value, attribute), digits)]
    if symbol.kind == ast.SymbolKind.TypeAlias and symbol.targetType.type.canonicalType.isEnum:
        return [Export(package, member.name, _integer(member, member.value, attribute), None)
                for member in symbol.targetType.type.canonicalType]
    raise ValueError(f"(* {attribute} *) supports parameters and enum typedefs; "
                     f"{package}::{symbol.name} is a {symbol.kind.name}")


def read_exports(sources: list[Path], include_directory: Path, attribute: str) -> list[Export]:
    """Every package member marked (* attribute *), in source order."""
    trees, manager, options = _parse(sources, include_directory)
    packages = _package_trees(trees)
    compilation = _elaborate(packages, manager, options)
    order = {tree.root.sourceRange.start.buffer: index for index, tree in enumerate(packages)}
    marked = sorted(((order[symbol.location.buffer], symbol.location.offset), package.name, symbol)
                    for package in compilation.getPackages() for symbol in package
                    if any(spec.name == attribute for spec in compilation.getAttributes(symbol)))
    exports = [export for _, package, symbol in marked for export in _symbol_exports(package, symbol, attribute)]

    attributes = 0

    def count(node: Any) -> None:
        nonlocal attributes
        if node.kind == syntax.SyntaxKind.AttributeSpec and node.name.valueText == attribute:
            attributes += 1

    for tree in trees:
        tree.root.visit(count)
    if attributes != len(marked):
        raise ValueError(f"{attributes} (* {attribute} *) attributes but {len(marked)} on package members: "
                         "only package parameters and enum typedefs can be exported")
    names = [export.name for export in exports]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates or not exports:
        raise ValueError(f"(* {attribute} *) exports must be unique and not empty; twice: {', '.join(duplicates)}")
    return exports
