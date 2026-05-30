# BEQ taken: positive equal.
bge  x0, x1, beq_pos_taken
addi x28, x28, 1 
addi x28, x28, 1 
addi x28, x28, 1 
addi x28, x28, 1 
addi x28, x28, 1 
addi x28, x28, 1 
addi x28, x28, 1      # must be flushed
addi x28, x28, 1      # must be flushed
addi x28, x28, 1      # must be flushed
beq_pos_taken:
addi x20, x20, 1

jalr x0, 0(x1)
