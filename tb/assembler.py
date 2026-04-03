# Documentation: https://celebi-pkg.github.io/riscv-assembler/index.html

from riscv_assembler.convert import AssemblyConverter as AC


PROGRAM = """
addi x1, x1, 7
add x2, x1, x1
sub x3, x2, x1
"""

convert = AC(output_mode = 'p', nibble_mode = True, hex_mode = False)

convert(PROGRAM, "program.hex")
