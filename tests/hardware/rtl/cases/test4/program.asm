addi x1, x1, 7
addi x2, x2, 7
mul x3, x1, x2
addi x17, x0, 0  # Kernel complete: ECALL service 0
ecall
