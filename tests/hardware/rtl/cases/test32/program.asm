# DMEM then DDR: each lane writes its square to DMEM, reads its neighbour's
# square back, and writes it to a framebuffer row.
slli x6, x31, 2         # lane * 4
mul  x7, x31, x31
sw   x7, 0(x6)          # DMEM[lane] = lane^2
addi x8, x31, 1
andi x8, x8, 31         # neighbour (lane + 1) mod 32
slli x8, x8, 2
lw   x9, 0(x8)          # neighbour's square (0 if that lane does not exist)
lui  x5, 0x18003
add  x5, x5, x6
sw   x9, 0(x5)
addi x17, x0, 0  # Kernel complete: ECALL service 0
ecall