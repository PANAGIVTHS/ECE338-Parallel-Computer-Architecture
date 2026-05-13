# --- MULTI-CORE BOOTLOADER ---
# x31 holds the hardcoded Core ID
beq x31, x0, core0_setup

core1_setup:
# Core 1 Stack Pointer (x2) -> 4096 (0x1000)
addi x2, x0, 1
slli x2, x2, 12
beq x0, x0, main_start

core0_setup:
# Core 0 Stack Pointer (x2) -> 8192 (0x2000)
addi x2, x0, 2
slli x2, x2, 12

main_start:
# --- END BOOTLOADER ---

# --- INJECT TEST DATA (Hardware Safe) ---

# Synthesized: lui x15, 1 (Loads 4096 into x15)
addi x15, x0, 1
slli x15, x15, 12

# Point x15 to data[0] (4096 + 168 = 4264 or 0x10A8)
addi x15, x15, 168 

# Load 50 into data[0]
addi x14, x0, 50   
sw x14, 0(x15)

# Load 10 into data[1] (Offset of 4 bytes)
addi x14, x0, 10
sw x14, 4(x15)

# ----------------------------------------

addi x2,  x2,  -32
sw   x8,  28(x2)
addi x8,  x2,  32
addi x15, x31, 0
sw   x15, -20(x8)

lw   x14, -20(x8)
addi x15, x0,  9

# Synthesized: blt x15, x14, 94
slt  x13, x15, x14
beq  x13, x0, skip_blt
beq  x0,  x0,  end_block

skip_blt:
lw   x15, -20(x8)

# Synthesized: bne x15, x0, 44
beq  x15, x0,  i_is_zero
beq  x0,  x0,  i_not_zero

i_is_zero:
# Synthesized: lui x15, 0x1
addi x15, x0,  1
slli x15, x15, 12

addi x15, x15, 168
lw   x14, 0(x15)

# Synthesized: lui x15, 0x1
addi x15, x0,  1
slli x15, x15, 12

addi x15, x15, 208
sw   x14, 0(x15)

# Synthesized: jal x0, 94
beq  x0,  x0,  tail_block

i_not_zero:
# Synthesized: lui x15, 0x1
addi x15, x0,  1
slli x15, x15, 12

addi x14, x15, 168
lw   x15, -20(x8)
slli x15, x15, 2
add  x15, x14, x15
lw   x14, 0(x15)

lw   x15, -20(x8)
addi x15, x15, -1

# Synthesized: lui x13, 0x1
addi x13, x0,  1
slli x13, x13, 12

addi x13, x13, 168
slli x15, x15, 2
add  x15, x13, x15
lw   x15, 0(x15)

sub  x14, x14, x15

# Synthesized: lui x15, 0x1
addi x15, x0,  1
slli x15, x15, 12

addi x13, x15, 208
lw   x15, -20(x8)
slli x15, x15, 2
add  x15, x13, x15
sw   x14, 0(x15)

tail_block:
end_block:
addi x15, x0,  0
addi x10, x15, 0
lw   x8,  28(x2)
addi x2,  x2,  32