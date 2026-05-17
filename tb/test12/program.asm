# =========================================================================
# AMOADD.W STRESS TEST 
# =========================================================================

# INITIALIZATION
addi x1, x0, 0      # Base memory pointer = 0
addi x2, x0, 50     
sw   x2, 0(x1)      # Mem[0] = 50
sw   x2, 4(x1)      # Mem[4] = 50

# TEST 1: BASIC AMO & LOAD-USE HAZARD (Producer)
# amoadd.w acts like a load to the core; it takes 1 extra cycle to return the old value.
# The 'add' instruction needs x3 immediately, forcing the pipeline to stall for 1 cycle.
addi x4, x0, 10
amoadd.w x3, x4, (x1) # x3 = 50 (old val), Mem[0] becomes 50 + 10 = 60
add  x5, x3, x4       # Requires stall + MEM/WB forwarding. x5 = 50 + 10 = 60
sw   x5, 8(x1)        # Mem[8] = 60

# TEST 2: FORWARDING TO AMO ADDEND & BASE (Consumer)
# Tests if the pipeline correctly forwards EX/MEM ALU results straight into the AMO's rs1 and rs2.
addi x6, x1, 4        # Base address = 4
addi x7, x0, 25
add  x8, x7, x7       # EX-to-EX forwarding. x8 = 50
amoadd.w x9, x8, (x6) # Forwards x8 into rs2. x9 = 50 (old val), Mem[4] = 50 + 50 = 100

# TEST 3: THE ZERO-REGISTER DISCARD (rd = x0)
# Ensure the core doesn't crash or corrupt x0 if we don't care about the old memory value.
addi x10, x1, 16      # Base address = 16
sw   x0, 0(x10)       # Mem[16] = 0
nop
addi x11, x0, 7       # Addend = 7
amoadd.w x0, x11, (x10) # Mem[16] becomes 0 + 7 = 7, but x0 MUST remain 0!
add  x12, x0, x11     # x12 = 0 + 7 = 7
sw   x12, 20(x1)      # Mem[20] = 7

# TEST 4: CROSSBAR LOCK RELEASE VERIFICATION
# Verifies that after the crossbar hijacks the port for Cycle 2, it successfully 
# releases it so normal stores aren't silently dropped.
addi x13, x1, 24      # Base address = 24
sw   x0, 0(x13)       # Mem[24] = 0
nop
addi x14, x0, 10
amoadd.w x15, x14, (x13) # Mem[24] = 10. Port is locked!
addi x16, x0, 99
sw   x16, 0(x13)      # Overwrites the AMO. If lock gets stuck, this store vanishes.
lw   x17, 0(x13)      # Should read 99.
sw   x17, 28(x1)      # Mem[28] = 99.

# TEST 5: MASSIVE MULTI-CORE CONTENTION (THE ATOMICITY CHECK)
# Every core executes this simultaneously. They all attempt to increment Mem[12] by 1.
# - If atomicity FAILS: Mem[12] will be completely random or 1 (due to overwrites).
# - If atomicity WORKS: The crossbar queue will serialize them, and Mem[12] = NUM_CORES.
addi x18, x1, 12      # Base address = 12
sw   x0, 0(x18)       # Init Mem[12] = 0.
nop                   # Let the pipeline settle so the 'sw' commits before the AMO.
nop
nop
addi x19, x0, 1       # Addend = 1
amoadd.w x20, x19, (x18) # ATOMIC INCREMENT! 

# End program gracefully
jalr x0, x0, 0