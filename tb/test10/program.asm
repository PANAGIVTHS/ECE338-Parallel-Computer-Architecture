# ==========================================
# LOCKSTEP-SAFE 2-CORE BOOTLOADER
# ==========================================
# Calculate Base Multiplier: (2 - x31)
addi x15, x0, 2
sub x15, x15, x31

# Shift left by 12 to multiply by 4096
# Core 0 Stack Pointer (x2) = 8192
# Core 1 Stack Pointer (x2) = 4096
add x2, x0, x15
slli x2, x2, 12
# ==========================================

addi    x2, x2, -48
sw      x8, 44(x2)
addi    x8, x2, 48
addi    x15, x31, 0
sw      x15, -20(x8)
sw      x0, -32(x8)
sw      x0, -28(x8)
lw      x15, -20(x8)
add     x15, x15, x15
addi    x14, x8, -16
add     x15, x14, x15
lw      x14, -20(x8)
sw      x14, -16(x15)
addi    x15, x0, 10
sw      x15, -24(x8)
sw      x0, -40(x8)
sw      x0, -36(x8)
lw      x15, -20(x8)
add     x15, x15, x15
addi    x14, x8, -16
add     x15, x14, x15
lw      x14, -24(x8)
sw      x14, -24(x15)
addi    x0, x0, 0
addi    x10, x15, 0
lw      x8, 44(x2)
addi    x2, x2, 48
jalr    x0, 0(x1)
