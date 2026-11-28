"""The runtime's build steps (docs/runtime-spec.md): kernel generator, module builder, simulator check.

kernel generator  <p>.c -> scan pass -> <p>_entry.c (RISC-V entry code and block loop),
                  <p>_kernels.h (typed launch functions and symbols for the host),
                  <p>_scan.json (what the module builder needs)
module builder    kernel ELF -> <p>_module.c: the IMEM and GMEM images, the entry of
                  every kernel and the address of every exported variable
hardware header   rtl_constants.txt -> gpgpu_hw.h: the RTL the simulator models
runtime check     every RTL case on the C simulator, against the Python model's results
"""
from __future__ import annotations

import filecmp
import json
import re
import struct
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .kernel_elf import _STT_FUNC, _STT_OBJECT, ElfSection, _image_words, _sections, _symbols

_SHT_NOBITS = 8
_SHF_EXECINSTR = 0x4
# aux-info: "/* file:line:NF */ extern void name (params); /* (names) declarations */"
_AUX = re.compile(r"^/\* (?P<file>.+):(?P<line>\d+):(?P<kind>[A-Z]+) \*/ (?P<head>.*?)\b(?P<name>[A-Za-z_]\w*) "
                  r"\((?P<params>.*)\); /\* \((?P<names>[^)]*)\)")
_STORAGE = {"extern", "static", "inline", "__inline", "__inline__"}


class KernelError(ValueError):
    """A kernel or a marked variable breaks a rule of the runtime; the message names the source line."""


def c_name(program: str) -> str:
    """The program's name in generated C identifiers."""
    return re.sub(r"\W", "_", program)


def _read_constants(path: Path) -> dict[str, int]:
    constants = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name:
            constants[name] = int(value)
    return constants


# ---- Scan pass and kernel generator -------------------------------------------------------------

def _split_params(text: str) -> list[str]:
    text = text.strip()
    return [] if text in ("", "void") else [part.strip() for part in text.split(",")]


