addi x5,x31,0
slli x6,x5,0x6
lui x2,0x2
addi x2,x2,0 # 2000 <__stack_top>
sub x2,x2,x6
jal x1,1c <kernel_main>
jal x0,18 <_start+0x18>
addi x15,x31,0
lui x14,0x0
lw x14,64(x14) # 40 <__gpu_args_base>
addi x15,x15,1
slli x15,x15,0x2
addi x12,x15,-4
add x13,x14,x15
add x12,x14,x12
lw x13,0(x13)
lw x12,0(x12)
addi x15,x15,128
add x15,x14,x15
sub x14,x13,x12
sw x14,0(x15)
jalr x0,0(x1)
