# DDR: byte and halfword stores over a seeded framebuffer (ddr_seed.mem). WSTRB
# selects single bytes, so the seed around them must survive, and lanes that
# share a word must merge. Every store is one burst for up to 32 lanes.
lui   x5, 0x18002       # x5: FB0 + 0x2000
lui   x6, 0x55555
add   x6, x6, x31
addi  x6, x6, 0x40      # 0x55555040 + lane: the upper bytes must not land

add   x7, x5, x31
sb    x6, 0(x7)         # FB0 + 0x2000: lanes share words, each its own byte

slli  x8, x31, 2
add   x8, x5, x8        # x8: FB0 + 0x2000 + lane * 4
sb    x6, 129(x8)       # FB0 + 0x2080: byte 1 of this lane's word, over the seed
sh    x6, 258(x8)       # FB0 + 0x2100: the upper half of its word, over the seed

slli  x9, x31, 1
add   x9, x5, x9
sh    x6, 384(x9)       # FB0 + 0x2180: lanes share words, each its own half

addi  x10, x0, 0x5A
sb    x10, 515(x5)      # FB0 + 0x2200: every lane the same byte and value, over the seed
addi  x17, x0, 0
ecall
