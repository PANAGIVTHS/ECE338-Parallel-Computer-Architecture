"""Toolchain on GCC: the programs of software/programs (kernels, simulator and A9 builds) and the host headers."""
from __future__ import annotations

import re
import shutil
import subprocess
from functools import partial
from pathlib import Path
from typing import Literal

from pydantic import NonNegativeInt, PositiveInt

from gpgpu.api import GpgpuError, Step

from . import host_headers
from .config import Config, Section
from .design import (architecture, axi_address, host_map, memory_layout, program_names, program_output,
                     rtl_constants_path, vitis_workspace)
from .kernel_elf import write_linker_layout
from .runtime_build import check_cases, generate_kernels, write_hw_header, write_module
from .tools import run

# -fno-jump-tables: a switch's table would be .rodata in GMEM, a DDR load before
# every indirect jump; a kernel that wants one asks with optimize("jump-tables").
# x31 holds the lane index; x3 (gp) and x4 (tp) the block index of the runtime's
# block loop (docs/runtime-spec.md, section 6.2), so no code may allocate them.
# Shared memory starts at address 0, so a null pointer is a valid shared address:
# -fno-delete-null-pointer-checks keeps GCC from treating a load from it as undefined.
_RISCV_CFLAGS = ("-ffreestanding", "-fno-delete-null-pointer-checks", "-fno-builtin", "-fomit-frame-pointer", "-ffixed-x31", "-ffixed-x3", "-ffixed-x4",
                 "-ffunction-sections",
                 "-fdata-sections", "-msmall-data-limit=0", "-mno-relax", "-fno-jump-tables")
_INSTRUCTION = re.compile(r"^\s*[0-9a-fA-F]+:\s+(\S+)(?:\s+(.*))?$")


class _Programs(Section):
    optimization: Literal["-O0", "-O1", "-O2", "-O3", "-Os", "-Og"]


class _Riscv(Section):
    march: str
    abi: str


class _Runtime(Section):
    launch_timeout_ms: NonNegativeInt
    arguments: list[str]
    board_stack_bytes: PositiveInt
    board_heap_bytes: PositiveInt



def _c_string(text: str) -> str:
    """A C string literal of printable ASCII `text`."""
    if not all(" " <= character <= "~" for character in text):
        raise GpgpuError(f"software.runtime.arguments: {text!r} must be printable ASCII for a boot program")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _run_program(command: list[str], cwd: Path) -> None:
    """Run a host program in the simulator; its status is the task's."""
    cwd.mkdir(parents=True, exist_ok=True)
    status = subprocess.run(command, cwd=cwd).returncode
    if status != 0:
        raise RuntimeError(f"{Path(command[0]).name} exited with status {status}")


def _instructions(listing: Path) -> list[tuple[str, str]]:
    """(hex code, assembly) of each instruction line in an objdump listing."""
    matches = map(_INSTRUCTION.match, listing.read_text(encoding="utf-8").splitlines())
    return [(match[1], match[2] or "") for match in matches if match]


