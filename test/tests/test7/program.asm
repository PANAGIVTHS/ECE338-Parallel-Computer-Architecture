# INITIALIZATION
addi x1, x0, 0       # x1 = 0 (Base Memory Address)
addi x2, x0, 2       # x2 = 2
addi x3, x0, 3       # x3 = 3
addi x4, x0, 4       # x4 = 4
addi x5, x0, 5       # x5 = 5

# TEST 1: MUL FOLLOWED BY NON-MUL (NO DEPENDENCY)
mul  x6, x2, x3      # x6 = 2 * 3 = 6
add  x7, x4, x5      # x7 = 4 + 5 = 9 (Executes concurrently/right after, no hazard)

# TEST 2: MUL FOLLOWED BY NON-MUL (WITH DEPENDENCY)
mul  x8, x2, x4      # x8 = 2 * 4 = 8
add  x9, x8, x5      # x9 = 8 + 5 = 13 (EX-to-EX forwarding from MUL to ADD)

# TEST 3: MUL FOLLOWED BY MUL (NO DEPENDENCY)
mul  x10, x3, x4     # x10 = 3 * 4 = 12
mul  x11, x2, x5     # x11 = 2 * 5 = 10 (Pipeline should stream these without stall)

# TEST 4: MUL FOLLOWED BY MUL (WITH DEPENDENCY)
mul  x12, x2, x3     # x12 = 2 * 3 = 6
mul  x13, x12, x4    # x13 = 6 * 4 = 24 (EX-to-EX forwarding between two MUL units)

# TEST 5: LOAD -> MUL DEPENDENCY -> ADD DEPENDENCY
addi x14, x0, 7      # x14 = 7
sw   x14, 0(x1)      # Mem[0] = 7
lw   x15, 0(x1)      # x15 = 7
mul  x16, x15, x2    # STALL TRIGGERED! x16 = 7 * 2 = 14 (Load-Use hazard into MUL)
add  x17, x16, x3    # x17 = 14 + 3 = 17 (EX-to-EX forwarding from MUL to ADD)

# MEMORY DUMP: STORE ALL RESULTS TO VERIFY IN DATA.MEM
sw   x6,  4(x1)      # Mem[4]  = 6
sw   x7,  8(x1)      # Mem[8]  = 9
sw   x8,  12(x1)     # Mem[12] = 8
sw   x9,  16(x1)     # Mem[16] = 13
sw   x10, 20(x1)     # Mem[20] = 12
sw   x11, 24(x1)     # Mem[24] = 10
sw   x12, 28(x1)     # Mem[28] = 6
sw   x13, 32(x1)     # Mem[32] = 24
sw   x16, 36(x1)     # Mem[36] = 14
sw   x17, 40(x1)     # Mem[40] = 17
jalr x0, 0(x1)  # return