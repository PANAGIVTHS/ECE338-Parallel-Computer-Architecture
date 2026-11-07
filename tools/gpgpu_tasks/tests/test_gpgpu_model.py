"""AUIPC and sub-word memory operations in the test assembler and GPGPU model.

The RTL suites compare the hardware with this model, so its results here are
checked against values worked out by hand from the RISC-V specification.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.tests import rtl
from tools.tests.gpgpu_model import ModelError, Warp, read_constants
from tools.tests.assembler import assemble_line

REPO = Path(__file__).resolve().parents[3]
RTL_PACKAGES = ("packages/gpu_pkg.sv", "memory/ddr/AXI4FullPkg.sv",
                "memory/ddr/DDRBackendPkg.sv", "memory/MemorySubsystemPkg.sv")
RET = "jalr x0, 0(x1)"


@pytest.fixture(scope="module")
def constants(tmp_path_factory):
    root = REPO / "hardware/rtl/gpgpu"
    path = tmp_path_factory.mktemp("rtl") / "rtl_constants.txt"
    rtl.write_rtl_constants([root / package for package in RTL_PACKAGES], root, path)
    return read_constants(path)


def run(constants, lines, lanes=1, dmem_seed=None, ddr_seed=None):
    program = [assemble_line(line, pc, {}) for pc, line in enumerate([*lines, RET])]
    return Warp(program, lanes, constants, dmem_seed, ddr_seed).run(1000)


# Encodings from the GNU assembler (riscv64-elf-as -march=rv32im).
@pytest.mark.parametrize("line, word", [
    ("auipc x7, 0x12345", 0x12345397),
    ("auipc x31, 0xFFFFF", 0xFFFFFF97),
    ("lb x6, 0(x5)", 0x00028303),
    ("lh x8, 2(x5)", 0x00229403),
    ("lbu x7, -1(x5)", 0xFFF2C383),
    ("lhu x9, 2047(x5)", 0x7FF2D483),
    ("lw x10, 4(x5)", 0x0042A503),
    ("sb x10, 16(x5)", 0x00A28823),
    ("sh x10, 20(x5)", 0x00A29A23),
    ("sb x10, -1(x5)", 0xFEA28FA3),
    ("sw x10, 2044(x5)", 0x7EA2AE23),
])
def test_assembler_encodes_as_the_gnu_assembler(line, word):
    assert assemble_line(line, 0, {}) == word


def test_auipc_adds_the_upper_immediate_to_its_own_pc(constants):
    regs = run(constants, ["auipc x5, 0", "auipc x6, 1", "auipc x7, 0xFFFFF"]).regfiles[0]
    assert regs[5:8] == [0x00000000, 0x00001004, 0xFFFFF008]


def test_loads_take_the_addressed_bytes_and_extend_them(constants):
    seed = [0x80F1E2D3, 0x7F6E5D4C]
    regs = run(constants, [
        "lb x5, 0(x0)", "lb x6, 1(x0)", "lb x7, 2(x0)", "lb x8, 3(x0)",
        "lbu x9, 0(x0)", "lbu x10, 3(x0)",
        "lh x11, 0(x0)", "lh x12, 2(x0)", "lhu x13, 0(x0)", "lhu x14, 2(x0)",
        "lb x15, 7(x0)", "lh x16, 6(x0)", "lw x17, 4(x0)",
    ], dmem_seed=seed).regfiles[0]
    assert regs[5:18] == [
        0xFFFFFFD3, 0xFFFFFFE2, 0xFFFFFFF1, 0xFFFFFF80,
        0x000000D3, 0x00000080,
        0xFFFFE2D3, 0xFFFF80F1, 0x0000E2D3, 0x000080F1,
        0x0000007F, 0x00007F6E, 0x7F6E5D4C,
    ]


def test_stores_change_only_the_addressed_bytes(constants):
    seed = [0xAAAAAAAA] * 6
    dmem = run(constants, [
        "lui x5, 0x44332", "addi x5, x5, 0x211",
        "sb x5, 0(x0)", "sb x5, 5(x0)", "sb x5, 10(x0)", "sb x5, 15(x0)",
        "sh x5, 16(x0)", "sh x5, 22(x0)",
    ], dmem_seed=seed).dmem
    assert dmem[:6] == [0xAAAAAA11, 0xAAAA11AA, 0xAA11AAAA, 0x11AAAAAA, 0xAAAA2211, 0x2211AAAA]


def test_lanes_merge_into_one_dmem_word_and_the_highest_lane_wins_a_byte(constants):
    dmem = run(constants, [
        "addi x5, x31, 0x40",
        "sb x5, 0(x31)",        # lane i, byte i
        "sb x5, 4(x0)",         # every lane the same byte
    ], lanes=4).dmem
    assert dmem[:2] == [0x43424140, 0x00000043]


@pytest.mark.parametrize("line, misaligned", [
    ("lb x5, 1(x0)", False), ("lb x5, 3(x0)", False), ("sb x5, 3(x0)", False),
    ("lh x5, 2(x0)", False), ("lhu x5, 2(x0)", False), ("sh x5, 2(x0)", False),
    ("lh x5, 1(x0)", True), ("lhu x5, 3(x0)", True), ("sh x5, 1(x0)", True),
    ("lw x5, 2(x0)", True), ("sw x5, 1(x0)", True),
])
def test_each_access_must_be_aligned_to_its_own_size(constants, line, misaligned):
    fault = run(constants, [line]).fault
    if misaligned:
        assert fault.pc == 0 and fault.statuses == {constants["MemorySubsystemPkg::ST_MISALIGNED"]}
    else:
        assert fault is None


def test_a_faulting_sub_word_store_has_no_side_effect(constants):
    result = run(constants, ["sh x31, 1(x0)"], dmem_seed=[0xDEADBEEF])
    assert result.fault is not None
    assert result.dmem[0] == 0xDEADBEEF


def test_the_memory_map_decides_a_byte_past_a_region(constants):
    end = constants["gpu_pkg::DMEM_BASE"] + constants["gpu_pkg::DMEM_SIZE"]
    result = run(constants, [f"lui x5, {end >> 12}", "lbu x6, -1(x5)", "lbu x6, 0(x5)"])
    assert result.fault.pc == 8
    assert result.fault.statuses == {constants["MemorySubsystemPkg::ST_UNMAPPED"]}


def test_ddr_stores_merge_over_the_seed_in_one_burst(constants):
    base = constants["gpu_pkg::FB0_BASE"]
    result = run(constants, [
        f"lui x5, {base >> 12}",
        "addi x6, x31, 0x40",
        "add x7, x5, x31",
        "sb x6, 0(x7)",         # lane i, byte i of the first word
        "addi x8, x0, 0x41",
        "sh x8, 6(x5)",         # the same value from every lane is not ambiguous
    ], lanes=2, ddr_seed={base: 0xA5A5A5A5, base + 4: 0xC3C3C3C3})
    assert result.ddr == {base: 0xA5A54140, base + 4: 0x0041C3C3}
    assert result.ddr_bursts == 2


def test_only_a_byte_two_lanes_disagree_on_is_ambiguous_in_ddr(constants):
    base = constants["gpu_pkg::FB0_BASE"]
    prefix = [f"lui x5, {base >> 12}", "slli x6, x31, 8"]  # lanes differ in byte 1 only
    assert run(constants, [*prefix, "sb x6, 0(x5)"], lanes=2).ddr == {base: 0}
    with pytest.raises(ModelError, match=f"DDR byte {base + 1:#010x}"):
        run(constants, [*prefix, "sh x6, 0(x5)"], lanes=2)