def _write_disassembly(command: list[str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        subprocess.run(command, check=True, stdout=stream)
    mnemonics = sorted({assembly.split(maxsplit=1)[0] for _, assembly in _instructions(output) if assembly})
    print("---------------------------------------------------")
    print("Instruction Set used in program (RISC-V):")
    print(" ".join(mnemonics))
    print("---------------------------------------------------")


def _write_assembly(listing: Path, output: Path) -> None:
    output.write_text("".join(f"{assembly}\n" for _, assembly in _instructions(listing)), encoding="utf-8")


def _remove(directory: Path) -> None:
    if directory.exists():
        shutil.rmtree(directory)


class GccToolchain:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._root = config.repo_root / "software/programs"
        self._cores = architecture(config).num_cores
        self._memory = memory_layout(config)
        stride = self._memory.stack_bytes_per_lane
        # The memory ABI for every build of a program: gpgpu_config.h documents each.
        self._defines = (f"-DGPGPU_NUM_CORES={self._cores}", f"-DGPGPU_STACK_STRIDE={stride}",
                         f"-DGPGPU_STACK_SHIFT={stride.bit_length() - 1}")
        self._layout = config.build_root / "software/programs/linker_layout.ld"
        self._optimization = config.section("software.programs", _Programs).optimization
        self._riscv = config.section("software.riscv", _Riscv)
        self._native_cc, self._riscv_cc = config.tool("native_cc"), config.tool("riscv_gcc")
        if not self._riscv_cc.endswith("-gcc"):
            raise GpgpuError("tools.riscv_gcc.command must end in '-gcc', so objdump and nm can be derived from it")
        self._runtime = config.repo_root / "software/runtime"
        self._runtime_build = config.build_root / "software/runtime"
        self._runtime_settings = config.section("software.runtime", _Runtime)
        self._ddr_enable = architecture(config).ddr_enable

    def _binutil(self, tool: str) -> str:
        return f"{self._riscv_cc[:-3]}{tool}"

    def _out(self, program: str, suffix: str) -> Path:
        return program_output(self._config, program, suffix)

    def _sources(self, program: str) -> tuple[Path, list[Path]]:
        directory = self._root / program
        return directory / f"{program}.c", sorted({*self._root.glob("*.h"), *directory.glob("*.h")})

    def programs(self) -> list[str]:
        return program_names(self._config)

    # ---- A program: <p>.c with GPGPU_GLOBAL kernels and host.c (docs/runtime-spec.md) ----

    def _riscv_command(self) -> list[str]:
        return [self._riscv_cc, self._optimization, f"-march={self._riscv.march}", f"-mabi={self._riscv.abi}",
                *self._defines, *_RISCV_CFLAGS]

    def _runtime_includes(self, program: str) -> list[str]:
        return [f"-I{self._runtime / 'include'}", f"-I{self._runtime / 'device'}", f"-I{self._root}",
                f"-I{self._root / program}"]

    def _runtime_sources(self, *parts: str) -> list[Path]:
        return sorted(path for part in parts for path in (self._runtime / part).glob("*.[ch]"))

    def _header(self, program: str) -> Path | None:
        header = self._root / program / f"{program}.h"
        return header if header.is_file() else None

    def generate_kernels(self, program: str) -> Step:
        source, headers = self._sources(program)
        outputs = [self._out(program, suffix) for suffix in ("_scan.o", "_aux.txt", "_entry.c", "_kernels.h", "_scan.json")]
        command = [*self._riscv_command(), *self._runtime_includes(program)]
        generator = Path(__file__).with_name("runtime_build.py")
        return Step(partial(generate_kernels, command, source, self._header(program), program, *outputs),
                    inputs=(source, *headers, *self._runtime_sources("include", "device"), generator),
                    outputs=tuple(outputs), fingerprint={"command": command})

    def build_module(self, program: str) -> Step:
        elf, scan, module = self._out(program, ".elf"), self._out(program, "_scan.json"), self._out(program, "_module.c")
        constants = rtl_constants_path(self._config)
        settings = {"num_cores": self._cores, "stack_bytes": self._memory.stack_bytes_per_lane}
        builder = Path(__file__).with_name("runtime_build.py")
        return Step(partial(write_module, elf, scan, constants, settings, module), inputs=(elf, scan, constants, builder),
                    outputs=(module,), fingerprint=settings)

    def hardware_header(self) -> Step:
        constants, output = rtl_constants_path(self._config), self._runtime_build / "gpgpu_hw.h"
        settings = {"num_cores": self._cores, "ddr_enable": self._ddr_enable}
        builder = Path(__file__).with_name("runtime_build.py")
        return Step(partial(write_hw_header, constants, settings, output), inputs=(constants, builder),
                    outputs=(output,), fingerprint=settings)

    def _simulator_command(self, sources: list[Path], includes: list[Path], executable: Path) -> list[str]:
        timeout = self._runtime_settings.launch_timeout_ms
        return [self._native_cc, "-std=gnu11", "-O2", "-g", "-Wall", "-Wextra", *self._defines,
                f"-DGPGPU_LAUNCH_TIMEOUT_MS={timeout}u", *(f"-I{path}" for path in includes),
                "-o", str(executable), *map(str, sources)]

    def build_simulator_program(self, program: str) -> Step:
        executable = self._out(program, "_sim")
        sources = [self._root / program / "host.c", self._runtime / "host/gpgpu_runtime.c",
                   self._runtime / "host/sim/gpgpu_backend_sim.c", self._runtime / "sim/gpgpu_sim.c",
                   self._out(program, "_module.c")]
        includes = [self._runtime / "include", self._runtime / "host", self._runtime / "sim", self._runtime_build,
                    self._root, self._root / program, executable.parent]
        command = self._simulator_command(sources, includes, executable)
        headers = [*self._runtime_sources("include", "host", "sim"), *(self._root / program).glob("*.h"),
                   self._out(program, "_kernels.h"), self._runtime_build / "gpgpu_hw.h", self._root / "gpgpu_config.h"]
        return Step(partial(run, command, creates=executable.parent), inputs=(*sources, *headers), outputs=(executable,),
                    fingerprint={"command": command})

    def run_simulator_program(self, program: str) -> Step:
        executable = self._out(program, "_sim")
        command = [str(executable), *self._runtime_settings.arguments]
        return Step(partial(_run_program, command, executable.parent / "sim"), always_run=True)

    def build_board_program(self, program: str, boot: bool = False) -> Step:
        """The host program for the A9, linked against the platform's standalone BSP.

        `boot`: the build that runs in place of the monitor (software.host.boot_program), with
        software.runtime.arguments built in."""
        platform, domain = (str(self._config.get(f"hardware.vitis.{key}")) for key in ("platform_name", "domain"))
        bsp = vitis_workspace(self._config) / platform / "export" / platform / "sw" / domain
        host = self._config.repo_root / "software/host/xc7z020"
        suffix = "_boot_a9" if boot else "_a9"
        executable, script = self._out(program, f"{suffix}.elf"), self._out(program, f"{suffix}.ld")
        arguments = [program, *self._runtime_settings.arguments] if boot else []
        boot_header = executable.parent / "boot" / "gpgpu_boot_args.h"
        sources = [self._root / program / "host.c", self._runtime / "host/gpgpu_runtime.c",
                   self._runtime / "host/xc7z020/gpgpu_backend_xc7z020.c", host / "gpgpu_driver.c", host / "gpgpu_display.c",
                   self._out(program, "_module.c")]
        includes = [self._runtime / "include", self._runtime / "host", host, self._root, self._root / program,
                    executable.parent, *([boot_header.parent] if boot else []), bsp / "include"]
        base, _ = axi_address(self._config)
        flags = [*(["-DGPGPU_BOOT_PROGRAM"] if boot else []), "-DSDT", f"-DGPGPU_BASEADDR={base}", "-mcpu=cortex-a9", "-mfpu=vfpv3", "-mfloat-abi=hard",
                 f"-specs={bsp / 'Xilinx.spec'}"]
        command = [self._config.tool("arm_gcc"), "-std=gnu11", "-O2", "-g", "-Wall", "-Wextra", *flags, *self._defines,
                   f"-DGPGPU_LAUNCH_TIMEOUT_MS={self._runtime_settings.launch_timeout_ms}u",
                   *(f"-I{path}" for path in includes), "-o", str(executable), *map(str, sources),
                   f"-Wl,-T,{script}", f"-L{bsp / 'lib'}", "-Wl,--start-group,-lxilstandalone,-lxiltimer,-lxil,-lgcc,-lc,--end-group"]
        template = self._runtime / "host/xc7z020/lscript.ld.in"
        constants = rtl_constants_path(self._config)
        # The programs' DDR (software.host): above the monitor, up to FB0.
        region = host_map(self._config)
        sizes = {"stack": self._runtime_settings.board_stack_bytes, "heap": self._runtime_settings.board_heap_bytes,
                 "origin": region["program_base"], "length": region["program_end"] - region["program_base"]}

        def build() -> None:
            text = template.read_text(encoding="utf-8")
            for key, value in {"ORIGIN": sizes["origin"], "LENGTH": sizes["length"],
                               "STACK_SIZE": sizes["stack"], "HEAP_SIZE": sizes["heap"]}.items():
                text = text.replace(f"@{key}@", f"0x{value:X}")
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(text, encoding="utf-8")
            if boot:
                boot_header.parent.mkdir(parents=True, exist_ok=True)
                boot_header.write_text("/* Generated: the boot program's argv (software.runtime.arguments). */\n"
                                       f"#define GPGPU_BOOT_ARGUMENTS {', '.join(map(_c_string, arguments))}\n",
                                       encoding="utf-8")
            run(command)

        board_headers = [host / name for name in ("gpgpu_driver.h", "gpgpu_display.h", "gpgpu_boot.h", "gpgpu_platform.h")]
        headers = [*self._runtime_sources("include", "host"), *board_headers, *(self._root / program).glob("*.h"),
                   self._out(program, "_kernels.h"), self._root / "gpgpu_config.h"]
        return Step(build, inputs=(*sources, *headers, template, constants, bsp / "lib/libxil.a"),
                    outputs=(executable,), fingerprint={"command": command, "sizes": sizes, "arguments": arguments})

    def runtime_check(self) -> Step:
        runner = self._runtime_build / "gpgpu_sim_case"
        sources = [self._runtime / "sim/gpgpu_sim.c", self._runtime / "sim/gpgpu_sim_case.c"]
        includes = [self._runtime / "sim", self._runtime_build]
        build = self._simulator_command(sources, includes, runner)
        cases_root = self._config.repo_root / "tests/hardware/rtl/cases"
        cases = sorted((path.parent for path in cases_root.glob("test*/program.asm")
                        if re.fullmatch(r"test\d+", path.parent.name)), key=lambda path: int(path.name[4:]))
        expected = [case / name for case in cases for name in ("program.mem", "data.mem")]
        seeds = [case / name for case in cases for name in ("dmem_seed.mem", "ddr_seed.mem") if (case / name).is_file()]
        log = self._runtime_build / "check/check.log"

        def check() -> None:
            run(build, creates=runner.parent)
            check_cases(runner, cases, self._cores, self._runtime_build / "check", log)

        return Step(check, inputs=(*sources, self._runtime / "sim/gpgpu_sim.h", self._runtime_build / "gpgpu_hw.h",
                                   *expected, *seeds, Path(__file__).with_name("runtime_build.py")),
                    outputs=(log,), fingerprint={"command": build})

    def clean(self, program: str) -> Step:
        return Step(partial(_remove, self._out(program, "").parent), always_run=True)

    def build_elf(self, program: str) -> Step:
        source, headers = self._sources(program)
        elf, link_map = self._out(program, ".elf"), self._out(program, ".map")
        linker_script = self._root / "linker.ld"
        # The generated entry code includes the kernels' source.
        headers = [source, *headers, *self._runtime_sources("include", "device")]
        source, includes = self._out(program, "_entry.c"), self._runtime_includes(program)
        command = [self._riscv_cc, self._optimization, f"-march={self._riscv.march}", f"-mabi={self._riscv.abi}",
                   *self._defines, *_RISCV_CFLAGS, *includes, "-o", str(elf), str(source), "-nostdlib", "-nostartfiles",
                   f"-Wl,-L,{self._layout.parent}", f"-Wl,-T,{linker_script}", f"-Wl,-Map,{link_map}", "-Wl,--build-id=none"]
        # The whole command: a change of compiler, flags, march/abi, core count or memory layout rebuilds.
        return Step(partial(run, command, creates=elf.parent), inputs=(source, linker_script, self._layout, *headers),
                    outputs=(elf, link_map), fingerprint={"command": command})

    def linker_layout(self) -> Step:
        settings = {**self._memory.model_dump(), "num_cores": self._cores}
        constants = rtl_constants_path(self._config)
        this = Path(__file__).with_name("kernel_elf.py")
        return Step(partial(write_linker_layout, settings, constants, self._layout), inputs=(constants, this),
                    outputs=(self._layout,), fingerprint=settings)

    def disassemble(self, program: str) -> Step:
        elf, listing = self._out(program, ".elf"), self._out(program, "_dump_real.asm")
        command = [self._binutil("objdump"), "-d", "-M", "no-aliases,numeric", str(elf)]
        return Step(partial(_write_disassembly, command, listing), inputs=(elf,), outputs=(listing,))

    def assembly(self, program: str) -> Step:
        listing, output = self._out(program, "_dump_real.asm"), self._out(program, "_program.asm")
        return Step(partial(_write_assembly, listing, output), inputs=(listing,), outputs=(output,))

    def host_platform_header(self) -> Step:
        return host_headers.platform_step(self._config)
