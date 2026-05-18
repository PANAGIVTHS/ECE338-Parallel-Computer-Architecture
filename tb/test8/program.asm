# BASE VALUES & x0 TRAP
addi x1, x0, 10
addi x2, x0, 20
add  x0, x1, x2    # Tries to write 30 to x0 (Hardware MUST ignore/discard)
add  x3, x0, x1    # x3 = 10 (If your forwarding unit fails the x0 check, it will be 40)

# MULTIPLIER HAZARD
mul  x4, x2, x1    # x4 = 200
addi x5, x0, 5     # Independent, no stall
add  x6, x4, x5    # Stalls for mul3_valid. x6 = 205

# THE LOAD-STORE FIX VALIDATION
sw   x6, 0(x0)     # Mem[0] = 205
lw   x7, 0(x0)     # x7 = 205
sw   x7, 4(x0)     # MUST STALL! Mem[4] = 205

# PIPELINED MULTIPLIER DSP TRAP
mul  x8, x5, x5    # x8 = 25
mul  x9, x5, x2    # x9 = 100 (Independent, MUST pipeline right behind x8)
add  x10, x8, x9   # Stalls for x9. x10 = 125
sw   x10, 8(x0)    # Mem[8] = 125

# BRANCH FORWARDING & FLUSHING
addi x11, x0, 100
sub  x12, x9, x11  # x12 = 100 - 100 = 0
beq  x12, x0, branch_pass_1  # Forwards 0 from EX. BRANCH TAKEN!

# POISON INSTRUCTIONS (Should be flushed)
addi x13, x0, 999  
addi x13, x0, 999  

branch_pass_1:
addi x13, x0, 13   # TARGET. x13 = 13

# BACK-TO-BACK BRANCH HAZARD
addi x14, x0, 1
sub  x15, x14, x14 # x15 = 0
beq  x15, x0, branch_pass_2   # BRANCH TAKEN!

# POISON INSTRUCTION (Should be flushed)
addi x15, x0, 999  

branch_pass_2:
addi x16, x0, 16   # TARGET. x16 = 16

# DEEP MEMORY CASCADE
lw   x17, 8(x0)    # x17 = 125
add  x18, x17, x13 # 1 cycle load-use stall. x18 = 125 + 13 = 138
sw   x18, 12(x0)   # Mem[12] = 138
sw   x18, 16(x0)   # Mem[16] = 138
lw   x19, 12(x0)   # x19 = 138
sub  x20, x19, x18 # 1 cycle load-use stall. x20 = 138 - 138 = 0
sw   x20, 20(x0)   # Mem[20] = 0
jalr x0, 0(x1)