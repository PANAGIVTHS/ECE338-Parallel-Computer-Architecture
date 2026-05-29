# BNE instruction coverage test
#
# Each case writes an independent signature to DMEM so a wrong branch decision or
# wrong target is easy to identify.  The test covers taken/not-taken paths,
# equality, inequality, zero operands, negative/high-bit values, x0 comparisons,
# forwarding into BNE operands, and a backward BNE loop.

# Case 1: equal positive values -> BNE must NOT branch
addi x2, x0, 42
addi x3, x0, 42
bne  x2, x3, case1_fail
addi x10, x0, 1
sw   x10, 0(x0)
jal  x0, case1_done
case1_fail:
addi x10, x0, 201
sw   x10, 0(x0)
case1_done:

# Case 2: unequal positive values -> BNE must branch
addi x2, x0, 42
addi x3, x0, 43
bne  x2, x3, case2_pass
addi x10, x0, 202
sw   x10, 4(x0)
jal  x0, case2_done
case2_pass:
addi x10, x0, 2
sw   x10, 4(x0)
case2_done:

# Case 3: zero vs non-zero -> BNE must branch
addi x4, x0, 0
addi x5, x0, 1
bne  x4, x5, case3_pass
addi x10, x0, 203
sw   x10, 8(x0)
jal  x0, case3_done
case3_pass:
addi x10, x0, 3
sw   x10, 8(x0)
case3_done:

# Case 4: zero vs zero -> BNE must NOT branch
bne  x0, x0, case4_fail
addi x10, x0, 4
sw   x10, 12(x0)
jal  x0, case4_done
case4_fail:
addi x10, x0, 204
sw   x10, 12(x0)
case4_done:

# Case 5: equal all-ones values -> BNE must NOT branch
addi x6, x0, -1
addi x7, x0, -1
bne  x6, x7, case5_fail
addi x10, x0, 5
sw   x10, 16(x0)
jal  x0, case5_done
case5_fail:
addi x10, x0, 205
sw   x10, 16(x0)
case5_done:

# Case 6: negative-looking value vs positive value -> BNE must branch
addi x6, x0, -1
addi x7, x0, 1
bne  x6, x7, case6_pass
addi x10, x0, 206
sw   x10, 20(x0)
jal  x0, case6_done
case6_pass:
addi x10, x0, 6
sw   x10, 20(x0)
case6_done:

# Case 7: high-bit values differ by one bit -> BNE must branch
lui  x8, 0x80000       # x8 = 0x80000000
lui  x9, 0x80000
addi x9, x9, -1        # x9 = 0x7fffffff
bne  x8, x9, case7_pass
addi x10, x0, 207
sw   x10, 24(x0)
jal  x0, case7_done
case7_pass:
addi x10, x0, 7
sw   x10, 24(x0)
case7_done:

# Case 8: explicit x0 equality -> BNE must NOT branch
addi x11, x0, 0
bne  x0, x11, case8_fail
addi x10, x0, 8
sw   x10, 28(x0)
jal  x0, case8_done
case8_fail:
addi x10, x0, 208
sw   x10, 28(x0)
case8_done:

# Case 9: branch operands produced immediately before BNE, equal -> NOT taken
addi x12, x0, 10
addi x13, x0, 10
bne  x12, x13, case9_fail
addi x10, x0, 9
sw   x10, 32(x0)
jal  x0, case9_done
case9_fail:
addi x10, x0, 209
sw   x10, 32(x0)
case9_done:

# Case 10: branch operand produced immediately before BNE, unequal -> taken
addi x12, x0, 10
addi x13, x0, 11
bne  x12, x13, case10_pass
addi x10, x0, 210
sw   x10, 36(x0)
jal  x0, case10_done
case10_pass:
addi x10, x0, 10
sw   x10, 36(x0)
case10_done:

# Case 11: backward BNE loop; taken repeatedly, then not taken at equality
addi x14, x0, 0
addi x15, x0, 5
case11_loop:
addi x14, x14, 1
bne  x14, x15, case11_loop
sw   x14, 40(x0)

# Case 12: same non-zero register compared with itself -> BNE must NOT branch
addi x16, x0, 123
bne  x16, x16, case12_fail
addi x10, x0, 12
sw   x10, 44(x0)
jal  x0, end
case12_fail:
addi x10, x0, 212
sw   x10, 44(x0)

end:
jalr x0, 0(x1)
