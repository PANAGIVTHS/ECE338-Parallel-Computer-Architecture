# One load, two backends: even lanes read SMEM, odd lanes read GMEM,
# in the same instruction. The results go to a framebuffer row.
slli x6, x31, 2         # lane * 4
addi x7, x31, 7
sw   x7, 0(x6)          # SMEM[lane] = lane + 7
andi x8, x31, 1         # 1 on odd lanes
lui  x9, 0x04800        # GMEM_BASE
mul  x10, x8, x9        # odd lanes: GMEM_BASE, even lanes: 0 (SMEM)
add  x10, x10, x6
lw   x11, 0(x10)
lui  x5, 0x04004        # FB0 + 0x4000
add  x5, x5, x6
sw   x11, 0(x5)
addi  x17, x0, 0
ecall