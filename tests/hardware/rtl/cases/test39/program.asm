# Sustained DDR loads: each lane sums its column of 16 GMEM rows (one
# burst per row), with the add right after each load.
lui  x5, 0x18801        # GMEM_BASE + 0x1000
slli x6, x31, 2
add  x5, x5, x6
addi x8, x0, 16         # rows left
addi x12, x0, 0         # sum
loop:
lw   x7, 0(x5)
add  x12, x12, x7
addi x5, x5, 128        # next row
addi x8, x8, -1
bne  x8, x0, loop
jalr x0, 0(x1)