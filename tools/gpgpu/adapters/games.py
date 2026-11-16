"""GameFlow: games whose logic runs on the ARM and whose drawing runs on the GPU (software/games).

A game is a directory with a manifest, game.yaml. This module reads the manifests, and builds
what is the same for the board and for the PC simulation: the fetched upstream source, the
generated files, and the simulation itself. The board build is PlatformFlow's.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import AfterValidator, NonNegativeInt, PositiveInt, StringConstraints, ValidationError

from gpgpu.api import GpgpuError, Step

from .config import Config, Section
from .design import architecture, program_names, program_output
from .host_headers import args_window
from .tools import run

CName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
Define = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*(=[A-Za-z0-9_.+-]*)?$")]
Commit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


def _inside(path: str) -> str:
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError("must be a path inside the directory, without . or .. components")
    return path


Relative = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_+-][A-Za-z0-9_./+-]*$"), AfterValidator(_inside)]

_MANIFEST = "game.yaml"
_REPLAY = Path(__file__).parents[2] / "tests/kernel_replay.py"
_MODEL = _REPLAY.with_name("gpgpu_model.py")


# The manifest: what a game is, committed next to its code.

class _Upstream(Section):
    url: str
    commit: Commit
    directory: Relative    # where its C files are
    sources: list[Relative]  # the ones the game is built from, in `directory`


class _Asset(Section):
    description: str  # what the file is and where to get it: shown when it is not configured


class _Verify(Section):
    runs: list[PositiveInt]  # runs of the kernel in the simulation, counted from 1


class _Manifest(Section):
    description: str
    kernel: str                     # the program of software/programs that is its GPU side
    upstream: _Upstream | None = None
    sources: list[Relative]         # its own C files, from its directory
    include: list[Relative] = []
    defines: list[Define] = []
    wrap: list[CName] = []          # functions of the upstream source replaced at link time
    assets: dict[CName, _Asset] = {}
    arguments: list[str] = []       # of the game; {name} is the file name of asset `name`
    verify: _Verify | None = None


# The configuration: what a user or a machine chooses.

class _Size(Section):
    width: PositiveInt
    height: PositiveInt


class _Input(Section):
    hold_ms: PositiveInt


class _Memory(Section):
    heap_mb: PositiveInt
    stack_kb: PositiveInt


class _Simulation(Section):
    frames: PositiveInt
    dump_every: PositiveInt
    arguments: list[str]


class _Platform(Section):
    output: _Size
    input: _Input
    stats_seconds: NonNegativeInt
    memory: _Memory
    simulation: _Simulation


class _Settings(Section):
    assets: dict[CName, str | None]
    args: list[str]
    defines: dict[CName, int | str]


class _Games(Section):
    platform: _Platform
    settings: dict[str, _Settings]


def games_root(config: Config) -> Path:
    return config.repo_root / "software/games"


def game_names(config: Config) -> list[str]:
    root = games_root(config)
    return sorted(path.name for path in root.iterdir() if (path / _MANIFEST).is_file()) if root.is_dir() else []


def game_output(config: Config, game: str, *parts: str) -> Path:
    return config.build_root.joinpath("software/games", game, *parts)


def _manifest(config: Config, game: str) -> _Manifest:
    path = games_root(config) / game / _MANIFEST
    try:
        return _Manifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except yaml.YAMLError as error:
        raise GpgpuError(f"Invalid YAML in {path}: {error}") from None
    except ValidationError as error:
        first = error.errors()[0]
        raise GpgpuError(f"{path}: {'.'.join(map(str, first['loc']))}: {first['msg']}") from None


def _settings(config: Config, game: str) -> _Settings:
    settings = config.section("software.games", _Games).settings
    if game not in settings:
        raise GpgpuError(f"software.games.settings.{game} is missing",
                         "Add the game's settings to config/profiles/default.yaml: assets, args and defines")
    return settings[game]


@dataclass(frozen=True)
class GameBuild:
    """What a game is built from. The board build and the simulation differ only in their platform."""

    name: str
    kernel: str
    upstream: tuple[Path, ...]    # fetched; compiled as it is
    sources: tuple[Path, ...]     # the game's own files and the shared platform
    generated: tuple[Path, ...]   # gp_assets.c
    board: tuple[Path, ...]       # platform/xc7z020, the host driver and the kernel image
    simulation: tuple[Path, ...]  # platform/sim
    kernel_source: Path           # compiled natively into the simulation
    include: tuple[Path, ...]
    defines: tuple[str, ...]
    wraps: tuple[str, ...]
    headers: tuple[Path, ...]     # of everything above that is committed
    fetched: Path | None          # written when the upstream source is in place
    heap_bytes: int
    stack_bytes: int

    @property
    def link_flags(self) -> list[str]:
        return [f"-Wl,--wrap={name}" for name in self.wraps]


def game_build(config: Config, game: str) -> GameBuild:
    manifest, settings = _manifest(config, game), _settings(config, game)
    platform = config.section("software.games", _Games).platform
    if manifest.kernel not in program_names(config):
        raise GpgpuError(f"{games_root(config) / game / _MANIFEST}: kernel {manifest.kernel!r} is not a program",
                         f"Programs: {', '.join(program_names(config))}")
    directory, shared = games_root(config) / game, games_root(config) / "platform"
    programs, host = config.repo_root / "software/programs", config.repo_root / "software/host/xc7z020"
    generated = game_output(config, game, "generated")
    upstream_root = game_output(config, game, "upstream")
    upstream: tuple[Path, ...] = ()
    fetched = None
    include = [generated, shared, programs, programs / manifest.kernel, host, *(directory / item for item in manifest.include)]
    if manifest.upstream is not None:
        upstream = tuple(upstream_root / manifest.upstream.directory / source for source in manifest.upstream.sources)
        include.append(upstream_root / manifest.upstream.directory)
        fetched = upstream_root / ".fetched"
    sources = [directory / source for source in manifest.sources]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        raise GpgpuError(f"{directory / _MANIFEST}: sources not found: {', '.join(missing)}")
    headers = {header for folder in (shared, shared / "xc7z020", shared / "sim", programs, programs / manifest.kernel,
                                     *(directory / item for item in manifest.include)) for header in folder.glob("*.h")}
    # Of the host driver, what a game includes; gpgpu_platform.h is `software:host:platform`'s.
    headers |= {host / "gpgpu_platform.h", host / "gpgpu_driver.h", host / "gpgpu_display.h"}
    defines = [*manifest.defines, *(f"{name}={value}" for name, value in settings.defines.items())]
    return GameBuild(
        name=game, kernel=manifest.kernel, upstream=upstream,
        sources=(*sources, *sorted(shared.glob("*.c"))), generated=(generated / "gp_assets.c",),
        board=(*sorted((shared / "xc7z020").glob("*.c")), host / "gpgpu_driver.c", host / "gpgpu_display.c",
               generated / "gp_kernel.c"),
        simulation=tuple(sorted((shared / "sim").glob("*.c"))),
        kernel_source=programs / manifest.kernel / f"{manifest.kernel}.c",
        include=tuple(include), defines=tuple(defines), wraps=tuple(manifest.wrap), headers=tuple(sorted(headers)),
        fetched=fetched,
        heap_bytes=platform.memory.heap_mb << 20, stack_bytes=platform.memory.stack_kb << 10)


def _write_if_changed(output: Path, text: str) -> None:
    """Generated sources keep their date when nothing changed, so nothing recompiles."""
    output.parent.mkdir(parents=True, exist_ok=True)
    if not output.is_file() or output.read_text(encoding="utf-8") != text:
        output.write_text(text, encoding="utf-8")


def _c_string(text: str) -> str:
    return json.dumps(text)  # for the ASCII these strings are, JSON's escapes are C's


def _fetch(git: str, upstream: _Upstream, directory: Path, marker: Path) -> None:
    """A shallow clone of exactly the pinned commit, left as plain files."""
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    for arguments in (["init", "--quiet"], ["remote", "add", "origin", upstream.url],
                      ["fetch", "--quiet", "--depth", "1", "origin", upstream.commit],
                      ["checkout", "--quiet", "--detach", "FETCH_HEAD"]):
        run([git, "-C", str(directory), *arguments])
    head = subprocess.run([git, "-C", str(directory), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    if head != upstream.commit:
        raise RuntimeError(f"{upstream.url}: fetched {head}, not the pinned {upstream.commit}")
    missing = [source for source in upstream.sources if not (directory / upstream.directory / source).is_file()]
    if missing:
        raise FileNotFoundError(f"{upstream.url} at {upstream.commit} has no {', '.join(missing)}")
    shutil.rmtree(directory / ".git")
    marker.write_text(f"{upstream.url} {upstream.commit}\n", encoding="utf-8")
    print(f"Fetched {upstream.url} at {upstream.commit[:12]} into {directory}", flush=True)


def _asset_files(config: Config, game: str, manifest: _Manifest, settings: _Settings) -> dict[str, Path | None]:
    """Each asset of the manifest and the file configured for it, relative paths from the repository."""
    return {name: (config.repo_root / Path(settings.assets[name]).expanduser()).resolve() if settings.assets.get(name) else None
            for name in manifest.assets}


def _require_assets(game: str, manifest: _Manifest, files: dict[str, Path | None]) -> dict[str, Path]:
    for name, path in files.items():
        option = f"software.games.settings.{game}.assets.{name}"
        if path is None:
            raise FileNotFoundError(f"{option} is not set. {manifest.assets[name].description.strip()} "
                                    f"Set it in config/local.yaml or with --set {option}=<path>")
        if not path.is_file():
            raise FileNotFoundError(f"{option}: {path} is not a file")
    return {name: path for name, path in files.items() if path is not None}


def _write_config(output: Path, game: str, manifest: _Manifest, settings: _Settings, platform: _Platform,
                  files: dict[str, Path | None]) -> None:
    names = {name: path.name for name, path in _require_assets(game, manifest, files).items()}
    try:
        arguments = [game, *(argument.format(**names) for argument in manifest.arguments), *settings.args]
    except (KeyError, IndexError, ValueError) as error:
        raise ValueError(f"{game}/{_MANIFEST}: arguments name an asset the manifest does not have ({error})") from None
    lines = ["/* Generated by `gpgpu software games:<game>:configure`",
             f" * from software/games/{game}/{_MANIFEST} and software.games in the configuration.",
             " * Do not edit: change those and regenerate.",
             " */", "#ifndef GP_CONFIG_H", "#define GP_CONFIG_H", "",
             f"#define GP_GAME_NAME      {_c_string(game)}",
             "/* The game's arguments: its manifest's, then software.games.settings.<game>.args. */",
             f"#define GP_GAME_ARGV      {{ {', '.join([*map(_c_string, arguments), 'NULL'])} }}",
             "/* The picture on the display, in pixels (software.games.platform.output). */",
             f"#define GP_OUTPUT_WIDTH   {platform.output.width}u",
             f"#define GP_OUTPUT_HEIGHT  {platform.output.height}u",
             "/* How long a key of a UART terminal counts as held (software.games.platform.input.hold_ms). */",
             f"#define GP_INPUT_HOLD_MS  {platform.input.hold_ms}u",
             "/* Seconds between frame-rate reports, 0 for none (software.games.platform.stats_seconds). */",
             f"#define GP_STATS_SECONDS  {platform.stats_seconds}u",
             "/* What the board build links with (software.games.platform.memory). */",
             f"#define GP_HEAP_BYTES     {platform.memory.heap_mb << 20}u",
             f"#define GP_STACK_BYTES    {platform.memory.stack_kb << 10}u",
             "", "#endif /* GP_CONFIG_H */", ""]
    _write_if_changed(output, "\n".join(lines))


def _write_assets(output: Path, game: str, manifest: _Manifest, files: dict[str, Path | None]) -> None:
    """A C file that links each data file into the game with .incbin, and names it."""
    paths = _require_assets(game, manifest, files)
    lines = ["/* Generated by `gpgpu software games:<game>:assets`",
             f" * from software.games.settings.{game}.assets. Do not edit.",
             " */", '#include "gp_port.h"', ""]
    for index, (name, path) in enumerate(paths.items()):
        if '"' in str(path) or "\\" in str(path) or "\n" in str(path):
            raise ValueError(f"software.games.settings.{game}.assets.{name}: the path cannot be quoted in assembly: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        symbol = f"gp_asset_{index}"
        # The size and digest make this file change, and so recompile, when the data does.
        lines += [f"/* {name}: {path.name}, {path.stat().st_size} bytes, sha256 {digest} */",
                  f'__asm__(".section .rodata.{symbol},\\"a\\",%progbits\\n"',
                  '        ".balign 16\\n"',
                  f'        ".global {symbol}_start\\n"',
                  f'        "{symbol}_start:\\n"',
                  f'        ".incbin \\"{path}\\"\\n"',
                  f'        ".global {symbol}_end\\n"',
                  f'        "{symbol}_end:\\n"',
                  '        ".previous\\n");',
                  f"extern const uint8_t {symbol}_start[], {symbol}_end[];", ""]
    entries = [f"    {{ {_c_string(path.name)}, gp_asset_{index}_start, gp_asset_{index}_end }}," for index, path in enumerate(paths.values())]
    lines += ["const gp_asset_file_t gp_assets[] = {", *(entries or ["    { 0, 0, 0 },"]), "};",
              f"const unsigned int gp_asset_count = {len(paths)};", ""]
    _write_if_changed(output, "\n".join(lines))


def _write_kernel(output: Path, kernel: str, nm_command: list[str], memory: Path, cores: int) -> None:
    # gpgpu.ld has already checked that the image fits IMEM.
    image = [int(line, 16) for line in memory.read_text(encoding="utf-8").split()]
    args_word, args_words = args_window(nm_command)
    lines = ["/* Generated by `gpgpu software games:<game>:kernel`",
             f" * from the RISC-V build of software/programs/{kernel}. Do not edit.",
             " */", '#include "gp_port.h"', "", "/* IMEM image, from word 0. */", "const uint32_t gp_kernel_image[] = {",
             *(f"    {', '.join(f'0x{word:08X}u' for word in image[i:i + 6])}," for i in range(0, len(image), 6)), "};",
             f"const unsigned int gp_kernel_words = {len(image)};",
             "/* GPGPU_ARGS: its first DMEM word and its size in words (gpgpu.ld). */",
             f"const unsigned int gp_kernel_args_word = {args_word};",
             f"const unsigned int gp_kernel_args = {args_words};",
             "/* The lanes it was compiled for (architecture.num_cores). */",
             f"const unsigned int gp_kernel_lanes = {cores};", ""]
    _write_if_changed(output, "\n".join(lines))


def _compile(compiler: str, flags: list[str], source: Path, obj: Path) -> None:
    result = subprocess.run([compiler, *flags, "-c", str(source), "-o", str(obj)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{source.name} did not compile:\n{result.stderr}")
    if result.stderr:
        sys.stderr.write(result.stderr)


def _build_simulation(compiler: str, build: GameBuild, flags: list[str], cores: int, executable: Path) -> None:
    """Every source to its own object, in parallel; then link with the game's --wrap list."""
    objects = executable.parent / "obj"
    shutil.rmtree(objects, ignore_errors=True)
    objects.mkdir(parents=True)
    common = [*flags, f"-DGPGPU_NUM_CORES={cores}", *(f"-D{define}" for define in build.defines),
              *(f"-I{directory}" for directory in build.include)]
    jobs = [(source, [*common, "-w"]) for source in build.upstream]  # not ours to tidy
    jobs += [(source, [*common, "-Wall", "-Wextra"]) for source in (*build.sources, *build.generated, *build.simulation)]
    jobs.append((build.kernel_source, [*common, "-Wall", "-DGPGPU_NATIVE_LIB"]))
    compiled = [(source, objects / f"{index:03d}_{source.stem}.o", options) for index, (source, options) in enumerate(jobs)]
    with ThreadPoolExecutor() as pool:
        for future in [pool.submit(_compile, compiler, options, source, obj) for source, obj, options in compiled]:
            future.result()
    run([compiler, *flags, *(str(obj) for _, obj, _ in compiled), *build.link_flags, "-lm", "-o", str(executable)])
    print(f"Built {executable}", flush=True)


