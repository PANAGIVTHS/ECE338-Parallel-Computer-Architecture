# First instruction at JAL target is a relative branch.
# If IF/ID PC is not retagged to target during flush,
# this branch target is computed one instruction too early.

addi x20, x0, 0
addi x28, x0, 0

jal  x0, target_branch
addi x28, x28, 1

target_branch:
beq  x0, x0, real_target
addi x28, x28, 2

real_target:
addi x20, x20, 5
sw   x20, 0(x0)
sw   x28, 4(x0)

jalr x0, 0(x1)