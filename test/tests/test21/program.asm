# Compiled from programs/args_and_output.c

addi x5,x31,0
slli x6,x5,0x6
lui x2,0x2
addi x2,x2,0 # 2000 <__stack_top>
sub x2,x2,x6
jal x1,1c <kernel_main>
jal x0,18 <_start+0x18>
addi x0,x0,0
addi x12,x31,0
lui x14,0x0
addi x14,x14,64 # 40 <__gpu_args_base>
lw x11,0(x14)
lw x15,4(x14)
lw x10,8(x14)
lw x16,12(x14)
lui x13,0x1
slli x14,x12,0x3
addi x13,x13,0 # 1000 <__gpu_output_base>
add x15,x15,x10
add x11,x12,x11
add x10,x14,x13
add x15,x15,x16
addi x14,x14,4
sw x11,0(x10)
add x14,x14,x13
add x15,x15,x12
sw x15,0(x14)
jalr x0,0(x1)
