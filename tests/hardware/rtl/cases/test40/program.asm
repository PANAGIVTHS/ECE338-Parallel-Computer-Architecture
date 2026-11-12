# DDR sub-word loads from the texture (ddr_seed.mem): every byte and halfword
# of each lane's own word (one burst per load), each lane its own byte and its
# own halfword of the same few words, a halfword per lane that straddles two
# groups (two bursts), and consumers of the loaded values. Each lane stores
# every result in its own slot, for the benches that only check memory.
lui   x3, 0x1
slli  x4, x31, 2
add   x3, x3, x4        # x3: 0x1000 + lane * 4, one array every 128 bytes

lui   x5, 0x18800       # TEX_BASE
add   x6, x5, x4        # TEX word `lane`: c0+i 7f-i 01+i 80|i (high to low)

lb    x8, 0(x6)         # 0xFFFFFF80 | i
lb    x9, 1(x6)         # 0x01 + i
lb    x10, 2(x6)        # 0x7F - i
lb    x11, 3(x6)        # 0xFFFFFFC0 + i
lbu   x12, 0(x6)        # 0x80 | i
lbu   x13, 1(x6)        # 0x01 + i
lbu   x14, 2(x6)        # 0x7F - i
lbu   x15, 3(x6)        # 0xC0 + i
lh    x16, 0(x6)        # positive half: zero upper bits
lh    x17, 2(x6)        # negative half: 0xFFFF....
lhu   x18, 0(x6)
lhu   x19, 2(x6)

add   x20, x5, x31
lb    x20, 0(x20)       # byte `lane` of TEX: words 0..7, four lanes per word
slli  x21, x31, 1
add   x21, x5, x21
lh    x21, 0(x21)       # halfword `lane` of TEX: words 0..15, two lanes per word
lhu   x22, 126(x6)      # lane 0: TEX word 31 (group 0), lanes 1..31: words 32..62 (group 1)

lb    x23, 3(x6)
add   x23, x23, x23     # load-use on a DDR byte load: 2 * (0xFFFFFFC0 + i)
lh    x24, 2(x6)
blt   x24, x0, negative # taken only if the halfword's sign was extended
addi  x23, x23, 1       # flushed
negative:

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
sw    x22, 1792(x3)
sw    x23, 1920(x3)
jalr  x0, 0(x1)
