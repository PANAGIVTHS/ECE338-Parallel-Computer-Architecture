# Documentation: https://celebi-pkg.github.io/riscv-assembler/index.html

from riscv_assembler.convert import AssemblyConverter as AC

import itertools


def generate_instructions() -> str:
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

convert = AC(output_mode = 'p', nibble_mode = False, hex_mode = True)

convert(generate_instructions(), "program.hex")
