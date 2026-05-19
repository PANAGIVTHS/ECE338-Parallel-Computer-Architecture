# INITIALIZATION
addi x1, x0, 0      # Base address = 0
addi x2, x0, 100
sw   x2, 0(x1)      # Mem[0] = 100
addi x3, x0, 200
sw   x3, 4(x1)      # Mem[4] = 200

# TEST 1: LOAD-USE HAZARD (Stall Required)
# The ALU needs x4 immediately, but lw doesn't get it until the MEM stage.
# Processor MUST stall for 1 cycle, then forward from MEM/WB to EX.
lw   x4, 0(x1)      # x4 = 100
add  x5, x4, x3     # x5 = 100 + 200 = 300
sw   x5, 8(x1)      # Mem[8] = 300

# TEST 2: LOAD DIRECTLY TO STORE
# Tests forwarding a loaded value straight into the data port of a store.
lw   x6, 4(x1)      # x6 = 200
sw   x6, 12(x1)     # Mem[12] = 200

# TEST 3: SIMULTANEOUS EX-to-EX & MEM-to-EX FORWARDING
addi x7, x0, 10     # x7 = 10
addi x8, x7, 20     # EX-to-EX forwarding (x8 = 30)
add  x9, x8, x7     # x8 uses EX-to-EX, x7 uses MEM-to-EX. x9 = 40.
sw   x9, 16(x1)     # Mem[16] = 40

# TEST 4: DEEP PIPELINE FORWARDING & SUBTRACTION
sub  x10, x5, x4    # x10 = 300 - 100 = 200
add  x11, x10, x10  # x11 = 400
nop                 # Creates a gap to test if forwarding safely ignores inactive stages
sub  x12, x11, x10  # x11 from MEM-to-EX, x10 from RegFile. x12 = 200.
sw   x12, 20(x1)    # Mem[20] = 200

# TEST 5: NEGATIVE OFFSETS & BASE REGISTER OVERLAPS
addi x13, x0, 24    # Set a new base to byte 24
sw   x11, 0(x13)    # Mem[24] = 400
lw   x14, -4(x13)   # Reads Mem[20] using a negative offset. x14 = 200
add  x15, x14, x14  # x15 = 400
sw   x15, 4(x13)    # Mem[28] = 400

# TEST 6: MEMORY OVERWRITE
addi x16, x0, 999   # x16 = 999
sw   x16, 28(x1)    # Overwrites Mem[28]. Changes it from 400 to 999.
jalr x0, 0(x1)  # return