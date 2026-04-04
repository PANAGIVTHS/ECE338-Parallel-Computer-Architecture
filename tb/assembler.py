import os
import io
import itertools
import contextlib
from pathlib import Path
# Documentation: https://celebi-pkg.github.io/riscv-assembler/index.html
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
                asm_code = f.read()

            # Skip the file if it's completely empty
            if not asm_code.strip():
                print(f"  [Warning] File {asm_path} is empty. Skipped.")
                continue

            # Create an in-memory string buffer
            f_buffer = io.StringIO()
            
            # Redirect standard output (stdout) into our buffer
            # This captures all the print() statements executed by the library
            with contextlib.redirect_stdout(f_buffer):
                convert(asm_code)
            
            # Retrieve the captured text from the buffer
            hex_result = f_buffer.getvalue()

            clean_hex = hex_result.replace("0x", "")

            # Write the captured text to the actual .mem file
            with open(mem_path, 'w', encoding='utf-8') as f_out:
                # Strip leading/trailing whitespaces or newlines printed by the library,
                # and append a single newline at the end for clean formatting
                f_out.write(clean_hex.strip() + '\n00000000\n')  # Add a NOP

        except Exception as e:
            print(f"  [Error] Failed to convert {asm_path}: {e}")

    print("\nConversion completed successfully!")

def generate_random_instructions() -> str:
    program = ""

    # Define registers (x0, ..., x31)
    registers = [f"x{i}" for i in range(4)]

    immediates = list(range(-10, 11)) + [-2048, 2047]

    # addi
    for rd, rs1 in itertools.product(registers, repeat=2):
        for imm in immediates:
            program += f"addi {rd}, {rs1}, {imm}\n"

    # add
    for rd, rs1, rs2 in itertools.product(registers, repeat=3):
        program += f"add {rd}, {rs1}, {rs2}\n"

    # sub
    for rd, rs1, rs2 in itertools.product(registers, repeat=3):
        program += f"sub {rd}, {rs1}, {rs2}\n"

    return program

if __name__ == "__main__":
    compile_all_tests()