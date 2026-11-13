# DDR: one group per lane in FB1 (lane * 128 B). With more lanes than write
# slots the write ring fills and the group former waits for free slots.
lui  x5, 0x18400        # x5 = FB1
slli x6, x31, 7         # lane * 128
add  x5, x5, x6
addi x7, x0, 3
mul  x7, x7, x31
addi x7, x7, 7          # value = 3 * lane + 7
sw   x7, 0(x5)
addi x17, x0, 0  # Kernel complete: ECALL service 0
ecall