"""ECALL encoding, ordinary returns, warp selectors, and exit epilogues.

All generated files live under pytest's temporary directory; these tests never
run the directed-suite generators against the source cases.
"""
from __future__ import annotations

from pathlib import Path
import random
import sys

import pytest

from tools.tests import assembler, expected_generator, random_tester


CASES = Path(__file__).resolve().parents[3] / "tests/hardware/rtl/cases"


def instructions_and_labels(text: str) -> tuple[list[str], dict[str, int]]:
    instructions: list[str] = []
    labels: dict[str, int] = {}
    for line in text.splitlines():
        code = line.split("#", 1)[0].split("//", 1)[0].strip()
        if ":" in code:
            name, code = code.split(":", 1)
            labels[name.strip()] = len(instructions)
            code = code.strip()
        if code:
            instructions.append(code)
    return instructions, labels


@pytest.mark.parametrize("instruction", ["ecall", "ECALL"])
def test_ecall_encoding(instruction: str) -> None:
    assert assembler.assemble_line(instruction, 123, {}) == 0x00000073
    assert assembler.assemble_line("jalr x0, 0(x1)", 123, {}) == 0x00008067


@pytest.mark.parametrize("instruction", ["ecall x17", "ecall 0"])
def test_ecall_rejects_explicit_operands(instruction: str) -> None:
    with pytest.raises(ValueError, match="ECALL has no explicit operands"):
        assembler.assemble_line(instruction, 0, {})


def test_assembler_preserves_subroutine_after_exit(tmp_path: Path, monkeypatch) -> None:
    source = (CASES / "test26/program.asm").read_text(encoding="utf-8")
    (tmp_path / "program.asm").write_text(source, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["assembler.py", str(tmp_path)])
    assembler.compile_all_tests()
    words = [int(word, 16) for word in (tmp_path / "program.mem").read_text().splitlines()]
    instructions, labels = instructions_and_labels(source)
    assert len(words) == assembler.DEPTH
    assert words[:len(instructions)] == [
        assembler.assemble_line(inst, pc, labels) for pc, inst in enumerate(instructions)
    ]
    assert words[labels["outer"]] != 0
    assert words[labels["inner"] + 1] == 0x00008067


@pytest.mark.parametrize("num_cores", [1, 2, 32])
def test_reference_nested_normal_returns_and_a7_use(num_cores: int) -> None:
    registers, memory = expected_generator.generate_expected_memories("""
        addi x17, x0, 41
        addi x18, x17, 1
        jal x1, outer
        addi x20, x20, 4
        sw x20, 0(x0)
        sw x18, 4(x0)
        addi x17, x0, 0
        ecall
        addi x29, x0, 999
        sw x18, 8(x0)
    outer:
        addi x5, x1, 0
        addi x20, x20, 1
        jal x1, inner
        addi x1, x5, 0
        jalr x0, 0(x1)
    inner:
        addi x20, x20, 2
        jalr x0, 0(x1)
    """, num_cores=num_cores)
    assert memory[:3] == [7, 42, 0]
    for lane, regs in enumerate(registers):
        assert regs[0] == 0
        assert regs[1] == 12
        assert regs[17] == 0
        assert regs[18] == 42
        assert regs[20] == 7
        assert regs[29] == 0
        assert regs[31] == lane


@pytest.mark.parametrize("selector", [1, 7, -1])
def test_reference_unknown_ecall_continues(selector: int) -> None:
    registers, memory = expected_generator.generate_expected_memories(f"""
        addi x17, x0, {selector}
        ecall
        addi x20, x0, 123
        sw x20, 0(x0)
        addi x17, x0, 0
        ecall
        addi x29, x0, 999
        sw x20, 4(x0)
    """, num_cores=2)
    assert memory[:2] == [123, 0]
    assert all(regs[20] == 123 and regs[29] == 0 for regs in registers)


