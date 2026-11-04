# DDR: one store to both framebuffers. Even lanes write FB0, odd lanes FB1
# (FB1 = FB0 + 0x400000), so the instruction forms two groups (two bursts).
andi x6, x31, 1
slli x6, x6, 22         # 0 or FB1 - FB0
lui  x5, 0x18000
add  x5, x5, x6
srli x7, x31, 1
slli x7, x7, 2
add  x5, x5, x7         # word lane / 2 of its framebuffer
xori x8, x31, -1        # value = ~lane
sw   x8, 0(x5)
jalr x0, 0(x1)
