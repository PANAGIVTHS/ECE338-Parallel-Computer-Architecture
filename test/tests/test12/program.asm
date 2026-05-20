addi x1, x31, 0 # t0: 0, t1: 1
slli x1, x1, 2  # t0: 0, t1: 4
addi x2, x1, 1  # x2 = $t0 + 1
sw   x2, 0(x1)  # mem[0] = 1, mem[1] = 2
lw   x3, 0(x1)
addi x3, x2, 1
mul  x3, x3, x3
jalr x0, 0(x1)  # return