# DDR: every other word over a seeded framebuffer (ddr_seed.mem fills the odd
# words). The bursts carry WSTRB = 0 for the gaps, so the seed must survive.
lui  x5, 0x18001
slli x6, x31, 3         # lane * 8
add  x5, x5, x6
addi x7, x31, 100
sw   x7, 0(x5)
jalr x0, 0(x1)
