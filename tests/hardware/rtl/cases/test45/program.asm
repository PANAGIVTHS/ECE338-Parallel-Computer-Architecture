# Immediate pipelined multiplier -> ECALL dependencies, nonzero then zero.
addi x3, x0, 7
mul  x17, x3, x3
ecall               # Product 49: no-op, must not consume old a7 = 0.
addi x20, x0, 29
sw   x20, 0(x0)
mul  x17, x3, x0
ecall               # Product zero: exit, must not consume old a7 = 49.
addi x29, x0, 999   # Younger register poison.
sw   x20, 4(x0)     # Younger store poison.