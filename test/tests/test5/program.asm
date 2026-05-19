# INITIALIZATION
addi x1, x0, 0       # x1 = 0 (Base Memory Address)
addi x2, x0, 10      # x2 = 10
addi x3, x0, 20      # x3 = 20

# TEST 1: BRANCH NOT TAKEN & EX-TO-EX FORWARDING
add  x4, x2, x3      # x4 = 30
beq  x4, x2, fail1   # 30 != 10, Branch Not Taken.
nop                  # (Branch delay slot)
nop                  # (Branch delay slot)

# TEST 2: BRANCH TAKEN & NEGATIVE MATH
sub  x5, x4, x2      # x5 = 30 - 10 = 20
beq  x5, x3, skip1   # 20 == 20, Branch Taken!
nop                  # (Branch delay slot)
nop                  # (Branch delay slot)
addi x5, x0, 999     # This should be SKIPPED! (If x5 becomes 999, branch failed)
fail1:
nop
skip1:

# TEST 3: LOAD-USE HAZARD (STALL) & STORE FORWARDING
sw   x5, 0(x1)       # Mem[0] = 20
lw   x6, 0(x1)       # x6 = 20
add  x7, x6, x2      # STALL TRIGGERED! x7 = 20 + 10 = 30
sw   x7, 4(x1)       # Mem[4] = 30

# TEST 4: NEGATIVE OFFSETS & DEEP LOAD-USE PIPELINE
addi x8, x1, 16      # x8 = 16 (New Base)
sw   x7, 0(x8)       # Mem[16] = 30
lw   x9, -12(x8)     # Reads Mem[4]. x9 = 30
sub  x10, x9, x2     # STALL TRIGGERED! x10 = 30 - 10 = 20
sw   x10, -8(x8)     # Mem[8] = 20

# TEST 5: ALWAYS TAKEN BRANCH
addi x11, x0, 50     # x11 = 50
beq  x11, x11, skip2 # Always Taken!
nop
nop
addi x11, x0, 0      # This should be SKIPPED!
skip2:
sw   x11, 12(x1)     # Mem[12] = 50

# TEST 6: LOAD DIRECTLY TO STORE DATA PORT
lw   x12, 12(x1)     # x12 = 50
sw   x12, 20(x1)     # Mem[20] = 50

# TEST 7: MEMORY OVERWRITE & TRIPLE STAGE FORWARDING
addi x13, x0, 100    # x13 = 100
addi x14, x13, 200   # EX-to-EX -> x14 = 300
add  x15, x14, x13   # x14(EX-to-EX), x13(MEM-to-EX) -> x15 = 400
sw   x15, 24(x1)     # Mem[24] = 400
sw   x13, 24(x1)     # Overwrite Mem[24] with 100!
jalr x0, 0(x1)  # return