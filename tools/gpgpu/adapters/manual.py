"""ManualSite on Zensical: the user manual, built to static HTML or served while it is written."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from functools import partial
from html.parser import HTMLParser
from importlib.metadata import version
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml
from pydantic import Field

from gpgpu.api import GpgpuError, Step

from .config import Config, Section

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class _Site(Section):
    config: str
    host: str
    port: int = Field(ge=1, le=65535)


class _Loader(yaml.SafeLoader):
    """The site's YAML, without importing what its `!!python/name:` tags name."""


_Loader.add_multi_constructor("tag:yaml.org,2002:python/name:", lambda loader, suffix, node: suffix)


def _nav_pages(nav: Any) -> Iterator[str]:
    """Every local page that the navigation names, in order."""
    if isinstance(nav, str):
        if not urlsplit(nav).scheme:
            yield nav
    elif isinstance(nav, dict):
        for entry in nav.values():
            yield from _nav_pages(entry)
    else:
        for entry in nav or ():
            yield from _nav_pages(entry)


def navigation_problems(docs: Path, nav: Any) -> list[str]:
    """Pages the navigation leaves out, names twice or names without a file: Zensical accepts all three."""
    named = list(_nav_pages(nav))
    written = {path.relative_to(docs).as_posix() for path in docs.rglob("*.md")}
    return [*(f"{page}: not in the navigation" for page in sorted(written - set(named))),
            *(f"{page}: in the navigation, but there is no such page" for page in sorted(set(named) - written)),
            *(f"{page}: in the navigation more than once" for page in sorted({page for page in named if named.count(page) > 1}))]


class _Targets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.found += [value for name, value in attrs if name in ("href", "src") and value]


def broken_targets(site: Path) -> list[str]:
    """Local links, images, styles and scripts of the built pages that lead to no file."""
    problems = []
    for page in sorted(site.rglob("*.html")):
        parser = _Targets()
        parser.feed(page.read_text(encoding="utf-8"))
        for target in dict.fromkeys(parser.found):
            parts = urlsplit(target)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            path = unquote(parts.path)
            file = site / path.lstrip("/") if path.startswith("/") else page.parent / path
            if not (file / "index.html" if file.is_dir() else file).is_file():
                problems.append(f"{page.relative_to(site).as_posix()}: {target} leads to no file")
    return problems


def _report(problems: list[str]) -> None:
    if problems:
        print("\n".join(problems))
        raise RuntimeError(f"The manual has {len(problems)} problem(s), listed above")


def _build(command: list[str], root: Path, docs: Path, nav: Any, site: Path) -> None:
    _report(navigation_problems(docs, nav))
    if site.exists():
        shutil.rmtree(site)  # pages that were renamed or removed
    result = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output = _ANSI.sub("", result.stdout)
    print(output.partition("Traceback (most recent call last)")[0].rstrip())
    if result.returncode:
        raise RuntimeError("Zensical rejected the manual, see above")
    _report(broken_targets(site))
    print(f"Built the manual in {site}")


def _serve(command: list[str], root: Path) -> None:
    try:
        subprocess.run(command, cwd=root, check=True)
    except KeyboardInterrupt:
        pass


class ZensicalManual:
    def __init__(self, config: Config) -> None:
        settings = config.section("docs.site", _Site)
        self._root = config.repo_root
        self._file = self._root / settings.config
        if not self._file.is_file():
            raise GpgpuError(f"docs.site.config not found: {self._file}")
        try:
            site = yaml.load(self._file.read_text(encoding="utf-8"), _Loader)
        except yaml.YAMLError as error:
            raise GpgpuError(f"Invalid YAML in {self._file}: {error}") from None
        self._docs, self._site = self._root / site["docs_dir"], self._root / site["site_dir"]
        self._nav = site["nav"]
        self._address = f"{settings.host}:{settings.port}"

    def _command(self, *arguments: str) -> list[str]:
        return [sys.executable, "-m", "zensical", *arguments, "--config-file", str(self._file)]

    def problems(self) -> list[str]:
        return navigation_problems(self._docs, self._nav)

    def build(self) -> Step:
        command = self._command("build", "--strict", "--clean")
        return Step(partial(_build, command, self._root, self._docs, self._nav, self._site),
                    inputs=(self._file, *sorted(path for path in self._docs.rglob("*") if path.is_file()), Path(__file__)),
                    outputs=(self._site / "index.html",), fingerprint={"zensical": version("zensical")})

    def serve(self) -> Step:
        return Step(partial(_serve, self._command("serve", "--dev-addr", self._address), self._root), always_run=True)
