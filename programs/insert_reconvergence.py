#!/usr/bin/env python3
"""Insert static SIMT reconvergence markers into RISC-V objdump output.

This tool reads the repository's `objdump -d -M no-aliases,numeric` output,
builds a basic-block control-flow graph, computes the immediate post-dominator
of each conditional branch block, and emits assembly with a custom `ssy LABEL`
instruction immediately before each conditional branch.

`ssy` encoding used by this tool for future RTL support:
  - custom-0 opcode: 0b0001011 (0x0b)
  - J-type immediate layout, like JAL, but with rd fixed to x0
  - semantic immediate: PC-relative byte offset to the reconvergence label

Until RTL decodes this instruction, keep BRANCH_RECONVERGENCE disabled for
normal FPGA/simulation runs. The generated *_reconv.asm and *_reconv.mem files
are useful for reviewing the static transformation before RTL work starts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

COND_BRANCHES = {"beq", "bne", "blt", "bge", "bltu", "bgeu"}
CONTROL_OPS = COND_BRANCHES | {"jal", "jalr"}
DEPTH = 2048
SSY_OPCODE = 0x0B  # RISC-V custom-0 opcode space.


@dataclass(frozen=True)
class Instr:
    addr: int
    hex_code: str
    text: str
    op: str
    operands: List[str]


@dataclass
class Block:
    start: int
    instrs: List[Instr]
    succs: Set[int]

    @property
    def end(self) -> int:
        return self.instrs[-1].addr


def strip_comment(text: str) -> str:
    return text.split("#", 1)[0].split("//", 1)[0].strip()


def split_operands(rest: str) -> Tuple[str, List[str]]:
    code = strip_comment(rest)
    if not code:
        return "", []
    parts = code.split(None, 1)
    op = parts[0].lower()
    if len(parts) == 1:
        return op, []
    operands = [p.strip() for p in parts[1].split(",")]
    return op, operands


def parse_int_token(token: str) -> int:
    token = token.strip().rstrip(",")
    token = token.split()[0]
    sign = -1 if token.startswith("-") else 1
    if token and token[0] in "+-":
        token = token[1:]
    if token.lower().startswith("0x"):
        return sign * int(token, 16)
    # Objdump branch/jump target addresses are bare hex tokens.
    if re.fullmatch(r"[0-9a-fA-F]+", token) and re.search(r"[a-fA-F]", token):
        return sign * int(token, 16)
    # For target fields emitted by objdump, tokens like '150' are still hex.
    # Callers that parse non-target immediates should use parse_imm instead.
    return sign * int(token, 16)


def parse_imm(token: str) -> int:
    token = token.strip().rstrip(",")
    if token.lower().startswith("0x") or token.lower().startswith("-0x"):
        return int(token, 16)
    return int(token, 10)


def parse_objdump(path: Path) -> Tuple[List[Instr], Dict[int, List[str]]]:
    instrs: List[Instr] = []
    labels: Dict[int, List[str]] = {}
    label_re = re.compile(r"^\s*([0-9a-fA-F]+)\s+<([^>]+)>:\s*$")
    instr_re = re.compile(r"^\s*([0-9a-fA-F]+):\s+([0-9a-fA-F]{8})\s+\t?(.+?)\s*$")

    for line in path.read_text(encoding="utf-8").splitlines():
        m = label_re.match(line)
        if m:
            addr = int(m.group(1), 16)
            labels.setdefault(addr, []).append(m.group(2))
            continue
        m = instr_re.match(line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        hex_code = m.group(2).lower()
        text = m.group(3).strip()
        op, operands = split_operands(text)
        if not op:
            continue
        instrs.append(Instr(addr=addr, hex_code=hex_code, text=strip_comment(text), op=op, operands=operands))

    if not instrs:
        raise ValueError(f"No instructions found in {path}")
    return instrs, labels


def control_target(inst: Instr) -> Optional[int]:
    if inst.op in COND_BRANCHES:
        if len(inst.operands) < 3:
            raise ValueError(f"Malformed branch at 0x{inst.addr:x}: {inst.text}")
        return parse_int_token(inst.operands[2])
    if inst.op == "jal":
        if len(inst.operands) < 2:
            raise ValueError(f"Malformed jal at 0x{inst.addr:x}: {inst.text}")
        return parse_int_token(inst.operands[1])
    return None


def is_unconditional_jump(inst: Instr) -> bool:
    return inst.op == "jal" and len(inst.operands) >= 2 and inst.operands[0].strip().lower() == "x0"


def is_return_or_indirect_exit(inst: Instr) -> bool:
    return inst.op == "jalr"


def build_blocks(instrs: List[Instr]) -> Tuple[Dict[int, Block], Dict[int, int]]:
    addrs = [i.addr for i in instrs]
    addr_set = set(addrs)
    next_addr: Dict[int, Optional[int]] = {
        inst.addr: (instrs[idx + 1].addr if idx + 1 < len(instrs) else None)
        for idx, inst in enumerate(instrs)
    }

    starts: Set[int] = {instrs[0].addr}
    for inst in instrs:
        nxt = next_addr[inst.addr]
        if inst.op in COND_BRANCHES:
            tgt = control_target(inst)
            if tgt is not None and tgt in addr_set:
                starts.add(tgt)
            if nxt is not None:
                starts.add(nxt)
        elif inst.op == "jal":
            tgt = control_target(inst)
            if is_unconditional_jump(inst):
                if tgt is not None and tgt in addr_set:
                    starts.add(tgt)
                if nxt is not None:
                    starts.add(nxt)
            else:
                # Treat direct calls as returning to the next instruction; do not
                # add the callee as a normal CFG successor for post-dominators.
                if nxt is not None:
                    starts.add(nxt)
        elif inst.op == "jalr":
            if nxt is not None:
                starts.add(nxt)

    sorted_starts = sorted(starts)
    start_set = set(sorted_starts)
    blocks: Dict[int, Block] = {}
    addr_to_block: Dict[int, int] = {}
    cur_start = instrs[0].addr
    cur: List[Instr] = []

    for inst in instrs:
        if inst.addr in start_set and cur:
            blocks[cur_start] = Block(cur_start, cur, set())
            for ci in cur:
                addr_to_block[ci.addr] = cur_start
            cur_start = inst.addr
            cur = []
        cur.append(inst)
    if cur:
        blocks[cur_start] = Block(cur_start, cur, set())
        for ci in cur:
            addr_to_block[ci.addr] = cur_start

    block_starts = sorted(blocks)
    next_block: Dict[int, Optional[int]] = {}
    for idx, start in enumerate(block_starts):
        next_block[start] = block_starts[idx + 1] if idx + 1 < len(block_starts) else None

    for start, block in blocks.items():
        last = block.instrs[-1]
        succs: Set[int] = set()
        if last.op in COND_BRANCHES:
            tgt = control_target(last)
            if tgt is not None and tgt in addr_to_block:
                succs.add(addr_to_block[tgt])
            if next_block[start] is not None:
                succs.add(next_block[start])
        elif is_unconditional_jump(last):
            tgt = control_target(last)
            if tgt is not None and tgt in addr_to_block:
                succs.add(addr_to_block[tgt])
        elif is_return_or_indirect_exit(last):
            succs = set()
        else:
            if next_block[start] is not None:
                succs.add(next_block[start])
        block.succs = succs

    return blocks, addr_to_block


def compute_postdominators(blocks: Dict[int, Block]) -> Dict[int, Set[int]]:
    nodes = set(blocks)
    exit_node = -1
    all_nodes = nodes | {exit_node}
    succs: Dict[int, Set[int]] = {n: set(blocks[n].succs) or {exit_node} for n in nodes}
    succs[exit_node] = set()

    postdom: Dict[int, Set[int]] = {n: set(all_nodes) for n in all_nodes}
    postdom[exit_node] = {exit_node}

    changed = True
    while changed:
        changed = False
        for n in nodes:
            new_set = {n} | set.intersection(*(postdom[s] for s in succs[n]))
            if new_set != postdom[n]:
                postdom[n] = new_set
                changed = True
    return postdom


def immediate_postdom(node: int, postdom: Dict[int, Set[int]]) -> Optional[int]:
    candidates = postdom[node] - {node, -1}
    if not candidates:
        return None
    for cand in sorted(candidates):
        # The immediate post-dominator is the closest candidate: it is not in
        # any other candidate's postdominator set.
        if all(cand == other or cand not in postdom[other] for other in candidates):
            return cand
    return sorted(candidates)[0]


def branch_reconvergence(blocks: Dict[int, Block], postdom: Dict[int, Set[int]]) -> Dict[int, int]:
    result: Dict[int, int] = {}
    for start, block in blocks.items():
        last = block.instrs[-1]
        if last.op not in COND_BRANCHES:
            continue
        ipdom = immediate_postdom(start, postdom)
        if ipdom is None:
            raise ValueError(f"No reconvergence block found for branch at 0x{last.addr:x}: {last.text}")
        result[last.addr] = ipdom
    return result


def label_for(addr: int) -> str:
    return f".Lpc_{addr:08x}"


def format_instruction(inst: Instr, branch_reconv: Dict[int, int]) -> List[str]:
    out: List[str] = []
    if inst.addr in branch_reconv:
        out.append(f"    ssy     {label_for(branch_reconv[inst.addr])}    # reconverge for branch at 0x{inst.addr:x}")

    operands = list(inst.operands)
    if inst.op in COND_BRANCHES and len(operands) >= 3:
        operands[2] = label_for(control_target(inst) or 0)
    elif inst.op == "jal" and len(operands) >= 2:
        tgt = control_target(inst)
        if tgt is not None:
            operands[1] = label_for(tgt)

    if operands:
        out.append(f"    {inst.op}    {', '.join(operands)}")
    else:
        out.append(f"    {inst.op}")
    return out


def emit_asm(instrs: List[Instr], objdump_labels: Dict[int, List[str]], branch_reconv: Dict[int, int]) -> str:
    needed_labels: Set[int] = {instrs[0].addr} | set(objdump_labels) | set(branch_reconv.values())
    for inst in instrs:
        if inst.op in COND_BRANCHES or inst.op == "jal":
            tgt = control_target(inst)
            if tgt is not None:
                needed_labels.add(tgt)

    lines: List[str] = []
    lines.append("# Auto-generated by programs/insert_reconvergence.py")
    lines.append("# Contains custom `ssy label` instructions before conditional branches.")
    lines.append("")
    for inst in instrs:
        if inst.addr in needed_labels:
            names = objdump_labels.get(inst.addr, [])
            for name in names:
                safe = re.sub(r"[^A-Za-z0-9_.$]", "_", name)
                # Numeric local labels and names containing + are awkward to
                # reference after reassembly; emit them as comments only unless
                # they look like ordinary assembler symbols.
                if re.fullmatch(r"[A-Za-z_.$][A-Za-z0-9_.$]*", safe):
                    lines.append(f"{safe}:")
            lines.append(f"{label_for(inst.addr)}:")
        lines.extend(format_instruction(inst, branch_reconv))
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Small assembler, intentionally matching the repo's supported RV32IM subset.
# ---------------------------------------------------------------------------

def parse_reg(reg: str) -> int:
    reg = reg.strip().replace("(", "").replace(")", "")
    if not reg.startswith("x"):
        raise ValueError(f"Expected x-register, got {reg!r}")
    return int(reg[1:])


def parse_mem_operand(op: str) -> Tuple[int, int]:
    m = re.fullmatch(r"\s*(-?(?:0x[0-9a-fA-F]+|\d+))\s*\(\s*(x\d+)\s*\)\s*", op)
    if not m:
        raise ValueError(f"Invalid memory operand: {op}")
    return parse_imm(m.group(1)), parse_reg(m.group(2))


def control_offset(target: str, pc: int, labels: Dict[str, int]) -> int:
    if target in labels:
        return (labels[target] - pc) * 4
    return parse_imm(target)


def encode_j_imm(offset: int) -> int:
    off = offset & 0x1FFFFF
    return (((off >> 20) & 1) << 31) | (((off >> 1) & 0x3FF) << 21) | (((off >> 11) & 1) << 20) | (((off >> 12) & 0xFF) << 12)


def assemble_line(inst: str, pc: int, labels: Dict[str, int]) -> int:
    op, operands = split_operands(inst)
    if not op:
        raise ValueError("empty instruction")
    parts = [op] + operands

    if op == "nop":
        return 0x00000013

    if op == "ssy":
        if len(parts) != 2:
            raise ValueError(f"ssy expects one label/immediate: {inst}")
        offset = control_offset(parts[1], pc, labels)
        return encode_j_imm(offset) | SSY_OPCODE

    if op in ["add", "sub", "mul", "and", "or", "xor", "sll", "srl", "sra", "slt", "sltu"]:
        rd, rs1, rs2 = parse_reg(parts[1]), parse_reg(parts[2]), parse_reg(parts[3])
        opcode = 0x33
        f3, f7 = 0x0, 0x00
        if op == "sub": f7 = 0x20
        elif op == "mul": f7 = 0x01
        elif op == "sll": f3 = 0x1
        elif op == "slt": f3 = 0x2
        elif op == "sltu": f3 = 0x3
        elif op == "srl": f3 = 0x5
        elif op == "sra": f3 = 0x5; f7 = 0x20
        elif op == "xor": f3 = 0x4
        elif op == "or": f3 = 0x6
        elif op == "and": f3 = 0x7
        return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | opcode

    if op in ["addi", "andi", "ori", "xori", "slli", "srli", "srai", "slti", "sltiu"]:
        rd, rs1, imm = parse_reg(parts[1]), parse_reg(parts[2]), parse_imm(parts[3])
        opcode, f3 = 0x13, 0x0
        if op == "slti": f3 = 0x2
        elif op == "sltiu": f3 = 0x3
        elif op == "xori": f3 = 0x4
        elif op == "ori": f3 = 0x6
        elif op == "andi": f3 = 0x7
        elif op == "slli": f3 = 0x1; imm &= 0x1F
        elif op == "srli": f3 = 0x5; imm &= 0x1F
        elif op == "srai": f3 = 0x5; imm = (imm & 0x1F) | 0x400
        return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | opcode

    if op == "lui":
        return ((parse_imm(parts[2]) & 0xFFFFF) << 12) | (parse_reg(parts[1]) << 7) | 0x37

    if op == "lw":
        rd = parse_reg(parts[1])
        imm, rs1 = parse_mem_operand(parts[2])
        return ((imm & 0xFFF) << 20) | (rs1 << 15) | (0x2 << 12) | (rd << 7) | 0x03

    if op == "sw":
        rs2 = parse_reg(parts[1])
        imm, rs1 = parse_mem_operand(parts[2])
        imm &= 0xFFF
        return (((imm >> 5) & 0x7F) << 25) | (rs2 << 20) | (rs1 << 15) | (0x2 << 12) | ((imm & 0x1F) << 7) | 0x23

    if op in COND_BRANCHES:
        rs1, rs2 = parse_reg(parts[1]), parse_reg(parts[2])
        offset = control_offset(parts[3], pc, labels) & 0x1FFF
        f3 = {"beq": 0x0, "bne": 0x1, "blt": 0x4, "bge": 0x5, "bltu": 0x6, "bgeu": 0x7}[op]
        return (((offset >> 12) & 1) << 31) | (((offset >> 5) & 0x3F) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (((offset >> 1) & 0xF) << 8) | (((offset >> 11) & 1) << 7) | 0x63

    if op == "jal":
        rd = parse_reg(parts[1])
        offset = control_offset(parts[2], pc, labels)
        return encode_j_imm(offset) | (rd << 7) | 0x6F

    if op == "jalr":
        rd = parse_reg(parts[1])
        if len(parts) == 3 and "(" in parts[2]:
            imm, rs1 = parse_mem_operand(parts[2])
        else:
            rs1, imm = parse_reg(parts[2]), parse_imm(parts[3])
        return ((imm & 0xFFF) << 20) | (rs1 << 15) | (0x0 << 12) | (rd << 7) | 0x67

    raise ValueError(f"Unsupported instruction {op!r}: {inst}")


def assemble_asm_text(asm_text: str, depth: int = DEPTH) -> List[str]:
    instructions: List[str] = []
    labels: Dict[str, int] = {}

    for raw in asm_text.splitlines():
        code = strip_comment(raw)
        if not code:
            continue
        while ":" in code:
            before, after = code.split(":", 1)
            label = before.strip()
            if not label or re.search(r"\s", label):
                break
            labels[label] = len(instructions)
            code = after.strip()
            if not code:
                break
        if code:
            instructions.append(code)

    hex_lines = [f"{assemble_line(inst, pc, labels):08x}" for pc, inst in enumerate(instructions)]
    if len(hex_lines) > depth:
        raise ValueError(f"Program has {len(hex_lines)} instructions after SSY insertion; IMEM depth is {depth}")
    return hex_lines + ["00000000"] * (depth - len(hex_lines))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, type=Path, help="objdump -d output file")
    ap.add_argument("--asm-out", required=True, type=Path, help="transformed assembly output")
    ap.add_argument("--mem-out", type=Path, help="optional transformed instruction memory output")
    ap.add_argument("--report-out", type=Path, help="optional JSON analysis report")
    ap.add_argument("--depth", type=int, default=DEPTH, help="IMEM depth when writing --mem-out")
    args = ap.parse_args(argv)

    instrs, objdump_labels = parse_objdump(args.input)
    blocks, addr_to_block = build_blocks(instrs)
    postdom = compute_postdominators(blocks)
    reconv = branch_reconvergence(blocks, postdom)
    asm_text = emit_asm(instrs, objdump_labels, reconv)

    args.asm_out.parent.mkdir(parents=True, exist_ok=True)
    args.asm_out.write_text(asm_text, encoding="utf-8")

    if args.mem_out:
        mem_lines = assemble_asm_text(asm_text, depth=args.depth)
        args.mem_out.parent.mkdir(parents=True, exist_ok=True)
        args.mem_out.write_text("\n".join(mem_lines) + "\n", encoding="utf-8")

    if args.report_out:
        report = {
            "input": str(args.input),
            "asm_out": str(args.asm_out),
            "mem_out": str(args.mem_out) if args.mem_out else None,
            "instruction_count_original": len(instrs),
            "conditional_branches": [
                {
                    "branch_pc": f"0x{addr:08x}",
                    "branch": next(i.text for i in instrs if i.addr == addr),
                    "reconvergence_pc": f"0x{target:08x}",
                    "reconvergence_label": label_for(target),
                }
                for addr, target in sorted(reconv.items())
            ],
        }
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"Inserted {len(reconv)} SSY reconvergence marker(s): {args.asm_out}")
    if args.mem_out:
        print(f"Wrote transformed memory image: {args.mem_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
