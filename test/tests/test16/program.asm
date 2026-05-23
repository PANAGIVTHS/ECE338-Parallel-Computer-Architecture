# XOR/XORI/ORI instruction test
# Verifies register-register XOR, sign-extended XORI immediates, ORI immediates,
# forwarding between the new logical operations, and x0 write suppression.

addi x2, x0, 0x55      # x2 = 0x00000055
addi x3, x0, 0x33      # x3 = 0x00000033
xor  x4, x2, x3        # x4 = 0x00000066
xori x5, x4, 0x0f      # x5 = 0x00000069
ori  x6, x5, 0x100     # x6 = 0x00000169
xori x7, x0, -1        # x7 = 0xffffffff, proves sign-extended I-immediate
ori  x8, x7, 0x123     # x8 = 0xffffffff
xor  x9, x8, x6        # x9 = 0xfffffe96
xor  x0, x7, x7        # x0 must remain 0
sw   x4, 0(x0)
sw   x5, 4(x0)
sw   x6, 8(x0)
sw   x7, 12(x0)
sw   x8, 16(x0)
sw   x9, 20(x0)
sw   x0, 24(x0)
jalr x0, 0(x1)
