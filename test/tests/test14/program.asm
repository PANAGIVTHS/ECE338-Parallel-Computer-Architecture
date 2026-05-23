# Extensive signed branch and JAL control-flow test
# Covers BLT/BGE taken and not-taken paths, equality boundaries,
# signed negative/positive comparisons, x0 operands, flush shadows,
# JAL x0 unconditional jumps, JAL link writes, and post-JAL branches.

# Accumulators:
#   x20 = success signature from every intended path
#   x28 = failure counter touched only by incorrectly executed paths
addi x20, x0, 0
addi x28, x0, 0
addi x5,  x0, 0

# Boundary values.
addi x3, x0, 5
addi x4, x0, 10
addi x6, x0, -1
addi x7, x0, 0
lui  x8, 0x80000      # most-negative signed 32-bit value
addi x9, x0, 2047
addi x10, x0, -2048

nop
nop
nop
nop
nop

# BLT taken: positive less-than.
blt  x3, x4, blt_pos_taken
addi x28, x28, 1      # must be flushed
addi x28, x28, 1      # must be flushed
addi x28, x28, 1      # must be flushed
blt_pos_taken:
nop
nop
nop
addi x20, x20, 1
nop
nop

# BLT not taken: positive greater-than.
blt  x4, x3, blt_pos_bad
addi x20, x20, 2
jal  x0, after_blt_pos_bad
blt_pos_bad:
addi x28, x28, 2      # must be skipped
after_blt_pos_bad:
nop
nop

# BLT taken: negative is less than zero.
blt  x6, x7, blt_neg_taken
addi x28, x28, 4      # must be flushed
addi x28, x28, 4      # must be flushed
blt_neg_taken:
nop
nop
addi x20, x20, 4
nop
nop

# BLT not taken: zero is not less than negative.
blt  x7, x6, blt_zero_neg_bad
addi x20, x20, 8
jal  x0, after_blt_zero_neg_bad
blt_zero_neg_bad:
addi x28, x28, 8      # must be skipped
after_blt_zero_neg_bad:
nop
nop

# BLT not taken on equality.
blt  x3, x3, blt_equal_bad
addi x20, x20, 16
jal  x0, after_blt_equal_bad
blt_equal_bad:
addi x28, x28, 16     # must be skipped
after_blt_equal_bad:
nop
nop

# BLT signed edge: INT_MIN < -2048.
blt  x8, x10, blt_min_taken
addi x28, x28, 32     # must be flushed
addi x28, x28, 32     # must be flushed
blt_min_taken:
nop
nop
addi x20, x20, 32
nop
nop

# BGE taken: positive greater-than.
bge  x4, x3, bge_pos_taken
addi x28, x28, 64     # must be flushed
addi x28, x28, 64     # must be flushed
bge_pos_taken:
nop
nop
addi x20, x20, 64
nop
nop

# BGE not taken: positive less-than.
bge  x3, x4, bge_pos_bad
addi x20, x20, 128
jal  x0, after_bge_pos_bad
bge_pos_bad:
addi x28, x28, 128    # must be skipped
after_bge_pos_bad:
nop
nop

# BGE taken on equality.
bge  x3, x3, bge_equal_taken
addi x28, x28, 256    # must be flushed
addi x28, x28, 256    # must be flushed
bge_equal_taken:
nop
nop
addi x20, x20, 256
nop
nop

# BGE taken: zero >= negative.
bge  x7, x6, bge_zero_neg_taken
addi x28, x28, 512    # must be flushed
addi x28, x28, 512    # must be flushed
bge_zero_neg_taken:
nop
nop
addi x20, x20, 512
nop
nop

# BGE not taken: negative is not >= zero.
bge  x6, x7, bge_neg_zero_bad
addi x20, x20, 1024
jal  x0, after_bge_neg_zero_bad
bge_neg_zero_bad:
addi x28, x28, 1024   # must be skipped
after_bge_neg_zero_bad:
nop
nop

# JAL x0 must jump without writing a link.
addi x11, x0, 123
jal  x0, jal_x0_target
addi x28, x28, 1      # must be flushed
addi x28, x28, 1      # must be flushed
jal_x0_target:
nop
nop
addi x20, x20, 37

# JAL with rd must write PC+4 link and jump over flushed instructions.
jal  x5, jal_link_target
addi x28, x28, 1      # must be flushed
addi x28, x28, 1      # must be flushed
jal_link_target:
nop
nop
addi x20, x20, 73

# Additional post-JAL branch checks around equal values.
addi x12, x0, 3
addi x13, x0, 3
bge  x12, x13, equal_after_jal_bge_ok
addi x28, x28, 1      # must be flushed/skipped
equal_after_jal_bge_ok:
nop
nop
addi x20, x20, 109
blt  x13, x12, equal_after_jal_blt_bad
addi x20, x20, 149
jal  x0, after_equal_after_jal_blt_bad
equal_after_jal_blt_bad:
addi x28, x28, 1      # must be skipped
after_equal_after_jal_blt_bad:

# Expected signature:
# 1+2+4+8+16+32+64+128+256+512+1024+37+73+109+149 = 2415
sw   x20, 0(x0)
sw   x28, 4(x0)      # expected 0 if no wrong-path instruction committed
sw   x5,  8(x0)      # expected JAL link address (PC + 4)
sw   x12, 12(x0)     # expected equality operand: 3
sw   x11, 16(x0)     # proves JAL x0 did not clobber x11

# Give all cores enough cycles to retire their queued stores before core 0 halts.
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop

jalr x0, 0(x1)
