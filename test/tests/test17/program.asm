# BLTU/BGEU instruction test
# Verifies unsigned branch comparisons, including cases that differ from signed BLT/BGE,
# equality behavior, branch-not-taken fallthrough, and branch-taken target selection.

addi x2, x0, -1       # x2 = 0xffffffff (unsigned max, signed -1)
addi x3, x0, 1        # x3 = 1

bltu x2, x3, fail1    # unsigned: 0xffffffff < 1 is false; must fall through
addi x10, x0, 1
sw   x10, 0(x0)

bltu x3, x2, pass2    # unsigned: 1 < 0xffffffff is true; must branch
fail1:
addi x10, x0, 201
sw   x10, 4(x0)
jal  x0, after2
pass2:
addi x10, x0, 2
sw   x10, 4(x0)
after2:

bgeu x3, x2, fail3    # unsigned: 1 >= 0xffffffff is false; must fall through
addi x10, x0, 3
sw   x10, 8(x0)

bgeu x2, x3, pass4    # unsigned: 0xffffffff >= 1 is true; must branch
fail3:
addi x10, x0, 203
sw   x10, 12(x0)
jal  x0, after4
pass4:
addi x10, x0, 4
sw   x10, 12(x0)
after4:

bgeu x2, x2, pass5    # equal operands: BGEU must branch
addi x10, x0, 205
sw   x10, 16(x0)
jal  x0, after5
pass5:
addi x10, x0, 5
sw   x10, 16(x0)
after5:

bltu x2, x2, fail6    # equal operands: BLTU must not branch
addi x10, x0, 6
sw   x10, 20(x0)
jal  x0, end
fail6:
addi x10, x0, 206
sw   x10, 20(x0)

end:
jalr x0, 0(x1)
