# INITIALIZATION
addi x1, x0, 0  # Reserved Base Memory Pointer (Address 0)
addi x2, x0, -6
addi x3, x0, -39
addi x4, x0, -37
addi x5, x0, 42

# RANDOM OPERATIONS
mul x9, x18, x5
beq x2, x3, skip_0
sw x22, 1580(x1)
mul x19, x30, x2
addi x16, x29, -87
lw x24, 1040(x1)
skip_0:
sub x24, x11, x27
sub x20, x30, x4
add x11, x27, x17
sw x6, 2328(x1)
addi x30, x6, -27
sw x16, 2408(x1)
beq x3, x11, skip_1
sw x3, 2900(x1)
sw x29, 1492(x1)
skip_1:
beq x29, x5, skip_2
addi x24, x16, 34
skip_2:
sub x7, x4, x12
addi x5, x19, -53
lw x4, 936(x1)
beq x21, x26, skip_3
add x20, x7, x2
skip_3:
add x27, x8, x22
mul x8, x11, x7
beq x17, x5, skip_4
beq x12, x16, skip_5
addi x4, x3, 42
lw x20, 600(x1)
skip_4:
sub x7, x23, x5
beq x12, x30, skip_6
addi x10, x23, 20
sub x4, x5, x27
sw x20, 3312(x1)
skip_5:
mul x30, x18, x20
skip_6:
sub x23, x9, x12
add x19, x9, x28
sub x16, x30, x20
lw x9, 1712(x1)
mul x23, x7, x11
add x6, x3, x18
sub x16, x18, x5
addi x25, x6, 50
beq x23, x2, skip_7
mul x21, x18, x15
skip_7:
mul x20, x26, x3
beq x12, x6, skip_8
add x2, x22, x6
skip_8:
sw x13, 20(x1)
sub x20, x17, x12
sw x27, 1564(x1)

# INFINITE LOOP TRAP
end_trap:
beq x0, x0, end_trap
