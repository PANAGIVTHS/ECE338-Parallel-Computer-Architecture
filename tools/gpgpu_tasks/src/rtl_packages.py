"""Elaborate the RTL's SystemVerilog packages with pyslang.

Shared by the host platform header (constants marked for the host) and the
RTL test model (every package constant), so both read the values the RTL
itself computes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyslang
from pyslang import ast, parsing, syntax


def parse_sources(sources: list[Path], include_directory: Path) -> tuple[list[Any], Any, Any]:
    """(syntax trees, source manager, options) for *sources*."""
    preprocessor = parsing.PreprocessorOptions()
    preprocessor.additionalIncludePaths = [str(include_directory)]
    options = pyslang.Bag([preprocessor])
    source_manager = pyslang.SourceManager()
    trees = [syntax.SyntaxTree.fromFile(str(path), source_manager, options) for path in sources]
    return trees, source_manager, options


def package_trees(trees: list[Any]) -> list[Any]:
    """The trees that declare a package, in order."""

    def declares_package(tree: Any) -> bool:
        # A one-item text parses with that item as the root, not a compilation unit.
        items = tree.root.members if tree.root.kind == syntax.SyntaxKind.CompilationUnit else [tree.root]
        return any(item.kind == syntax.SyntaxKind.PackageDeclaration for item in items)

    return [tree for tree in trees if declares_package(tree)]


def elaborate_packages(packages: list[Any], source_manager: Any, options: Any) -> Any:
    """Compile only the package trees: the rest of the design need not satisfy
    slang's checks. Raises with slang's diagnostics when they do not elaborate."""
    compilation = ast.Compilation(options)
    for tree in packages:
        compilation.addSyntaxTree(tree)
    errors = [diagnostic for diagnostic in compilation.getAllDiagnostics() if diagnostic.isError()]
    if errors:
        engine = pyslang.DiagnosticEngine(source_manager)
        client = pyslang.TextDiagnosticClient()
        engine.addClient(client)
        for diagnostic in errors:
            engine.issue(diagnostic)
        raise ValueError(f"RTL packages do not elaborate:\n{client.getString()}")
    return compilation


def package_constants(sources: list[Path], include_directory: Path) -> dict[str, int]:
    """Every integer package parameter and enum member as {"pkg::NAME": value}.

    Parameters whose value has unknown bits or is not an integer (strings,
    reals, types) are left out.
    """
    trees, source_manager, options = parse_sources(sources, include_directory)
    compilation = elaborate_packages(package_trees(trees), source_manager, options)
    constants: dict[str, int] = {}
    for package in compilation.getPackages():
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