def _run_simulation(executable: Path, simulation: _Simulation, frames: Path) -> None:
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir(parents=True)
    command = [str(executable), "--frames", str(simulation.frames), "--dump", str(frames),
               "--dump-every", str(simulation.dump_every), "--", *simulation.arguments]
    run(command, cwd=executable.parent)
    print(f"{len(list(frames.glob('*.ppm')))} frames of {simulation.frames} written to {frames}", flush=True)


def _verify(python: str, executable: Path, runs: list[int], nm_command: list[str], image: Path, constants: Path,
            cores: int, captures: Path) -> None:
    """Capture each run in the simulation, then replay the kernel's RISC-V image on the GPGPU model."""
    args_word, _ = args_window(nm_command)
    for index in runs:
        capture = captures / f"run_{index}"
        shutil.rmtree(capture, ignore_errors=True)
        capture.mkdir(parents=True)
        run([str(executable), "--capture", str(index), str(capture)], cwd=executable.parent)
        if not (capture / "args.txt").is_file():
            raise RuntimeError(f"the simulation ended before run {index} of the kernel")
        run([python, str(_REPLAY), "--image", str(image), "--capture", str(capture), "--constants", str(constants),
             "--cores", str(cores), "--args-word", str(args_word)])
        shutil.rmtree(capture)  # tens of megabytes each


