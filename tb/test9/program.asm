addi x1, x0, 4
addi x2, x0, 5
mul  x3, x1, x2
addi x4, x0, 8
add  x0, x3, x4
mul  x5, x2, x2
add  x6, x3, x5
sw   x6, 0(x0)
lw   x7, 0(x0)
add  x8, x7, x1
sw   x8, 4(x0)
sw   x7, 8(x0)
sub  x9, x8, x7
beq  x9, x1, branch_1
addi x31, x0, 999
addi x31, x0, 999
branch_1:
lw   x10, 4(x0)
lw   x11, 8(x0)
add  x12, x10, x11
sw   x12, 12(x0)
mul  x13, x2, x1
nop
sub  x14, x13, x1
sw   x14, 16(x0)
beq  x0, x0, branch_2
addi x31, x0, 999
branch_2:
lw   x15, 12(x0)
lw   x16, 16(x0)
mul  x17, x1, x1
sub  x18, x16, x17
sw   x18, 20(x0)
sw   x15, 24(x0)
sw   x10, 28(x0)