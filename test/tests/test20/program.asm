# Compiled from programs/simple.c

addi x5,x31,0
slli x6,x5,0x6
lui x2,0x2
addi x2,x2,0 # 2000 <__stack_top>
sub x2,x2,x6
jal x1,1c <main>
jal x0,18 <_start+0x18>
addi x0,x0,0
addi x13,x31,0
lui x14,0x1
slli x12,x13,0x2
addi x14,x14,256 # 1100 <indexes_array>
lui x15,0x1
add x14,x14,x12
addi x15,x15,384 # 1180 <ten_array>
add x15,x15,x12
sw x13,0(x14)
addi x14,x0,10
sw x14,0(x15)
jalr x0,0(x1)
