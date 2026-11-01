# Immediate load -> ECALL dependencies for both selector decisions.
addi x3, x0, 7
sw   x3, 0(x0)
sw   x0, 4(x0)
lw   x17, 0(x0)
ecall               # Loaded nonzero 7: no-op, despite old a7 = 0.
addi x20, x0, 28
sw   x20, 8(x0)
lw   x17, 4(x0)
ecall               # Loaded zero: exit, despite old a7 = 7.
addi x29, x0, 999   # Younger register poison.
sw   x20, 12(x0)    # Younger store poison.