def _remove(directory: Path) -> None:
    shutil.rmtree(directory, ignore_errors=True)


class Games:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._cores = architecture(config).num_cores
        self._platform = config.section("software.games", _Games).platform
        self._names = game_names(config)
        for game in self._names:  # a broken manifest or missing settings fail here, by name
            game_build(config, game)
        riscv_cc = config.tool("riscv_gcc")
        self._nm = f"{riscv_cc.removesuffix('gcc')}nm"

    def games(self) -> list[str]:
        return self._names

    def kernel(self, game: str) -> str:
        return _manifest(self._config, game).kernel

    def _generated(self, game: str, name: str) -> Path:
        return game_output(self._config, game, "generated", name)

    def _files(self, game: str) -> dict[str, Path | None]:
        return _asset_files(self._config, game, _manifest(self._config, game), _settings(self._config, game))

    def fetch(self, game: str) -> Step:
        upstream = _manifest(self._config, game).upstream
        build = game_build(self._config, game)
        if upstream is None or build.fetched is None:
            return Step()  # the game is all in the repository
        return Step(partial(_fetch, self._config.tool("git"), upstream, build.fetched.parent, build.fetched),
                    outputs=(build.fetched,), fingerprint=upstream.model_dump())

    def configure(self, game: str) -> Step:
        manifest, settings, files = _manifest(self._config, game), _settings(self._config, game), self._files(game)
        output = self._generated(game, "gp_config.h")
        return Step(partial(_write_config, output, game, manifest, settings, self._platform, files),
                    inputs=(games_root(self._config) / game / _MANIFEST, Path(__file__)), outputs=(output,),
                    fingerprint={"settings": settings.model_dump(), "platform": self._platform.model_dump(),
                                 "files": {name: str(path) for name, path in files.items()}})

    def assets(self, game: str) -> Step:
        manifest, files = _manifest(self._config, game), self._files(game)
        output = self._generated(game, "gp_assets.c")
        present = [path for path in files.values() if path is not None and path.is_file()]
        return Step(partial(_write_assets, output, game, manifest, files),
                    inputs=(games_root(self._config) / game / _MANIFEST, Path(__file__), *present), outputs=(output,),
                    fingerprint={"files": {name: str(path) for name, path in files.items()}})

    def kernel_image(self, game: str) -> Step:
        kernel = self.kernel(game)
        elf = program_output(self._config, kernel, ".elf")
        memory = program_output(self._config, kernel, "_instructions.mem")
        output = self._generated(game, "gp_kernel.c")
        return Step(partial(_write_kernel, output, kernel, [self._nm, str(elf)], memory, self._cores),
                    inputs=(elf, memory, Path(__file__)), outputs=(output,),
                    fingerprint={"kernel": kernel, "cores": self._cores})

    def _simulation(self, game: str) -> Path:
        return game_output(self._config, game, "sim", f"{game}_sim")

    def build_simulation(self, game: str) -> Step:
        build, executable = game_build(self._config, game), self._simulation(game)
        flags = [str(self._config.get("software.programs.optimization")), "-g"]
        compiler = self._config.tool("native_cc")
        return Step(partial(_build_simulation, compiler, build, flags, self._cores, executable),
                    inputs=(*build.sources, *build.simulation, *build.headers, build.kernel_source,
                            *((build.fetched,) if build.fetched else ()),
                            *build.generated, self._generated(game, "gp_config.h"), Path(__file__)),
                    outputs=(executable,),
                    fingerprint={"compiler": compiler, "flags": flags, "cores": self._cores, "defines": list(build.defines),
                                 "wraps": list(build.wraps), "upstream": [str(path) for path in build.upstream]})

    def run_simulation(self, game: str) -> Step:
        executable = self._simulation(game)
        return Step(partial(_run_simulation, executable, self._platform.simulation, executable.parent / "frames"),
                    always_run=True)

    def verify(self, game: str) -> Step:
        manifest, kernel, executable = _manifest(self._config, game), self.kernel(game), self._simulation(game)
        if manifest.verify is None:
            return Step()
        elf = program_output(self._config, kernel, ".elf")
        image = program_output(self._config, kernel, "_instructions.mem")
        constants = self._config.build_root / "tests/rtl/rtl_constants.txt"
        return Step(partial(_verify, self._config.tool("python"), executable, manifest.verify.runs, [self._nm, str(elf)],
                            image, constants, self._cores, executable.parent / "capture"),
                    inputs=(executable, elf, image, constants, _REPLAY, _MODEL),
                    fingerprint={"runs": manifest.verify.runs, "cores": self._cores})

    def clean(self, game: str) -> Step:
        return Step(partial(_remove, game_output(self._config, game)), always_run=True)
