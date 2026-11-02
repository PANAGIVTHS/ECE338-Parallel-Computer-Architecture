# DDR: one framebuffer row. Each lane writes its pixel to FB0 (32 lanes x 4 B
# = one 128 B group, one burst) and keeps a copy in DMEM.
lui  x5, 0x18000        # x5 = FB0
slli x6, x31, 2         # lane * 4
add  x7, x5, x6         # this lane's pixel
lui  x8, 0xFF0          # 0x00FF0000
add  x8, x8, x31        # color = 0x00FF0000 + lane
sw   x8, 0(x7)
sw   x8, 0(x6)          # DMEM copy
jalr x0, 0(x1)