@pytest.mark.parametrize("num_cores", [2, 4, 32])
def test_reference_mixed_ecall_is_noop_for_every_lane(num_cores: int) -> None:
    registers, memory = expected_generator.generate_expected_memories("""
        addi x17, x31, 0
        ecall
        addi x20, x0, 123
        slli x4, x31, 2
        sw x20, 0(x4)
        addi x17, x0, 0
        ecall
        addi x29, x0, 999
        sw x20, 128(x4)
    """, num_cores=num_cores)
    assert memory[:num_cores] == [123] * num_cores
    assert memory[32:32 + num_cores] == [0] * num_cores
    assert all(regs[20] == 123 and regs[29] == 0 for regs in registers)


@pytest.mark.parametrize("case, expected_memory", [
    (26, [31, 42, 0]),
    (27, [27, 0]),
    (28, [7, 0, 28, 0]),
    (29, [29, 0]),
])
@pytest.mark.parametrize("num_cores", [2, 32])
def test_directed_ecall_cases(case: int, expected_memory: list[int], num_cores: int) -> None:
    source = (CASES / f"test{case}/program.asm").read_text(encoding="utf-8")
    instructions, labels = instructions_and_labels(source)
    # Exercise the native dialect as well as the reference semantics.
    for pc, instruction in enumerate(instructions):
        assembler.assemble_line(instruction, pc, labels)
    registers, memory = expected_generator.generate_expected_memories(source, num_cores=num_cores)
    assert memory[:len(expected_memory)] == expected_memory
    assert all(regs[17] == 0 and regs[29] == 0 for regs in registers)
    if case == 26:
        assert all(regs[18] == 42 and regs[20] == 31 for regs in registers)
    else:
        assert all(regs[20] == case for regs in registers)


@pytest.mark.parametrize("seed", [0, 4242, 4243])
def test_random_generator_ecall_epilogue(tmp_path: Path, seed: int) -> None:
    output = tmp_path / "random.asm"
    state = random.getstate()
    try:
        random.seed(seed)
        random_tester.generate_random_assembly(output)
    finally:
        random.setstate(state)
    source = output.read_text(encoding="utf-8")
    instructions, labels = instructions_and_labels(source)
    assert instructions[-2:] == ["addi x17, x0, 0", "ecall"]
    assert sum(inst == "ecall" for inst in instructions) == 1
    assert not any(inst.startswith("jalr") for inst in instructions)
    assert "x17" in random_tester.AVAILABLE_REGS
    # Initialization must still treat a7 as ordinary random data.
    assert any(inst.startswith("addi x17, x0,") for inst in instructions[:-2])
    for pc, instruction in enumerate(instructions):
        assembler.assemble_line(instruction, pc, labels)
    registers, _ = expected_generator.generate_expected_memories(source, num_cores=2)
    assert all(regs[17] == 0 for regs in registers)


def test_uart_legacy_trim_preserves_full_linked_image() -> None:
    from tools.board.xc7z020.uart import trim_program_at_ret

    words = ["00000893", "00000073", "00008067", "00150513", "00008067"]
    assert trim_program_at_ret(iter(words)) == words


def test_checker_follows_normal_return_then_ecall() -> None:
    from tools.tests.program_checker import analyze_multicore_assembly

    assert analyze_multicore_assembly("""
        jal x1, helper
        addi x17, x0, 0
        ecall
        sw x0, 0(x0)
    helper:
        jalr x0, 0(x1)
        sw x0, 0(x0)
    """, num_cores=2)


@pytest.mark.parametrize("selector", ["addi x17, x0, 7", "addi x17, x31, 0"])
def test_checker_unsupported_or_mixed_ecall_continues(selector: str) -> None:
    from tools.tests.program_checker import analyze_multicore_assembly

    # A deliberate colliding store must be reached after a nonterminating ECALL.
    assert not analyze_multicore_assembly(f"""
        {selector}
        ecall
        sw x0, 0(x0)
    """, num_cores=2)
