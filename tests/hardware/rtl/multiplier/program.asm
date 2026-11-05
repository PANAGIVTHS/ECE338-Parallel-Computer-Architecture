# Consecutive independent products, followed by dependent products and ordinary ALU.
addi x3, x0, -7
addi x4, x0, 11
addi x5, x0, 13
mul x6, x3, x4
mul x7, x4, x5
mul x8, x5, x3
mul x9, x6, x7
mul x10, x8, x9
add x11, x10, x6
# Keep per-core memory independent while exercising crossbar stalls and load forwarding.
slli x20, x31, 4
sw x11, 0(x20)
lw x12, 0(x20)
mul x13, x12, x4
mul x14, x5, x3
xor x15, x13, x14
# x0 is not tracked as a valid multiplication destination.
mul x0, x3, x4
addi x16, x0, 17
mul x17, x16, x4
sw x17, 4(x20)
lw x18, 4(x20)
add x19, x18, x15
nop
nop
nop
jalr x0, 0(x1)
