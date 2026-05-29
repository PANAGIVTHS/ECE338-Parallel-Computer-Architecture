import os
import re
import sys
import itertools
from pathlib import Path

DEPTH = 2048

# =======================================================================
# NATIVE 2-PASS ASSEMBLER (Bypasses third-party library bugs entirely)
# =======================================================================

def parse_reg(r):
    return int(r.replace('x', '').replace(',', '').replace('(', '').replace(')', '').strip())

def parse_imm(imm_str):
    if imm_str.lower().startswith('0x') or imm_str.lower().startswith('-0x'):
        return int(imm_str, 16)
    return int(imm_str)

def parse_objdump_addr(addr_str):
    """Parse objdump-style bare hexadecimal addresses such as '1c' or '438'."""
    token = addr_str.strip().rstrip(',')
    sign = -1 if token.startswith('-') else 1
    if token[0] in '+-':
        token = token[1:]
    base = 16 if not token.lower().startswith('0x') else 0
    return sign * int(token, base)

def has_objdump_symbol(parts, target_index):
    """Return true for objdump operands like: jal x1,1c <nbody_kernel>."""
    return len(parts) > target_index + 1 and parts[target_index + 1].startswith('<')

def resolve_control_offset(target, pc, labels, absolute_address=False):
    """Return a byte offset for branch/jal targets.

    Hand-written tests normally use labels or PC-relative immediates. GCC
    objdump output uses absolute byte addresses plus a symbolic annotation, for
    example 'beq x1,x2,438 <fn+0x41c>'. Preserve the old relative-immediate
    behavior unless the objdump annotation tells us the numeric token is an
    absolute PC address.
    """
    if target in labels:
        return (labels[target] - pc) * 4
    if absolute_address:
        return parse_objdump_addr(target) - (pc * 4)
    return parse_imm(target)

def parse_mem_operand(op_str):
    match = re.match(r'(-?\d+)\s*\(\s*(x\d+)\s*\)', op_str)
    if match:
        return int(match.group(1)), parse_reg(match.group(2))
    raise ValueError(f"Invalid memory operand: {op_str}")

