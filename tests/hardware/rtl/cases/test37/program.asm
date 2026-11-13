# DDR loads from GMEM: each lane reads its own word (one burst), a
# word at a 16-byte stride (four bursts) and the first word (every lane the
# same word), then uses the loaded values right away.
lui  x5, 0x18800        # GMEM_BASE
slli x6, x31, 2         # lane * 4
add  x7, x5, x6
lw   x8, 0(x7)          # GMEM[lane]
slli x9, x31, 4         # lane * 16
add  x10, x5, x9
lw   x11, 256(x10)      # GMEM[64 + 4 * lane]
add  x12, x8, x11       # load-use on a DDR load
lw   x13, 0(x5)         # GMEM[0] on every lane
sub  x14, x12, x13
addi  x17, x0, 0
ecall