import os
import io
import itertools
import contextlib
import re
import sys
from pathlib import Path
from riscv_assembler.convert import AssemblyConverter as AC

DEPTH = 2048

# ===================== MANUAL BYPASS FUNCTIONS =====================
def parse_reg(r):
    return int(r.replace('x', '').replace(',', '').replace('(', '').replace(')', ''))

def parse_imm(imm_str):
    if imm_str.lower().startswith('0x') or imm_str.lower().startswith('-0x'):
        return int(imm_str, 16)
    return int(imm_str)

def assemble_manual(line):
    """Manually computes the hex for the 2 unsupported instructions"""
    parts = line.replace(',', ' ').split()
    op = parts[0].lower()
    if op == 'slt':
        rd = parse_reg(parts[1])
        rs1 = parse_reg(parts[2])
        rs2 = parse_reg(parts[3])
        b = (0x00 << 25) | (rs2 << 20) | (rs1 << 15) | (0x2 << 12) | (rd << 7) | 0x33
        return f"{b:08x}"
    elif op == 'srli':
        rd = parse_reg(parts[1])
        rs1 = parse_reg(parts[2])
        imm = parse_imm(parts[3])
        shamt = imm & 0x1F
        b = (0x00 << 25) | (shamt << 20) | (rs1 << 15) | (0x5 << 12) | (rd << 7) | 0x13
        return f"{b:08x}"
    elif op == 'jalr':
        rd = parse_reg(parts[1])
        if '(' in parts[2]:
            imm_str, rs1_str = parts[2].split('(')
            imm = parse_imm(imm_str)
            rs1 = parse_reg(rs1_str)
        else:
            rs1 = parse_reg(parts[2])
            imm = parse_imm(parts[3])
        imm = imm & 0xFFF
        b = (imm << 20) | (rs1 << 15) | (0x0 << 12) | (rd << 7) | 0x67
        return f"{b:08x}"
    return None

def convert_hex_immediates(match):
    """Converts 0x strings to decimal integers"""
    val_str = match.group(0)
    sign = -1 if val_str.startswith('-') else 1
    val = sign * int(val_str.replace('-', ''), 16)
    return str(val)
# ===================================================================

