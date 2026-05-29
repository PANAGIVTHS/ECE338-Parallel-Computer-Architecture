# Compiled from programs/stacktest.c

addi x5,x31,0
slli x6,x5,0x6
lui x2,0x2
addi x2,x2,0 # 2000 <__stack_top>
sub x2,x2,x6
jal x1,1c <kernel_main>
jal x0,18 <_start+0x18>
addi x0,x0,0
addi x2,x2,-16
addi x15,x31,0
sw x0,12(x2)
addi x15,x2,0
sw x15,12(x2)
addi x2,x2,16
jalr x0,0(x1)
