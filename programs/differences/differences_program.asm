addi x5,x31,0
slli x6,x5,0x6
lui x2,0x2
addi x2,x2,0 # 2000 <__stack_top>
sub x2,x2,x6
jal x1,1c <kernel_main>
jal x0,18 <_start+0x18>
addi x12,x31,0
lui x15,0x1
addi x13,x12,1
addi x15,x15,256 # 1100 <data>
slli x13,x13,0x2
slli x14,x12,0x2
add x13,x15,x13
sw x12,0(x13)
add x15,x15,x14
lw x13,0(x15)
lui x15,0x1
addi x15,x15,388 # 1184 <diff>
sub x13,x13,x12
lui x12,0x1
addi x12,x12,0 # 1000 <__gpu_output_base>
add x15,x15,x14
add x14,x14,x12
sw x13,0(x15)
sw x13,0(x14)
jalr x0,0(x1)
