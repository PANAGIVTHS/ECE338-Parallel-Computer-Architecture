# One load, two backends: even lanes read DMEM, odd lanes read the texture,
# in the same instruction. The results go to a framebuffer row.
slli x6, x31, 2         # lane * 4
addi x7, x31, 7
sw   x7, 0(x6)          # DMEM[lane] = lane + 7
andi x8, x31, 1         # 1 on odd lanes
lui  x9, 0x18800        # TEX_BASE
mul  x10, x8, x9        # odd lanes: TEX_BASE, even lanes: 0 (DMEM)
add  x10, x10, x6
lw   x11, 0(x10)
lui  x5, 0x18004        # FB0 + 0x4000
add  x5, x5, x6
sw   x11, 0(x5)
jalr x0, 0(x1)
