# Nested JAL/RET, ordinary a7 arithmetic and an unsupported ECALL.
# Subroutines deliberately follow the exit and must remain in the image.
addi x20, x0, 0
addi x17, x0, 41
addi x18, x17, 1     # a7 is an ordinary allocatable register: x18 = 42
jal  x1, outer
addi x20, x20, 4     # Both ordinary returns must reach this continuation.
addi x17, x0, 7
ecall               # Unsupported service: continue, do not exit.
addi x20, x20, 8
addi x20, x20, 16
sw   x20, 0(x0)     # Expected 31 = 1 + 2 + 4 + 8 + 16.
sw   x18, 4(x0)     # Expected 42.
addi x17, x0, 0
ecall
addi x29, x0, 999   # Younger register poison: must not retire.
sw   x18, 8(x0)     # Younger store poison: must not reach DMEM.
outer:
addi x5, x1, 0      # Save outer return address across the nested call.
addi x20, x20, 1
jal  x1, inner
addi x1, x5, 0
jalr x0, 0(x1)      # Normal RET, immediately dependent on restored x1.
inner:
addi x20, x20, 2
jalr x0, 0(x1)      # Normal RET, not a completion marker.
