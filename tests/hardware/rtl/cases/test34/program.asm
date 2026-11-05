# Back-to-back ALU -> ECALL selector dependencies, nonzero then zero.
addi x3, x0, 7
add  x17, x3, x3
ecall               # Fresh nonzero 14 must override stale initial zero.
addi x20, x0, 27
sw   x20, 0(x0)     # Continuation proves unsupported ECALL was a no-op.
sub  x17, x3, x3
ecall               # Fresh zero must override stale nonzero 14 and exit.
addi x29, x0, 999   # Younger register poison.
sw   x20, 4(x0)     # Younger store poison.
