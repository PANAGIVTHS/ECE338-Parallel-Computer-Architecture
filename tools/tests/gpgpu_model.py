"""Instruction-level model of the GPGPU, the reference for the RTL tests.

It runs the machine code the RTL runs (program.mem), one instruction at a time
for the whole warp, with the hardware's rules:

* Lockstep SIMT: one PC for every lane. Branches and jumps follow lane 0
  (StreamingMultiprocessor takes the branch decision and target from lane 0;
  divergence is not supported, so a branch the lanes disagree on is reported).
  The kernel ends when lane 0 executes RET, the encoding of jalr x0, 0(x1).
* Registers start as gpu_pkg::reg_reset_value: x2 = STACK_P_INIT, the
  TXD_REGISTER (x31) holds the lane id and ignores writes, the rest are 0;
  x0 is always 0. The PC wraps at IMEM_ENTRIES.
* Every access decodes as MemorySubsystemPkg::decode_access: misaligned,
  then DMEM (BRAM), the framebuffers (DDR, write-only), the texture (DDR,
  read-only), else unmapped; without the DDR backend a DDR access is unmapped.
* A memory instruction with a non-OK lane faults: the kernel stops there and
  the model records the fault report (PC, lanes, status kinds).
* Stores of one instruction to the same DMEM word take effect in ascending
  lane order (the BRAM backend's fixed priority). For the same DDR word the
  winner is unspecified (spec section 5.6), so different values are rejected.
* Each DDR store instruction issues one AXI write burst per distinct group
  (DDRBackendPkg::GROUP_BYTES): all lanes present together, so the group
  former takes every member of a group at once.

Every constant comes from the RTL packages, as read by the
tests:rtl:constants task ("pkg::NAME=value" lines).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

WORD_MASK = 0xFFFFFFFF

# Constants the model reads from the RTL packages
CONSTANTS = (
    "gpu_pkg::IMEM_ENTRIES", "gpu_pkg::DMEM_ENTRIES", "gpu_pkg::DMEM_BASE", "gpu_pkg::DMEM_SIZE",
    "gpu_pkg::FB0_BASE", "gpu_pkg::FB1_BASE", "gpu_pkg::FB_SIZE",
    "gpu_pkg::TEX_BASE", "gpu_pkg::TEX_SIZE",
    "gpu_pkg::STACK_P_INIT", "gpu_pkg::TXD_REGISTER", "gpu_pkg::REG_COUNT",
    "DDRBackendPkg::GROUP_BYTES",
    "MemorySubsystemPkg::ST_OK", "MemorySubsystemPkg::ST_UNMAPPED",
    "MemorySubsystemPkg::ST_PERMISSION", "MemorySubsystemPkg::ST_MISALIGNED",
)


class ModelError(Exception):
    """The program cannot be modelled: an unsupported instruction, an
    ambiguous DDR store, or no halt ECALL within the instruction limit."""


def read_constants(path: Path) -> dict[str, int]:
    """Parse the tests:rtl:constants file and check the model's constants are there."""
    constants: dict[str, int] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        match = re.fullmatch(r"(\w+::\w+)=([0-9]+)", line.strip())
        if match is None:
            raise ValueError(f"{path}:{line_no}: expected pkg::NAME=value, found {line!r}")
        constants[match[1]] = int(match[2])
    missing = [name for name in CONSTANTS if name not in constants]
    if missing:
        raise ValueError(f"{path} lacks RTL constants: {', '.join(missing)}")
    return constants


# =======================================================================
# Decode
# =======================================================================

@dataclass(frozen=True)
class Instruction:
    op: str
    rd: int = 0
    rs1: int = 0
    rs2: int = 0
    imm: int = 0


