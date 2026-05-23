# Extensive JALR control-flow test
# Covers:
# - jalr rd, imm(rs1) as an indirect jump with PC+4 link
# - clearing bit 0 of odd targets
# - negative immediates for backward indirect jumps
# - jalr x0 without clobbering registers
# - forwarding a freshly computed JALR base register
# - jalr x0, 0(x1) only as the final kernel-completion marker

jal  x0, main
nop
nop
nop
nop
return_subroutine:
addi x13, x13, 1024
jalr x31, 0(x1)     # return without using the reserved completion encoding

main:
addi x20, x0, 0      # success signature
addi x28, x0, 0      # wrong-path/failure counter
addi x5,  x0, 0
addi x8,  x0, 0
addi x9,  x0, 0
addi x10, x0, 0
addi x11, x0, 0

# Exercise an indirect return without using jalr x0, 0(x1), which is reserved
# by this project as the kernel-completion marker.
jal  x1, return_subroutine
after_return:
addi x20, x20, 1

# Direct indirect jump: x6 is the byte address of anchor_direct.
jal  x6, anchor_direct
anchor_direct:
jalr x5, 20(x6)      # target_direct, link should be PC + 4
addi x28, x28, 1     # must be flushed
addi x28, x28, 1     # must be flushed
addi x28, x28, 1     # must be flushed
addi x28, x28, 1     # must be flushed
target_direct:
addi x20, x20, 2

# Odd target address: JALR must clear bit 0 before jumping.
jal  x6, anchor_odd
anchor_odd:
addi x7, x6, 21      # odd address for target_odd; JALR should clear to +20
jalr x8, 0(x7)
addi x28, x28, 2     # must be flushed
addi x28, x28, 2     # must be flushed
addi x28, x28, 2     # must be flushed
target_odd:
addi x20, x20, 4

# Negative immediate: jump backward to guarded code skipped on the first pass.
addi x12, x0, 0
back_target:
beq  x12, x0, after_back_target
addi x20, x20, 8
jal  x0, after_back_jalr
after_back_target:
addi x12, x0, 1
jal  x6, anchor_back
anchor_back:
jalr x9, -20(x6)     # target is back_target
addi x28, x28, 4     # must be flushed
after_back_jalr:

# rd=x0 should jump but must not write any link register.
jal  x6, anchor_x0
anchor_x0:
addi x10, x0, 77
jalr x0, 16(x6)      # target_x0
addi x28, x28, 8     # must be flushed
addi x28, x28, 8     # must be flushed
target_x0:
addi x20, x20, 16

# Forwarding: compute the JALR base shortly before JALR consumes it.
jal  x6, anchor_forward
anchor_forward:
addi x7, x6, 20      # target_forward address produced just before JALR
nop
jalr x11, 0(x7)
addi x28, x28, 16    # must be flushed
addi x28, x28, 16    # must be flushed
target_forward:
addi x20, x20, 32

# Expected signature is written after all control-flow checks so prior wrong-path
# execution is caught by x28/link-register checks, not by accumulated arithmetic.
addi x20, x0, 1087
addi x13, x0, 0
sw   x20, 0(x0)
sw   x28, 4(x0)      # expected 0
sw   x5,  8(x0)      # link from direct JALR
sw   x8,  12(x0)     # link from odd-target JALR
sw   x9,  16(x0)     # link from backward JALR
sw   x10, 20(x0)     # expected 77; proves jalr x0 did not clobber x10
sw   x11, 24(x0)     # link from forwarded-base JALR

# Let all stores drain before halting.
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop
nop

jalr x0, 0(x1)
