# DDR: every lane stores the same value to the same framebuffer word. Same
# value, so the result is defined although the winning lane is not.
lui  x5, 0x18002
lui  x6, 0x5
addi x6, x6, 90         # 0x505A
sw   x6, 0(x5)
jalr x0, 0(x1)
