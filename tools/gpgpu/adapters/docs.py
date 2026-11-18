"""DocsFlow: the architecture map, a YAML model drawn by a static zoomable viewer."""
from __future__ import annotations

import functools
import http.server
import re
import shutil
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import Any

import yaml

from gpgpu.api import GpgpuError, Step

from .config import Config, Section
from .design import rtl_root, rtl_sources

# Keep in step with KINDS and WIRES in the viewer's map.js.
BLOCK_KINDS = {"lane", "ip", "module", "memory", "regs", "bus", "process", "command", "artifact", "tool", "external"}
WIRE_KINDS = {"data", "control", "axi", "axilite", "stream", "uart", "irq", "clock", "produces", "perf"}
BLOCK_KEYS = {"id", "label", "kind", "tech", "summary", "doc", "rtl", "src", "bd", "meta", "count", "status",
              "children", "wires"}
STATUSES = {"experimental", "deprecated"}
_VALUE = re.compile(r"\$\{([^}:]+(?:::[^}:]+)?|config:[^}:]+)(?::(hex|kib|mib))?\}")
_IDENTIFIER = re.compile(r"[A-Za-z_]\w*")


class _Map(Section):
    model: str
    viewer: str
    host: str
    port: int


class _Docs(Section):
    map: _Map


# ---------------------------------------------------------------- values from the sources
def _format(value: int, style: str | None) -> str:
    if style == "hex":                       # 0x1800_0000: groups of four digits, at least eight
        digits = f"{value:08X}"
        return "0x" + "_".join(digits[max(0, i - 4):i] for i in range(len(digits) % 4 or 4, len(digits) + 1, 4))
    if style == "kib":
        return f"{value / 1024:g} KiB"
    if style == "mib":
        return f"{value / (1024 * 1024):g} MiB"
    return str(value)


def substitute(text: str, constants: Mapping[str, int], config: Callable[[str], Any]) -> tuple[str, list[str]]:
    """The model with every ${NAME[:style]} replaced, and the names that do not resolve."""
    problems: list[str] = []

    def lookup(match: re.Match[str]) -> str:
        name, style = match.group(1), match.group(2)
        if name.startswith("config:"):
            try:
                value = config(name.removeprefix("config:"))
            except GpgpuError:
                problems.append(f"${{{name}}}: no such configuration option")
                return match.group(0)
            if isinstance(value, bool):
                return "true" if value else "false"
            return _format(value, style) if isinstance(value, int) and style else str(value)
        if "::" in name:
            found = [name] if name in constants else []
        else:
            found = [key for key in constants if key.rpartition("::")[2] == name]
        if len(found) != 1:
            problems.append(f"${{{name}}}: " + ("no such RTL constant" if not found
                                               else f"ambiguous, write one of {', '.join(sorted(found))}"))
            return match.group(0)
        return _format(constants[found[0]], style)

    lines = [line if line.lstrip().startswith("#") else _VALUE.sub(lookup, line) for line in text.splitlines(keepends=True)]
    return "".join(lines), problems


# ---------------------------------------------------------------- checks
def _bd_cells(design: Path) -> set[str]:
    return set(re.findall(r"create_bd_cell\s+-type\s+\S+\s+-vlnv\s+\S+\s+(\w+)", design.read_text()))


def _modules(source: Path) -> set[str]:
    return set(re.findall(r"^\s*module\s+(\w+)", source.read_text(errors="replace"), re.MULTILINE))


def check_model(root: Any, repo_root: Path, design: Path | None = None) -> list[str]:
    """Every problem in the parsed model: keys, kinds, ids, wires, source paths, RTL module names and bd cells."""
    problems: list[str] = []
    blocks: dict[str, dict] = {}
    cells: dict[str, str] = {}

    def visit(block: Any, path: str) -> None:
        where = path or "the root"
        if not isinstance(block, dict) or "id" not in block:
            problems.append(f"{where}: a block needs an id")
            return
        problems.extend(f"{where}: unknown key {key!r}" for key in block if key not in BLOCK_KEYS)
        kind = block.get("kind", "module")
        if path and kind not in BLOCK_KINDS:
            problems.append(f"{where}: unknown kind {kind!r}")
        if "status" in block and block["status"] not in STATUSES:
            problems.append(f"{where}: unknown status {block['status']!r}")
        if "count" in block and not isinstance(block["count"], int):
            problems.append(f"{where}: count {block['count']!r} is not a number")
        for key in ("rtl", "src"):
            if key in block and not (repo_root / block[key]).exists():
                problems.append(f"{where}: {key} {block[key]} does not exist")
        # A module-like block named by one identifier must be a module of its RTL file.
        rtl, tech = block.get("rtl", ""), str(block.get("tech", ""))
        if rtl.endswith((".sv", ".v")) and kind in ("module", "memory", "regs") and _IDENTIFIER.fullmatch(tech):
            declared = _modules(repo_root / rtl) if (repo_root / rtl).is_file() else set()
            if declared and tech not in declared:
                problems.append(f"{where}: {rtl} declares no module {tech} (it has {', '.join(sorted(declared))})")
        for cell in [block["bd"]] if isinstance(block.get("bd"), str) else block.get("bd") or []:
            if cell in cells:
                problems.append(f"{where}: block design cell {cell} is also {cells[cell]}")
            cells[cell] = where
        for child in block.get("children") or []:
            child_path = f"{path}.{child.get('id')}" if path else str(child.get("id"))
            if child_path in blocks:
                problems.append(f"{child_path}: duplicate block")
            blocks[child_path] = child
            visit(child, child_path)

    visit(root, "")
    blocks[""] = root

    def wires(block: dict, path: str) -> None:
        for spec in block.get("wires") or []:
            ends, kind, *_ = [*map(str.strip, str(spec).split("|")), "data", ""][:3]
            source, arrow, target = ends.partition("->")
            if not arrow:
                problems.append(f"{path or 'the root'}: bad wire {spec!r}")
                continue
            for end in (source.strip(), target.strip()):
                full = f"{path}.{end}" if path else end
                if full not in blocks:
                    problems.append(f"{path or 'the root'}: wire {spec!r} names no block {full}")
            if kind not in WIRE_KINDS:
                problems.append(f"{path or 'the root'}: wire {spec!r} has unknown kind {kind!r}")
        for child in block.get("children") or []:
            wires(child, f"{path}.{child['id']}" if path else child["id"])

    wires(root, "")
    if design is not None:
        actual = _bd_cells(design)
        problems.extend(f"block design cell {cell} ({cells[cell]}) is not in {design.name}" for cell in sorted(set(cells) - actual))
        problems.extend(f"block design cell {cell} of {design.name} is in no block" for cell in sorted(actual - set(cells)))
    return problems


