addi x1, x31, 0 # t0: 0, t1: 1
slli x1, x1, 2  # t0: 0, t1: 4
sw   x31, 0(x1)
addi x17, x0, 0  # Kernel complete: ECALL service 0
ecall