def assemble_line(inst, pc, labels):
    """Deterministically maps a single RISC-V assembly instruction to 32-bit Hex"""
    parts = inst.replace(',', ' ').split()
    op = parts[0].lower()
    
    if op == 'nop':
        return 0x00000013
        
    # R-Type
    if op in ['add', 'sub', 'mul', 'and', 'or', 'xor', 'sll', 'srl', 'sra', 'slt', 'sltu']:
        rd, rs1, rs2 = parse_reg(parts[1]), parse_reg(parts[2]), parse_reg(parts[3])
        opcode = 0x33
        f3, f7 = 0x0, 0x00
        if op == 'sub': f7 = 0x20
        elif op == 'mul': f7 = 0x01
        elif op == 'sll': f3 = 0x1
        elif op == 'slt': f3 = 0x2
        elif op == 'sltu': f3 = 0x3
        elif op == 'srl': f3 = 0x5
        elif op == 'sra': f3 = 0x5; f7 = 0x20
        elif op == 'xor': f3 = 0x4
        elif op == 'or': f3 = 0x6
        elif op == 'and': f3 = 0x7
        return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | opcode

    # I-Type
    elif op in ['addi', 'andi', 'ori', 'xori', 'slli', 'srli', 'srai', 'slti', 'sltiu']:
        rd, rs1, imm = parse_reg(parts[1]), parse_reg(parts[2]), parse_imm(parts[3])
        opcode = 0x13
        f3 = 0x0
        if op == 'slti': f3 = 0x2
        elif op == 'sltiu': f3 = 0x3
        elif op == 'xori': f3 = 0x4
        elif op == 'ori': f3 = 0x6
        elif op == 'andi': f3 = 0x7
        elif op == 'slli': f3 = 0x1; imm &= 0x1F
        elif op == 'srli': f3 = 0x5; imm &= 0x1F
        elif op == 'srai': f3 = 0x5; imm = (imm & 0x1F) | 0x400
        imm &= 0xFFF
        return (imm << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | opcode

    # U-Type
    elif op == 'lui':
        rd = parse_reg(parts[1])
        imm = parse_imm(parts[2])

        opcode = 0x37

        # LUI stores upper 20 bits directly
        imm &= 0xFFFFF

        return (imm << 12) | (rd << 7) | opcode

    # Load
    elif op == 'lw':
        rd = parse_reg(parts[1])
        imm, rs1 = parse_mem_operand(parts[2])
        opcode, f3 = 0x03, 0x2
        return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | opcode

    # Store
    elif op == 'sw':
        rs2 = parse_reg(parts[1])
        imm, rs1 = parse_mem_operand(parts[2])
        opcode, f3 = 0x23, 0x2
        imm &= 0xFFF
        return (((imm >> 5) & 0x7F) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | ((imm & 0x1F) << 7) | opcode

    # Branch
    elif op in ['beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu']:
        rs1, rs2, target = parse_reg(parts[1]), parse_reg(parts[2]), parts[3]
        # Dynamically calculate the PC-relative offset using labels or objdump
        # absolute target addresses.
        offset = resolve_control_offset(target, pc, labels, has_objdump_symbol(parts, 3))
        opcode = 0x63
        f3 = {'beq': 0x0, 'bne': 0x1, 'blt': 0x4, 'bge': 0x5, 'bltu': 0x6, 'bgeu': 0x7}[op]
        offset &= 0x1FFF
        return (((offset >> 12) & 1) << 31) | (((offset >> 5) & 0x3F) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (((offset >> 1) & 0xF) << 8) | (((offset >> 11) & 1) << 7) | opcode

    # JAL
    elif op == 'jal':
        rd, target = parse_reg(parts[1]), parts[2]
        offset = resolve_control_offset(target, pc, labels, has_objdump_symbol(parts, 2))
        opcode = 0x6F
        offset &= 0x1FFFFF
        return (((offset >> 20) & 1) << 31) | (((offset >> 1) & 0x3FF) << 21) | (((offset >> 11) & 1) << 20) | (((offset >> 12) & 0xFF) << 12) | (rd << 7) | opcode

    # JALR
    elif op == 'jalr':
        rd = parse_reg(parts[1])
        if '(' in parts[2]: imm, rs1 = parse_mem_operand(parts[2])
        else: rs1, imm = parse_reg(parts[2]), parse_imm(parts[3])
        opcode, f3 = 0x67, 0x0
        return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | opcode
        
    raise ValueError(f"Instruction '{op}' not supported by custom assembler.")


def compile_all_tests():
    current_dir = Path('.')
    asm_files = [Path(sys.argv[1]) / 'program.asm'] if len(sys.argv) > 1 else list(current_dir.glob('tests/test*/program.asm'))

    if not asm_files:
        print("No 'program.asm' files found.")
        return

    print(f"Found {len(asm_files)} tests. Starting native conversion...\n")

    for asm_path in asm_files:
        mem_path = asm_path.with_name("program.mem")
        print(f"Converting: {asm_path}  --->  {mem_path}")

        try:
            with open(asm_path, 'r', encoding='utf-8') as f:
                lines = f.read().splitlines()

            instructions = []
            labels = {}

            # ==========================================
            # PASS 1: Extract instructions and labels
            # ==========================================
            for line in lines:
                code = line.split('#')[0].split('//')[0].strip()
                if not code: continue
                
                if ':' in code:
                    parts = code.split(':', 1)
                    labels[parts[0].strip()] = len(instructions)
                    if parts[1].strip(): instructions.append(parts[1].strip())
                else:
                    instructions.append(code)

            # ==========================================
            # PASS 2: Assemble mapped instructions to hex
            # ==========================================
            hex_lines = []
            for pc, inst in enumerate(instructions):
                machine_code = assemble_line(inst, pc, labels)
                hex_lines.append(f"{machine_code:08x}")

            # Pad remaining memory with NOPs (0x00000000)
            while len(hex_lines) < DEPTH:
                hex_lines.append("00000000")
            hex_lines = hex_lines[:DEPTH]

            # Write perfectly mapped output
            with open(mem_path, 'w', encoding='utf-8') as f_out:
                f_out.write("\n".join(hex_lines) + "\n")

        except Exception as e:
            print(f"  [Error] Failed to convert {asm_path}: {e}")

    print("\nConversion completed successfully!")

if __name__ == "__main__":
    compile_all_tests()