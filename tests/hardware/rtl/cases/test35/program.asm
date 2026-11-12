# Sub-word stores change only the addressed bytes of a DMEM word: over a
# background, followed by loads and fed by forwarding, and from lanes that share
# a word. DMEM holds the results; the benches check all of it.
slli  x3, x31, 2        # x3: lane * 4, this lane's word of each array
lui   x5, 0x1010
addi  x5, x5, 0x101     # 0x01010101
mul   x5, x5, x31
lui   x6, 0x44332
addi  x6, x6, 0x211
add   x6, x6, x5        # 0x44332211 + lane in every byte: shows what landed where
lui   x7, 0xAAAAB
addi  x7, x7, -0x556    # 0xAAAAAAAA: the background that must survive

sw    x7, 256(x3)
sb    x6, 256(x3)       # AAAAAAdd
sw    x7, 384(x3)
sb    x6, 385(x3)       # AAAAddAA
sw    x7, 512(x3)
sb    x6, 514(x3)       # AAddAAAA
sw    x7, 640(x3)
sb    x6, 643(x3)       # ddAAAAAA
sw    x7, 768(x3)
sh    x6, 768(x3)       # AAAAdddd
sw    x7, 896(x3)
sh    x6, 898(x3)       # ddddAAAA

sb    x6, 1024(x3)
lbu   x10, 1024(x3)     # a load right after the store
lw    x11, 1024(x3)     # the whole word: only the low byte was stored
addi  x12, x31, 0x80
sb    x12, 1025(x3)     # store data forwarded from EX/MEM
lh    x13, 1024(x3)     # the byte just stored is the half's sign
lw    x14, 256(x3)
sh    x14, 1026(x3)     # load to store data, after the load-use stall
lw    x15, 1024(x3)

sw    x10, 1536(x3)
sw    x11, 1664(x3)
sw    x13, 1792(x3)
sw    x15, 1920(x3)

addi  x16, x31, 0x40
sb    x16, 1152(x31)    # lanes share words, each its own byte
slli  x17, x31, 1
sh    x16, 1280(x17)    # lanes share words, each its own halfword
sb    x16, 1408(x0)     # every lane the same byte: the highest lane is last
andi  x18, x31, 3
sb    x16, 1412(x18)    # four bytes of one word, lanes sharing each byte
andi  x18, x31, 2
sh    x16, 1416(x18)    # two halves of one word, lanes sharing each half
sw    x7, 1424(x0)
sb    x0, 1425(x0)      # a byte of x0 clears only that byte: 0xAAAA00AA
jalr  x0, 0(x1)