def compile_all_tests():
    # Keep output_mode='p' (print) since it's the only one that outputs the data
    convert = AC(output_mode='p', nibble_mode=False, hex_mode=True)

    # Search for all 'program.asm' files inside any directory starting with 'test'
    current_dir = Path('.')
    
    if len(sys.argv) > 1:
        target_dir = sys.argv[1]
        asm_files = [Path(target_dir) / 'program.asm']
    else:
        asm_files = list(current_dir.glob('test*/program.asm'))

    if not asm_files:
        print("No 'program.asm' files found.")
        return

    print(f"Found {len(asm_files)} tests. Starting conversion...\n")

    for asm_path in asm_files:
        mem_path = asm_path.with_name("program.mem")

        print(f"Converting: {asm_path}  --->  {mem_path}")

        try:
            # Read the Assembly code from the .asm file
            with open(asm_path, 'r', encoding='utf-8') as f:
                raw_asm_code = f.read()

            # --- 1. PRE-PROCESS 0x VALUES FOR ENTIRE FILE ---
            # This fixes the library crashing on '0x2' by making it '2' before doing anything
            raw_asm_code = re.sub(r'-?0[xX][0-9a-fA-F]+', convert_hex_immediates, raw_asm_code)

            # ===================== COMMENT REMOVAL START =====================
            cleaned_lines = []
            for line in raw_asm_code.splitlines():
                # Split at '#' or '//' and keep only the code portion
                code_only = line.split('#')[0].split('//')[0]
                code_only = code_only.strip()
                
                # Only keep lines that still have instructions on them
                if code_only:
                    cleaned_lines.append(code_only)
            
            asm_code = '\n'.join(cleaned_lines)
            # ===================== COMMENT REMOVAL END =======================

            # Skip the file if it's completely empty
            if not asm_code.strip():
                print(f"  [Warning] File {asm_path} is empty or only contains comments. Skipped.")
                continue

            # ===================== ASSEMBLER BUG FIX START =====================
            # This regex finds "sw rs2, imm(rs1)" and halves the immediate value
            # to bypass the riscv-assembler S-Type shifting bug.
            def fix_store_offset(match):
                rs2 = match.group(1)
                imm = int(match.group(2))
                rs1 = match.group(3)
                fixed_imm = imm // 2
                return f"sw {rs2}, {fixed_imm}({rs1})"
                
            asm_code = re.sub(r'sw\s+(x\d+)\s*,\s*(-?\d+)\((x\d+)\)', fix_store_offset, asm_code)
            # ===================== ASSEMBLER BUG FIX END =======================

            # ===================== INSTRUCTION BYPASS START ====================
            safe_lines = []
            custom_hex_map = {}
            
            for i, line in enumerate(asm_code.splitlines()):
                op = line.replace(',', ' ').split()[0].lower() if line.strip() else ""
                if op in ['slt', 'srli', 'jalr']:
                    # Manually convert the instruction to hex
                    custom_hex = assemble_manual(line)
                    if custom_hex:
                        custom_hex_map[i] = custom_hex
                    # Give the library a dummy instruction of the same length
                    safe_lines.append("addi x0, x0, 0")
                else:
                    safe_lines.append(line)
                    
            asm_code = '\n'.join(safe_lines)
            # ===================== INSTRUCTION BYPASS END ======================

            # Create an in-memory string buffer
            f_buffer = io.StringIO()

            # Redirect standard output (stdout) into our buffer
            # This captures all the print() statements executed by the library
            with contextlib.redirect_stdout(f_buffer):
                convert(asm_code)

            # Retrieve the captured text from the buffer
            hex_result = f_buffer.getvalue()

            clean_hex = hex_result.replace("0x", "")

            # ===================== FIX START =====================
            lines = clean_hex.strip().splitlines()

            # clean empty lines
            lines = [line.strip() for line in lines if line.strip()]

            # --- RESTORE OUR MANUALLY CALCULATED HEX ---
            for idx, hex_val in custom_hex_map.items():
                if idx < len(lines):
                    lines[idx] = hex_val

            # pad missing instructions with zeros
            while len(lines) < DEPTH:
                lines.append("00000000")

            # truncate if overflow
            lines = lines[:DEPTH]
            # ===================== FIX END =====================

            # Write the captured text to the actual .mem file
            with open(mem_path, 'w', encoding='utf-8') as f_out:
                f_out.write("\n".join(lines) + "\n")

        except Exception as e:
            print(f"  [Error] Failed to convert {asm_path}: {e}")

    print("\nConversion completed successfully!")

def generate_random_instructions() -> str:
    program = ""
    registers = [f"x{i}" for i in range(4)]
    
    immediates = list(range(-10, 11)) + [-2048, 2047]
    mem_offsets = [-8, -4, 0, 4, 8]
    branch_offsets = [-8, -4, 4, 8]

    for rd, rs1 in itertools.product(registers, repeat=2):
        for imm in immediates:
            program += f"addi {rd}, {rs1}, {imm}\n"

    for rd, rs1, rs2 in itertools.product(registers, repeat=3):
        program += f"add {rd}, {rs1}, {rs2}\n"

    for rd, rs1, rs2 in itertools.product(registers, repeat=3):
        program += f"sub {rd}, {rs1}, {rs2}\n"

    for rd, rs1 in itertools.product(registers, repeat=2):
        for imm in mem_offsets:
            program += f"lw {rd}, {imm}({rs1})\n"

    for rs2, rs1 in itertools.product(registers, repeat=2):
        for imm in mem_offsets:
            program += f"sw {rs2}, {imm}({rs1})\n"

    for rs1, rs2 in itertools.product(registers, repeat=2):
        for imm in branch_offsets:
            program += f"beq {rs1}, {rs2}, {imm}\n"

    program += "nop\n"

    return program

if __name__ == "__main__":
    compile_all_tests()