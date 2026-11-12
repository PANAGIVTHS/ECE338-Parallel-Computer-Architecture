# GMEM is read-write: stores and loads to the same DDR words. A store
# completes on its B response, so the load right after it must see it: each
# lane's own word, its neighbour's word, byte and halfword stores over seeded
# words (ddr_seed.mem) read back whole and in part, four lanes' bytes merged
# into one word, and an in-place read-modify-write loop. Each lane stores every
# result in its own slot, for the benches that only check memory; the model
# checks the final GMEM words (ddr.mem).
lui   x3, 0x1
slli  x4, x31, 2
add   x3, x3, x4        # x3: 0x1000 + lane * 4, one array every 128 bytes

lui   x5, 0x18802       # GMEM_BASE + 0x2000
add   x6, x5, x4        # x6: this lane's word

lui   x7, 0x9E378
addi  x7, x7, -0x64F    # 0x9E3779B1: spreads the lane id over all four bytes
addi  x8, x31, 1
mul   x7, x7, x8        # x7: (lane + 1) * 0x9E3779B1
sw    x7, 0(x6)
lw    x8, 0(x6)         # store then load of the same word: x7
xori  x9, x31, 1
slli  x9, x9, 2
add   x9, x5, x9
lw    x9, 0(x9)         # the word lane ^ 1 stored

andi  x10, x31, 3
add   x10, x6, x10
addi  x11, x31, 0x80
sb    x11, 256(x10)     # byte lane % 4 of seeded word GMEM + 0x2100 + lane * 4
lw    x12, 256(x6)      # 0xA5A5A5A5 with that byte replaced
lbu   x13, 256(x10)     # 0x80 + lane

andi  x14, x31, 1
slli  x14, x14, 1
add   x14, x6, x14
lui   x15, 0x8
add   x15, x15, x31
sh    x15, 512(x14)     # half lane % 2 of seeded word GMEM + 0x2200 + lane * 4
lw    x16, 512(x6)      # 0x5A5A5A5A with that half replaced
lh    x17, 512(x14)     # 0xFFFF8000 + lane

add   x18, x5, x31
sb    x11, 768(x18)     # byte lane of GMEM + 0x2300: four lanes per seeded word
srli  x19, x31, 2
slli  x19, x19, 2
add   x19, x5, x19
lw    x19, 768(x19)     # the word holding this lane's byte and three others

addi  x20, x0, 4        # read-modify-write this lane's word four times
rmw:
lw    x21, 0(x6)
addi  x21, x21, 1       # load-use on a GMEM load, then its store
sw    x21, 0(x6)
addi  x20, x20, -1
bne   x20, x0, rmw
lw    x22, 0(x6)        # x7 + 4

sw    x8, 0(x3)
sw    x9, 128(x3)
sw    x12, 256(x3)
sw    x13, 384(x3)
sw    x16, 512(x3)
sw    x17, 640(x3)
sw    x19, 768(x3)
sw    x22, 896(x3)
jalr  x0, 0(x1)
