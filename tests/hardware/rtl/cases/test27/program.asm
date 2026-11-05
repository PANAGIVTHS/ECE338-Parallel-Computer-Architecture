# DDR: 16 framebuffer rows of a 1280-pixel FB0 in a loop. Each row is one
# group (one burst); rows are 5120 B apart.
lui  x5, 0x18000
slli x6, x31, 2
add  x5, x5, x6         # pixel (0, lane)
lui  x9, 0x1
addi x9, x9, 1024       # row stride 5120 B
addi x10, x0, 0         # row
addi x11, x0, 16        # rows
row:
slli x12, x10, 16
add  x12, x12, x31      # value = row << 16 | lane
sw   x12, 0(x5)
add  x5, x5, x9
addi x10, x10, 1
bne  x10, x11, row
jalr x0, 0(x1)
