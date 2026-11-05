# Sub-word loads: every byte and halfword of a word with all its sign bits set,
# a word with them clear, their consumers, and each lane addressing its own
# byte or halfword. Each lane stores every result in its own slot, for the
# benches that only check memory.
lui   x3, 0x1
slli  x4, x31, 2
add   x3, x3, x4        # x3: 0x1000 + lane * 4, one array every 128 bytes

addi  x5, x0, 256
lui   x6, 0x80F1E
addi  x6, x6, 0x2D3     # 0x80F1E2D3: every byte negative
lui   x7, 0x7F6E6
addi  x7, x7, -0x2B4    # 0x7F6E5D4C: every byte positive
sw    x6, 0(x5)
sw    x7, 4(x5)

lb    x8, 0(x5)         # 0xFFFFFFD3
lb    x9, 1(x5)         # 0xFFFFFFE2
lb    x10, 2(x5)        # 0xFFFFFFF1
lb    x11, 3(x5)        # 0xFFFFFF80
lbu   x12, 0(x5)        # 0x000000D3
lbu   x13, 1(x5)        # 0x000000E2
lbu   x14, 2(x5)        # 0x000000F1
lbu   x15, 3(x5)        # 0x00000080
lh    x16, 0(x5)        # 0xFFFFE2D3
lh    x17, 2(x5)        # 0xFFFF80F1
lhu   x18, 0(x5)        # 0x0000E2D3
lhu   x19, 2(x5)        # 0x000080F1
lb    x20, 7(x5)        # 0x0000007F
lh    x21, 4(x5)        # 0x00005D4C

lb    x22, 3(x5)
add   x23, x22, x22     # load-use: 0xFFFFFF00
lhu   x24, 2(x5)
sw    x24, 8(x5)        # load to store data: 0x000080F1
lb    x25, 0(x5)
blt   x25, x0, negative # taken only if the sign was extended
addi  x25, x0, 1        # flushed
negative:
lb    x0, 1(x5)         # a load to x0 writes nothing

sw    x8, 0(x3)
sw    x9, 128(x3)
sw    x10, 256(x3)
sw    x11, 384(x3)
sw    x12, 512(x3)
sw    x13, 640(x3)
sw    x14, 768(x3)
sw    x15, 896(x3)
sw    x16, 1024(x3)
sw    x17, 1152(x3)
sw    x18, 1280(x3)
sw    x19, 1408(x3)
sw    x20, 1536(x3)
sw    x21, 1664(x3)
sw    x23, 1792(x3)
sw    x25, 1920(x3)

lui   x6, 0x9E378
addi  x6, x6, -0x64F    # 0x9E3779B1: spreads the lane id over all four bytes
addi  x7, x31, 1
mul   x7, x7, x6
sw    x7, 1024(x4)      # DMEM[0x400 + lane * 4] = this lane's word
slli  x8, x31, 1
lb    x9, 1024(x31)     # each lane its own byte
lbu   x10, 1024(x31)
lh    x11, 1024(x8)     # each lane its own halfword
lhu   x12, 1024(x8)
lui   x13, 0x2
add   x13, x13, x4
sw    x9, -1024(x13)    # x13: 0x2000 + lane * 4, arrays below it
sw    x10, -896(x13)
sw    x11, -768(x13)
sw    x12, -640(x13)
jalr  x0, 0(x1)