def _parse_kernels(aux: Path, source: Path, kernels: set[str]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for line in aux.read_text(encoding="utf-8").splitlines():
        match = _AUX.match(line)
        if match is None or match["name"] not in kernels or Path(match["file"]).resolve() != source.resolve():
            continue
        where = f"{source}:{match['line']}"
        name = match["name"]
        result = " ".join(word for word in match["head"].split() if word not in _STORAGE)
        if result != "void":
            raise KernelError(f"{where}: kernel {name} must return void, not {result}")
        params = _split_params(match["params"])
        names = [item.strip() for item in match["names"].split(",") if item.strip()]
        if "..." in params:
            raise KernelError(f"{where}: kernel {name} cannot take a variable number of parameters")
        for param in params:
            if "(" in param or "[" in param:
                raise KernelError(f"{where}: kernel {name}: parameter '{param}' is not supported "
                                  "(function pointers and pointers to arrays)")
        if len(params) != len(names) or any(not re.search(rf"\b{re.escape(n)}$", p) for p, n in zip(params, names)):
            raise KernelError(f"{where}: kernel {name}: cannot read the parameters ({match['params']})")
        found[name] = {"name": name, "line": int(match["line"]), "params": [{"decl": p, "name": n} for p, n in zip(params, names)]}
    missing = sorted(kernels - found.keys())
    if missing:
        raise KernelError(f"{source}: no prototype found for kernel(s) {', '.join(missing)}")
    return sorted(found.values(), key=lambda kernel: kernel["line"])


def _check_scan_object(data: bytes, sections: list[ElfSection], source: Path) -> None:
    """What the compiler does not check: writes to x3/x4 (inline assembly) and shared initializers."""
    for section in sections:
        if section.flags & _SHF_EXECINSTR and section.type != _SHT_NOBITS:
            code = data[section.offset:section.offset + section.size]
            for offset in range(0, len(code) - 3, 4):
                word, = struct.unpack_from("<I", code, offset)
                rd, opcode = (word >> 7) & 0x1F, word & 0x7F
                if rd in (3, 4) and opcode in (0x33, 0x13, 0x37, 0x17, 0x03, 0x6F, 0x67):
                    raise KernelError(f"{source}: {section.name} writes {'gp' if rd == 3 else 'tp'} (x{rd}) at offset "
                                      f"0x{offset:x}: the runtime keeps the block index there (runtime-spec 6.2)")
        if section.name == ".shared" and section.type != _SHT_NOBITS and any(data[section.offset:section.offset + section.size]):
            raise KernelError(f"{source}: a GPGPU_SHARED variable has an initializer; shared memory is not loaded "
                              "(runtime-spec 3.3): give it its value in the kernel")


def generate_kernels(command: Sequence[str], source: Path, header: Path | None, program: str, scan_object: Path,
                     aux: Path, entry: Path, kernels_header: Path, scan_json: Path) -> None:
    """The scan pass, then the code nvcc would add: entry functions and launch functions."""
    scan_object.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([*command, "-DGPGPU_SCAN", "-aux-info", str(aux), "-c", str(source), "-o", str(scan_object)], check=True)
    data = scan_object.read_bytes()
    sections = _sections(data)
    by_index = dict(enumerate(sections))
    symbols = _symbols(data, sections)

    def marked(section: str, kind: int) -> set[str]:
        return {s.name for s in symbols if s.kind == kind and s.section in by_index and by_index[s.section].name == section}

    kernels = _parse_kernels(aux, source, marked(".gpgpu_global", _STT_FUNC))
    if not kernels:
        raise KernelError(f"{source}: no kernel: mark one with GPGPU_GLOBAL")
    _check_scan_object(data, sections, source)
    exports = {"device": sorted(marked(".gpgpu_device", _STT_OBJECT)), "constant": sorted(marked(".gpgpu_constant", _STT_OBJECT))}
    name = c_name(program)

    lines = [f"/* Generated by `gpgpu software programs:{program}:kernels` from {source.name}. Do not edit.",
             " * The entry code of every kernel: the runtime's _start jumps to __gpgpu_kernel_<kernel>,",
             " * which loads the parameters once and calls the kernel for every block. */",
             f'#include "{source}"', "", "GPGPU_START_()"]
    for kernel in kernels:
        k, params = kernel["name"], kernel["params"]
        lines += ["", f"__attribute__((used, noinline)) void __gpgpu_kernel_{k}(void)", "{"]
        if params:
            # The types first, so a wide one is named before the layout below rejects it.
            lines.append(f"    typedef struct {{ {' '.join(p['decl'] + ';' for p in params)} }} gpgpu_types_;")
            lines += [f'    GPGPU_PARAM_CHECK_({k}, ((const gpgpu_types_ *)0)->{p["name"]}, "{p["name"]}");' for p in params]
            lines.append("    const struct {")
            lines += [f"        _Alignas(4) {p['decl']};" for p in params]
            lines.append("    } *gpgpu_args_ = (const void *)__gpu_launch[0].params;")
            lines += [f"    {p['decl']} = gpgpu_args_->{p['name']};" for p in params]
        lines += [f"    GPGPU_BLOCK_LOOP_({k}({', '.join(p['name'] for p in params)}));", "}"]
    entry.write_text("\n".join(lines) + "\n", encoding="utf-8")

    guard = f"{name.upper()}_KERNELS_H"
    lines = [f"/* Generated by `gpgpu software programs:{program}:kernels` from {source.name}. Do not edit.",
             " * A launch function for every kernel, used as gpgpu_launch(kernel, grid, ...), and the",
             " * symbols of the variables marked GPGPU_DEVICE or GPGPU_CONSTANT. */",
             f"#ifndef {guard}", f"#define {guard}", "", '#include "gpgpu.h"']
    if header is not None:
        lines.append(f'#include "{header}"')
    for kernel in kernels:
        k, params = kernel["name"], kernel["params"]
        signature = ", ".join(["gpgpu_dim3_t gpgpu_grid_", *(p["decl"] for p in params)])
        lines += ["", f"extern const uint32_t {k}_entry;", "",
                  f"static inline gpgpu_error_t {k}_launch({signature})", "{"]
        lines += [f'    GPGPU_PARAM_CHECK_({k}, {p["name"]}, "{p["name"]}");' for p in params]
        if params:
            wide = " || ".join(f"GPGPU_PARAM_TOO_WIDE_({p['name']})" for p in params)
            lines += [f"    if ({wide})", "        return GPGPU_ERROR_INVALID_VALUE;",
                      f"    const uint32_t gpgpu_words_[] = {{ {', '.join('GPGPU_PARAM_WORD_(' + p['name'] + ')' for p in params)} }};",
                      f"    return gpgpu_launch_words({k}_entry, gpgpu_grid_, gpgpu_words_, {len(params)}u);"]
        else:
            lines.append(f"    return gpgpu_launch_words({k}_entry, gpgpu_grid_, NULL, 0u);")
        lines.append("}")
    if exports["device"] or exports["constant"]:
        lines.append("")
        lines += [f"extern const gpgpu_symbol_t {name}_sym_{variable};" for variable in [*exports["device"], *exports["constant"]]]
    lines += ["", f"#endif /* {guard} */"]
    kernels_header.write_text("\n".join(lines) + "\n", encoding="utf-8")
    scan_json.write_text(json.dumps({"program": program, "kernels": kernels, "exports": exports}, indent=2) + "\n", encoding="utf-8")


# ---- Module builder -----------------------------------------------------------------------------

_M_NAMES = {1: "mulh", 2: "mulhsu", 3: "mulhu", 4: "div", 5: "divu", 6: "rem", 7: "remu"}


def _unsupported(word: int) -> str | None:
    """Why the core cannot execute this instruction, or None: the subset of tools/tests/gpgpu_model.py."""
    opcode, f3, f7 = word & 0x7F, (word >> 12) & 7, word >> 25
    if opcode == 0x33:
        if f7 == 0x01 and f3 in _M_NAMES:
            return f"{_M_NAMES[f3]} (only mul of the M extension is implemented: avoid /, % and 64-bit products)"
        return None if f7 == 0 or (f7 == 0x20 and f3 in (0, 5)) or (f7 == 0x01 and f3 == 0) else "an R-type encoding"
    if opcode == 0x13:
        return None if f3 not in (1, 5) or f7 == 0 or (f3 == 5 and f7 == 0x20) else "a shift encoding"
    if opcode in (0x37, 0x17, 0x6F):
        return None
    if opcode == 0x03:
        return None if f3 in (0, 1, 2, 4, 5) else "a load encoding"
    if opcode == 0x23:
        return None if f3 in (0, 1, 2) else "a store encoding"
    if opcode == 0x63:
        return None if f3 not in (2, 3) else "a branch encoding"
    if opcode == 0x67:
        return None if f3 == 0 else "a jalr encoding"
    return None if word == 0x00000073 else f"opcode 0x{opcode:02x}"


def _stack_depths(code: bytes, functions: dict[int, str]) -> tuple[dict[str, int], dict[str, set[str]]]:
    """Each function's frame (its first addi sp, sp, -N) and the functions it calls directly."""
    starts = sorted(functions)
    frames: dict[str, int] = {}
    calls: dict[str, set[str]] = {}
    words = [struct.unpack_from("<I", code, offset)[0] for offset in range(0, len(code) - 3, 4)]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else 4 * len(words)
        name = functions[start]
        frames[name], calls[name] = 0, set()
        for pc in range(start, end, 4):
            word = words[pc // 4]
            opcode, rd, rs1 = word & 0x7F, (word >> 7) & 0x1F, (word >> 15) & 0x1F
            immediate = (word >> 20) - (1 << 12 if word >> 31 else 0)
            if opcode == 0x13 and (word >> 12) & 7 == 0 and rd == 2 and rs1 == 2 and immediate < 0 and not frames[name]:
                frames[name] = -immediate
            elif opcode == 0x6F and rd in (0, 1):  # jal ra or a tail jump: j
                offset = (((word >> 31) & 1) << 20) | (((word >> 12) & 0xFF) << 12) | (((word >> 20) & 1) << 11) \
                    | (((word >> 21) & 0x3FF) << 1)
                target = pc + offset - (1 << 21 if offset >> 20 else 0)
                if target in functions and not start <= target < end:
                    calls[name].add(functions[target])
            elif opcode == 0x17 and rd == 1 and pc + 4 < end:  # auipc ra, hi; jalr ra, lo(ra)
                following = words[pc // 4 + 1]
                if following & 0x707F == 0x67 and (following >> 15) & 0x1F == 1:
                    low = (following >> 20) - (1 << 12 if following >> 31 else 0)
                    target = (pc + (word & 0xFFFFF000) + low) & 0xFFFFFFFF
                    if target in functions:
                        calls[name].add(functions[target])
    return frames, calls


def _check_stack(elf: Path, code: bytes, symbols: Sequence[Any], kernels: Sequence[str], stack_bytes: int) -> None:
    """Every kernel's deepest call chain must fit the lane's stack: lanes' stacks are adjacent."""
    functions = {symbol.value: symbol.name for symbol in symbols if symbol.kind == _STT_FUNC and symbol.value < len(code)}
    frames, calls = _stack_depths(code, functions)

    def depth(name: str, path: tuple[str, ...]) -> tuple[int, tuple[str, ...]]:
        if name in path:
            raise KernelError(f"{elf}: {' -> '.join((*path, name))} is recursive: the stack of a lane is {stack_bytes} bytes")
        deepest = max((depth(callee, (*path, name)) for callee in calls.get(name, ())), default=(0, ()))
        return frames.get(name, 0) + deepest[0], (name, *deepest[1])

    for kernel in kernels:
        used, chain = depth(f"__gpgpu_kernel_{kernel}", ())
        if used > stack_bytes:
            detail = " + ".join(f"{name} {frames.get(name, 0)}" for name in chain)
            raise KernelError(f"{elf}: kernel {kernel} needs {used} bytes of stack ({detail}), a lane has "
                              f"{stack_bytes} (architecture.memory.stack_bytes_per_lane)")


def _c_words(words: Sequence[int]) -> str:
    rows = [", ".join(f"0x{word:08x}u" for word in words[i:i + 8]) for i in range(0, len(words), 8)]
    return ",\n".join(f"    {row}" for row in rows)


def write_module(elf: Path, scan_json: Path, constants_file: Path, settings: dict[str, Any], output: Path) -> None:
    scan = json.loads(scan_json.read_text(encoding="utf-8"))
    program = scan["program"]
    name = c_name(program)
    rtl = _read_constants(constants_file)
    data = elf.read_bytes()
    sections = _sections(data)
    symbols = _symbols(data, sections)
    absolute = {symbol.name: symbol.value for symbol in symbols}

    text = next((section for section in sections if section.name == ".text"), None)
    if text is None or text.address != 0:
        raise KernelError(f"{elf}: .text must start at IMEM address 0")
    code = data[text.offset:text.offset + text.size] + b"\0" * (-text.size % 4)
    imem = list(struct.unpack_from(f"<{len(code) // 4}I", code))
    for index, word in enumerate(imem):
        why = _unsupported(word)
        if why is not None:
            raise KernelError(f"{elf}: instruction {word:08x} at 0x{4 * index:x} is {why}")
    _check_stack(elf, code, symbols, [kernel["name"] for kernel in scan["kernels"]], settings["stack_bytes"])

    image = _image_words(data, sections, (".rodata", ".data"))
    first = min(image, default=absolute["__gmem_data_start"])
    words = [image.get(address, 0) for address in range(first, max(image, default=first - 4) + 4, 4)]

    def symbol(variable: str) -> tuple[int, int]:
        found = next((s for s in symbols if s.name == variable and s.kind == _STT_OBJECT), None)
        if found is None:
            raise KernelError(f"{elf}: exported variable {variable} not found")
        return found.value, found.size

    lines = [f"/* Generated by `gpgpu software programs:{program}:module` from {elf.name}. Do not edit. */",
             '#include "gpgpu_module.h"', "",
             f"static const uint32_t gpgpu_imem_[{len(imem)}] = {{", _c_words(imem), "};"]
    if words:
        lines += ["", f"static const uint32_t gpgpu_gmem_image_[{len(words)}] = {{", _c_words(words), "};"]
    fields = {
        "name": f'"{program}"',
        "abi_version": "GPGPU_ABI_VERSION",
        "num_cores": f"{settings['num_cores']}u",
        "imem_words": f"{rtl['gpu_pkg::IMEM_ENTRIES']}u",
        "shared_bytes": f"{4 * rtl['gpu_pkg::SMEM_ENTRIES']}u",
        "gmem_base": f"0x{rtl['gpu_pkg::GMEM_BASE']:08x}u",
        "gmem_size": f"0x{rtl['gpu_pkg::GMEM_SIZE']:08x}u",
        "fb_base": f"{{ 0x{rtl['gpu_pkg::FB0_BASE']:08x}u, 0x{rtl['gpu_pkg::FB1_BASE']:08x}u }}",
        "fb_size": f"0x{rtl['gpu_pkg::FB_SIZE']:08x}u",
        "launch_block": f"0x{absolute['__gpu_launch']:08x}u",
        "data_start": f"0x{absolute['__gmem_data_start']:08x}u",
        "data_end": f"0x{absolute['__gmem_data_end']:08x}u",
        "bss_start": f"0x{absolute['__bss_start']:08x}u",
        "bss_end": f"0x{absolute['__bss_end']:08x}u",
        "imem": "gpgpu_imem_",
        "imem_count": f"{len(imem)}u",
        "gmem_image": "gpgpu_gmem_image_" if words else "NULL",
        "gmem_image_base": f"0x{first:08x}u",
        "gmem_image_words": f"{len(words)}u",
    }
    lines += ["", "const gpgpu_module_t gpgpu_module_ = {", *(f"    .{key} = {value}," for key, value in fields.items()), "};", ""]
    for kernel in scan["kernels"]:
        entry = f"__gpgpu_kernel_{kernel['name']}"
        if entry not in absolute:
            raise KernelError(f"{elf}: entry function {entry} not found")
        lines.append(f"const uint32_t {kernel['name']}_entry = 0x{absolute[entry]:08x}u;")
    for variable in [*scan["exports"]["device"], *scan["exports"]["constant"]]:
        address, size = symbol(variable)
        lines.append(f"const gpgpu_symbol_t {name}_sym_{variable} = {{ 0x{address:08x}u, {size}u }};")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- Simulator ----------------------------------------------------------------------------------

_HW = {
    "IMEM_ENTRIES": "gpu_pkg::IMEM_ENTRIES", "SMEM_ENTRIES": "gpu_pkg::SMEM_ENTRIES", "SMEM_BASE": "gpu_pkg::SMEM_BASE",
    "FB0_BASE": "gpu_pkg::FB0_BASE", "FB1_BASE": "gpu_pkg::FB1_BASE", "FB_SIZE": "gpu_pkg::FB_SIZE",
    "GMEM_BASE": "gpu_pkg::GMEM_BASE", "GMEM_SIZE": "gpu_pkg::GMEM_SIZE", "STACK_P_INIT": "gpu_pkg::STACK_P_INIT",
    "TXD_REGISTER": "gpu_pkg::TXD_REGISTER", "GROUP_BYTES": "DDRBackendPkg::GROUP_BYTES", "BEAT_LSB": "DDRBackendPkg::BEAT_LSB",
    "ST_OK": "MemorySubsystemPkg::ST_OK", "ST_UNMAPPED": "MemorySubsystemPkg::ST_UNMAPPED",
    "ST_PERMISSION": "MemorySubsystemPkg::ST_PERMISSION", "ST_MISALIGNED": "MemorySubsystemPkg::ST_MISALIGNED",
}


def write_hw_header(constants_file: Path, settings: dict[str, int], output: Path) -> None:
    """The hardware the simulator models: the RTL as elaborated, and the configuration."""
    rtl = _read_constants(constants_file)
    lines = ["/* Generated by `gpgpu software runtime:hw` from the RTL constants (rtl:constants) and the",
             " * configuration. Do not edit. */", "#ifndef GPGPU_HW_H", "#define GPGPU_HW_H", "",
             f"#define GPGPU_HW_NUM_CORES {settings['num_cores']}u",
             f"#define GPGPU_HW_DDR_ENABLE {int(settings['ddr_enable'])}"]
    lines += [f"#define GPGPU_HW_{key} {rtl[name]}u" for key, name in _HW.items()]
    lines += ["", "#endif /* GPGPU_HW_H */", ""]
    output.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    if not output.is_file() or output.read_text(encoding="utf-8") != text:
        output.write_text(text, encoding="utf-8")


def _same(left: Path, right: Path) -> bool:
    return left.is_file() and right.is_file() and filecmp.cmp(left, right, shallow=False)


def check_cases(runner: Path, cases: list[Path], lanes: int, output: Path, log: Path) -> None:
    """Run every case on the simulator and compare every file the model wrote."""
    lines, failures = [], []
    for case in cases:
        result = output / case.name
        result.mkdir(parents=True, exist_ok=True)
        for stale in result.iterdir():
            stale.unlink()
        run = subprocess.run([str(runner), str(case), str(result)], capture_output=True, text=True)
        if run.returncode != 0:
            failures.append(f"{case.name}: {run.stderr.strip() or f'exit status {run.returncode}'}")
            continue
        names = ["data.mem", "perf.mem", *(f"regfile_c{lane}.mem" for lane in range(lanes))]
        differ = [n for n in names if not _same(case / n, result / n)]
        if (case / "ddr.mem").is_file() != (result / "ddr.mem").is_file() or \
                ((case / "ddr.mem").is_file() and not _same(case / "ddr.mem", result / "ddr.mem")):
            differ.append("ddr.mem")
        if differ:
            failures.append(f"{case.name}: differs from the model in {', '.join(differ)}")
        else:
            lines.append(f"{case.name}: same as the model")
    lines += failures
    summary = f"{len(cases) - len(failures)} of {len(cases)} cases agree with the Python model"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join([*lines, summary]) + "\n", encoding="utf-8")
    print(summary)
    if failures:
        raise RuntimeError("The simulator disagrees with the model:\n" + "\n".join(failures))