# ---------------------------------------------------------------- the model with its values
class _Resolver:
    """Reads the model and puts in the values from the RTL packages and the configuration."""

    def __init__(self, config: Config, model: Path, design: Path) -> None:
        self._config, self.model, self.design = config, model, design

    def constants(self) -> dict[str, int]:
        from .slang import package_constants  # loaded only when the map is really validated or built

        sources, _ = rtl_sources(self._config, list(self._config.get("hardware.vivado.exclude_sources")))
        return package_constants(sources, rtl_root(self._config))

    def resolved(self) -> tuple[str, list[str]]:
        return substitute(self.model.read_text(), self.constants(), self._config.get)

    def validate(self) -> None:
        text, problems = self.resolved()
        try:
            root = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise GpgpuError(f"{self.model.name}: {error}") from None
        problems += check_model(root, self._config.repo_root, self.design)
        if problems:
            print("\n".join(f"{self.model.name}: {problem}" for problem in problems))
            raise RuntimeError(f"The map's model has {len(problems)} problem(s), listed above")
        print(f"{self.model.relative_to(self._config.repo_root)}: valid")


def _build(resolver: _Resolver, viewer: Path, site: Path) -> None:
    text, problems = resolver.resolved()
    if problems:
        print("\n".join(problems))
        raise RuntimeError(f"{len(problems)} unresolved value(s) in the map's model, listed above")
    if site.exists():
        shutil.rmtree(site)
    shutil.copytree(viewer, site)
    (site / "model.yaml").write_text(text)
    print(f"Built the map in {site}")


class _Handler(http.server.SimpleHTTPRequestHandler):
    """The viewer's files, with model.yaml resolved from the model on every request."""

    def __init__(self, *args: Any, resolver: _Resolver, **kwargs: Any) -> None:
        self._resolver = resolver
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != "/model.yaml":
            return super().do_GET()
        text, problems = self._resolver.resolved()
        for problem in problems:
            self.log_message("%s", problem)
        body = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/yaml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


def _serve(resolver: _Resolver, viewer: Path, host: str, port: int) -> None:
    handler = functools.partial(_Handler, directory=str(viewer), resolver=resolver)
    with http.server.ThreadingHTTPServer((host, port), handler) as server:
        print(f"Serving the map at http://{host}:{port}/ — edit the model and reload the page. Ctrl-C stops it.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


class MapSite:
    def __init__(self, config: Config) -> None:
        settings = config.section("docs", _Docs).map
        model = (config.repo_root / settings.model).resolve()
        self._viewer = (config.repo_root / settings.viewer).resolve()
        design = config.repo_root / "hardware/bd" / f"{config.get('hardware.vivado.bd_name')}.tcl"
        for name, path in (("docs.map.model", model), ("docs.map.viewer", self._viewer)):
            if not path.exists():
                raise GpgpuError(f"{name} not found: {path}")
        self._resolver = _Resolver(config, model, design)
        self._sources = rtl_sources(config, list(config.get("hardware.vivado.exclude_sources")))[0]
        self._host, self._port = settings.host, settings.port
        self._site = config.build_root / "docs/architecture-map"

    def _inputs(self) -> list[Path]:
        return [self._resolver.model, self._resolver.design, *self._sources]

    def validate_map(self) -> Step:
        return Step(self._resolver.validate, inputs=self._inputs(), fingerprint={"check": 2})

    def build_map(self) -> Step:
        return Step(partial(_build, self._resolver, self._viewer, self._site),
                    inputs=[*self._inputs(), *sorted(path for path in self._viewer.rglob("*") if path.is_file())],
                    outputs=(self._site / "index.html", self._site / "model.yaml"), fingerprint={"site": str(self._site)})

    def serve_map(self) -> Step:
        return Step(partial(_serve, self._resolver, self._viewer, self._host, self._port), always_run=True)