def _signed(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


_R_TYPE = {
    (0, 0x00): "add", (0, 0x20): "sub", (0, 0x01): "mul", (1, 0x00): "sll",
    (2, 0x00): "slt", (3, 0x00): "sltu", (4, 0x00): "xor", (5, 0x00): "srl",
    (5, 0x20): "sra", (6, 0x00): "or", (7, 0x00): "and",
}
_I_TYPE = {0: "addi", 2: "slti", 3: "sltiu", 4: "xori", 6: "ori", 7: "andi"}
_BRANCH = {0: "beq", 1: "bne", 4: "blt", 5: "bge", 6: "bltu", 7: "bgeu"}
_SHIFT_IMM = {(1, 0x00): "slli", (5, 0x00): "srli", (5, 0x20): "srai"}
_IMMEDIATE_OPS = {*_I_TYPE.values(), *_SHIFT_IMM.values()}


def decode(word: int) -> Instruction:
    """Decode the RV32I subset (plus MUL) the core executes."""
    opcode = word & 0x7F
    rd = (word >> 7) & 0x1F
    funct3 = (word >> 12) & 0x7
    rs1 = (word >> 15) & 0x1F
    rs2 = (word >> 20) & 0x1F
    funct7 = word >> 25
    if opcode == 0x33 and (funct3, funct7) in _R_TYPE:
        return Instruction(_R_TYPE[(funct3, funct7)], rd, rs1, rs2)
    if opcode == 0x13:
        if funct3 in _I_TYPE:
            return Instruction(_I_TYPE[funct3], rd, rs1, imm=_signed(word >> 20, 12))
        if (funct3, funct7) in _SHIFT_IMM:
            return Instruction(_SHIFT_IMM[(funct3, funct7)], rd, rs1, imm=rs2)
    if opcode == 0x37:
        return Instruction("lui", rd, imm=word & 0xFFFFF000)
    if opcode == 0x03 and funct3 == 2:
        return Instruction("lw", rd, rs1, imm=_signed(word >> 20, 12))
    if opcode == 0x23 and funct3 == 2:
        return Instruction("sw", rs1=rs1, rs2=rs2, imm=_signed((funct7 << 5) | rd, 12))
    if opcode == 0x63 and funct3 in _BRANCH:
        offset = (((word >> 31) & 1) << 12) | (((word >> 7) & 1) << 11) \
            | (((word >> 25) & 0x3F) << 5) | (((word >> 8) & 0xF) << 1)
        return Instruction(_BRANCH[funct3], rs1=rs1, rs2=rs2, imm=_signed(offset, 13))
    if opcode == 0x6F:
        offset = (((word >> 31) & 1) << 20) | (((word >> 12) & 0xFF) << 12) \
            | (((word >> 20) & 1) << 11) | (((word >> 21) & 0x3FF) << 1)
        return Instruction("jal", rd, imm=_signed(offset, 21))
    if opcode == 0x67 and funct3 == 0:
        return Instruction("jalr", rd, rs1, imm=_signed(word >> 20, 12))
    if word == 0x00000073:
        return Instruction("ecall")
    raise ModelError(f"unsupported instruction {word:08x}")


def _alu(op: str, a: int, b: int) -> int:
    sa, sb = _signed(a, 32), _signed(b, 32)
    if op in ("add", "addi"):
        return (a + b) & WORD_MASK
    if op == "sub":
        return (a - b) & WORD_MASK
    if op == "mul":
        return (a * b) & WORD_MASK
    if op in ("and", "andi"):
        return a & b
    if op in ("or", "ori"):
        return a | b
    if op in ("xor", "xori"):
        return a ^ b
    if op in ("sll", "slli"):
        return (a << (b & 0x1F)) & WORD_MASK
    if op in ("srl", "srli"):
        return a >> (b & 0x1F)
    if op in ("sra", "srai"):
        return (sa >> (b & 0x1F)) & WORD_MASK
    if op in ("slt", "slti"):
        return int(sa < sb)
    if op in ("sltu", "sltiu"):
        return int(a < b)
    raise AssertionError(op)


def _branch_taken(op: str, a: int, b: int) -> bool:
    sa, sb = _signed(a, 32), _signed(b, 32)
    return {
        "beq": a == b, "bne": a != b, "blt": sa < sb,
        "bge": sa >= sb, "bltu": a < b, "bgeu": a >= b,
    }[op]


# =======================================================================
# Memory
# =======================================================================

class Memory:
    """DMEM words plus a sparse DDR, decoded as the memory subsystem decodes."""

    def __init__(self, constants: dict[str, int], ddr_enable: bool):
        self.c = constants
        self.ddr_enable = ddr_enable
        self.dmem = [0] * constants["gpu_pkg::DMEM_ENTRIES"]
        self.ddr: dict[int, int] = {}

    def _in(self, addr: int, base: str, size: str) -> bool:
        start = self.c[f"gpu_pkg::{base}"]
        return start <= addr < start + self.c[f"gpu_pkg::{size}"]

    def decode(self, addr: int, write: bool) -> tuple[str | None, int]:
        """(target, status) as MemorySubsystemPkg::decode_access; target is
        "dmem", "ddr" or None (completed with the status, no side effect)."""
        st = lambda name: self.c[f"MemorySubsystemPkg::{name}"]  # noqa: E731
        if addr & 3:
            return None, st("ST_MISALIGNED")
        if self._in(addr, "DMEM_BASE", "DMEM_SIZE"):
            return "dmem", st("ST_OK")
        if self._in(addr, "FB0_BASE", "FB_SIZE") or self._in(addr, "FB1_BASE", "FB_SIZE"):
            target, status = ("ddr", st("ST_OK")) if write else (None, st("ST_PERMISSION"))
        elif self._in(addr, "TEX_BASE", "TEX_SIZE"):
            target, status = (None, st("ST_PERMISSION")) if write else ("ddr", st("ST_OK"))
        else:
            return None, st("ST_UNMAPPED")
        if target == "ddr" and not self.ddr_enable:
            return None, st("ST_UNMAPPED")
        return target, status

    def _dmem_index(self, addr: int) -> int:
        return (addr - self.c["gpu_pkg::DMEM_BASE"]) >> 2

    def read(self, target: str, addr: int) -> int:
        return self.dmem[self._dmem_index(addr)] if target == "dmem" else self.ddr.get(addr, 0)

    def write(self, target: str, addr: int, value: int) -> None:
        if target == "dmem":
            self.dmem[self._dmem_index(addr)] = value
        else:
            self.ddr[addr] = value


# =======================================================================
# Warp
# =======================================================================

@dataclass
class Fault:
    pc: int            # byte address of the faulting instruction
    lanes: int         # bit i: lane i got a non-OK status
    statuses: set[int]  # the non-OK status codes


@dataclass
class Result:
    regfiles: list[list[int]]
    dmem: list[int]
    ddr: dict[int, int]
    fault: Fault | None
    instructions: int
    ddr_bursts: int
    divergent_pcs: list[int] = field(default_factory=list)


class Warp:
    """One SM: NUM_CORES lanes in lockstep over a shared memory."""

    def __init__(self, program: list[int], num_lanes: int, constants: dict[str, int],
                 dmem_seed: list[int] | None = None, ddr_seed: dict[int, int] | None = None,
                 ddr_enable: bool = True):
        self.c = constants
        self.program = program
        self.num_lanes = num_lanes
        self.memory = Memory(constants, ddr_enable)
        if dmem_seed is not None:
            self.memory.dmem[:len(dmem_seed)] = dmem_seed
        self.memory.ddr.update(ddr_seed or {})
        self.txd = constants["gpu_pkg::TXD_REGISTER"]
        self.regs = []
        for lane in range(num_lanes):
            regs = [0] * constants["gpu_pkg::REG_COUNT"]
            regs[2] = constants["gpu_pkg::STACK_P_INIT"]
            regs[self.txd] = lane
            self.regs.append(regs)
        self.pc = 0  # instruction index

    def _write(self, lane: int, rd: int, value: int) -> None:
        if rd != 0 and rd != self.txd:
            self.regs[lane][rd] = value & WORD_MASK

    def run(self, max_instructions: int) -> Result:
        imem = self.c["gpu_pkg::IMEM_ENTRIES"]
        group_bytes = self.c["DDRBackendPkg::GROUP_BYTES"]
        lanes = range(self.num_lanes)
        executed = bursts = 0
        divergent: list[int] = []
        fault = None
        while True:
            if executed >= max_instructions:
                raise ModelError(f"no RET within {max_instructions} instructions (PC {self.pc * 4:#x})")
            word = self.program[self.pc] if self.pc < len(self.program) else 0
            try:
                inst = decode(word)
            except ModelError as error:
                raise ModelError(f"PC {self.pc * 4:#x}: {error}") from None
            executed += 1
            pc_bytes = self.pc * 4
            next_pc = (self.pc + 1) % imem
            op = inst.op

            if op == "ecall":
                # Every lane must request service 0; other values are no-ops.
                if all(self.regs[lane][17] == 0 for lane in lanes):
                    break
            elif op in _BRANCH.values():
                taken = [_branch_taken(op, self.regs[lane][inst.rs1], self.regs[lane][inst.rs2])
                         for lane in lanes]
                if any(t != taken[0] for t in taken):
                    divergent.append(pc_bytes)
                if taken[0]:
                    next_pc = (self.pc + inst.imm // 4) % imem
            elif op == "jal":
                for lane in lanes:
                    self._write(lane, inst.rd, pc_bytes + 4)
                next_pc = (self.pc + inst.imm // 4) % imem
            elif op == "jalr":
                target = (self.regs[0][inst.rs1] + inst.imm) & WORD_MASK & ~1
                for lane in lanes:
                    self._write(lane, inst.rd, pc_bytes + 4)
                next_pc = (target >> 2) % imem
            elif op == "lui":
                for lane in lanes:
                    self._write(lane, inst.rd, inst.imm)
            elif op in ("lw", "sw"):
                write = op == "sw"
                addrs = [(self.regs[lane][inst.rs1] + inst.imm) & WORD_MASK for lane in lanes]
                decoded = [self.memory.decode(addr, write) for addr in addrs]
                ok = self.c["MemorySubsystemPkg::ST_OK"]
                bad = [lane for lane in lanes if decoded[lane][1] != ok]
                if bad:
                    fault = Fault(pc_bytes, sum(1 << lane for lane in bad),
                                  {decoded[lane][1] for lane in bad})
                    break
                if write:
                    ddr_words: dict[int, set[int]] = {}
                    for lane in lanes:  # ascending lane order: the highest DMEM store survives
                        target = decoded[lane][0]
                        value = self.regs[lane][inst.rs2]
                        if target == "ddr":
                            ddr_words.setdefault(addrs[lane], set()).add(value)
                        self.memory.write(target, addrs[lane], value)
                    ambiguous = {a: v for a, v in ddr_words.items() if len(v) > 1}
                    if ambiguous:
                        addr = min(ambiguous)
                        raise ModelError(
                            f"PC {pc_bytes:#x}: lanes store different values to DDR word {addr:#010x} "
                            f"in one instruction; which one lands is unspecified")
                    bursts += len({addr // group_bytes for addr in ddr_words})
                else:
                    values = [self.memory.read(decoded[lane][0], addrs[lane]) for lane in lanes]
                    for lane in lanes:
                        self._write(lane, inst.rd, values[lane])
            else:  # ALU, register or immediate operand
                for lane in lanes:
                    a = self.regs[lane][inst.rs1]
                    b = inst.imm & WORD_MASK if op in _IMMEDIATE_OPS else self.regs[lane][inst.rs2]
                    self._write(lane, inst.rd, _alu(op, a, b))
            self.pc = next_pc

        return Result(
            regfiles=[list(regs) for regs in self.regs],
            dmem=list(self.memory.dmem),
            ddr=dict(sorted(self.memory.ddr.items())),
            fault=fault,
            instructions=executed,
            ddr_bursts=bursts,
            divergent_pcs=divergent,
        )
