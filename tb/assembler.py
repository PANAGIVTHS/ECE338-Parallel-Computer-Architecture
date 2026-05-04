import os
import io
import itertools
import contextlib
import re
from pathlib import Path
from riscv_assembler.convert import AssemblyConverter as AC

def compile_all_tests():
    # Keep output_mode='p' (print) since it's the only one that outputs the data
    convert = AC(output_mode='p', nibble_mode=False, hex_mode=True)

    # Search for all 'program.asm' files inside any directory starting with 'test'
    current_dir = Path('.')
    asm_files = list(current_dir.glob('test*/program.asm'))

    if not asm_files:
        print("No 'program.asm' files found in 'test*' directories.")
        return

    print(f"Found {len(asm_files)} tests. Starting conversion...\n")

    for asm_path in asm_files:
        mem_path = asm_path.with_name("program.mem")

        print(f"Converting: {asm_path}  --->  {mem_path}")

        try:
            # Read the Assembly code from the .asm file
            with open(asm_path, 'r', encoding='utf-8') as f:
                raw_asm_code = f.read()

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

            DEPTH = 1024  # memory size requirement

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