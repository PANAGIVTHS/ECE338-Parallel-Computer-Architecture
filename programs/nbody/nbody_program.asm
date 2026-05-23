addi x2,x2,-144
lui x15,0x1
addi x15,x15,-1696 # 960 <_start+0x960>
addi x12,x0,1600
addi x13,x0,800
addi x14,x0,1
sw x18,132(x2)
sw x19,128(x2)
sw x20,124(x2)
sw x23,112(x2)
addi x17,x0,-10
addi x16,x0,10
addi x10,x0,6
addi x11,x0,-6
addi x18,x0,3
addi x20,x2,72
addi x19,x2,84
addi x7,x2,12
addi x5,x2,24
lui x23,0x1
sw x8,140(x2)
sw x9,136(x2)
sw x21,120(x2)
sw x22,116(x2)
sw x24,108(x2)
sw x0,36(x2)
sw x0,48(x2)
sw x0,72(x2)
sw x0,76(x2)
sw x0,80(x2)
sw x0,84(x2)
sw x0,88(x2)
sw x0,92(x2)
sw x15,16(x2)
sw x15,28(x2)
sw x12,12(x2)
sw x12,24(x2)
sw x13,20(x2)
sw x13,32(x2)
sw x17,40(x2)
sw x16,44(x2)
sw x10,52(x2)
sw x11,56(x2)
sw x18,60(x2)
sw x14,64(x2)
sw x14,68(x2)
addi x29,x20,0
addi x28,x19,0
addi x9,x7,0
addi x8,x5,0
addi x23,x23,-1537 # 9ff <_start+0x9ff>
addi x30,x0,0
addi x22,x0,511
addi x21,x0,1535
addi x16,x2,60
addi x10,x5,0
addi x11,x7,0
addi x13,x0,0
beq x13,x30,138 <_start+0x138>
lw x15,0(x11)
lw x17,0(x9)
lw x14,0(x10)
lw x12,0(x8)
sub x15,x15,x17
sub x14,x14,x12
blt x0,x15,254 <_start+0x254>
bne x15,x0,2d0 <_start+0x2d0>
blt x0,x14,2d8 <_start+0x2d8>
bne x14,x0,2f0 <_start+0x2f0>
lw x12,0(x16)
lw x6,0(x29)
lw x17,0(x28)
mul x15,x12,x15
mul x12,x12,x14
add x15,x6,x15
sw x15,0(x29)
add x15,x17,x12
sw x15,0(x28)
addi x13,x13,1
addi x16,x16,4
addi x11,x11,4
addi x10,x10,4
bne x13,x18,e8 <_start+0xe8>
addi x30,x30,1
addi x29,x29,4
addi x28,x28,4
addi x9,x9,4
addi x8,x8,4
bne x30,x13,d8 <_start+0xd8>
addi x12,x2,48
addi x6,x12,0
addi x13,x2,36
lw x14,0(x13)
lw x10,0(x20)
lw x15,0(x12)
lw x11,0(x19)
add x14,x14,x10
lw x10,0(x7)
add x15,x15,x11
lw x11,0(x5)
srai x17,x14,0x5
srai x16,x15,0x5
sub x14,x14,x17
sub x15,x15,x16
add x10,x10,x14
add x11,x11,x15
sw x14,0(x13)
sw x10,0(x7)
sw x15,0(x12)
sw x11,0(x5)
addi x13,x13,4
addi x20,x20,4
addi x7,x7,4
addi x19,x19,4
addi x12,x12,4
addi x5,x5,4
bne x6,x13,170 <_start+0x170>
lw x14,12(x2)
lui x13,0x1
addi x15,x13,0 # 1000 <_start+0x1000>
srai x14,x14,0x4
sw x14,0(x13)
lw x13,24(x2)
lw x8,140(x2)
lw x9,136(x2)
srai x13,x13,0x4
sw x13,4(x15)
lw x13,16(x2)
lw x18,132(x2)
lw x19,128(x2)
srai x13,x13,0x4
sw x13,8(x15)
lw x13,28(x2)
lw x20,124(x2)
lw x21,120(x2)
srai x13,x13,0x4
sw x13,12(x15)
lw x13,20(x2)
lw x22,116(x2)
lw x23,112(x2)
srai x13,x13,0x4
sw x13,16(x15)
lw x14,32(x2)
lw x24,108(x2)
addi x10,x0,0
srai x14,x14,0x4
sw x14,20(x15)
addi x2,x2,144
jalr x0,0(x1)
addi x24,x0,1
srai x17,x15,0x1f
xor x12,x17,x15
sub x12,x12,x17
blt x0,x14,28c <_start+0x28c>
bne x14,x0,2e0 <_start+0x2e0>
bge x22,x12,2f8 <_start+0x2f8>
addi x15,x24,0
bge x21,x12,114 <_start+0x114>
slli x15,x24,0x1
bge x23,x12,114 <_start+0x114>
slli x15,x24,0x1
add x15,x15,x24
jal x0,114 <_start+0x114>
addi x6,x0,1
bge x22,x12,2e8 <_start+0x2e8>
addi x15,x24,0
bge x21,x12,2a8 <_start+0x2a8>
slli x15,x24,0x1
bge x23,x12,2a8 <_start+0x2a8>
add x15,x15,x24
srai x17,x14,0x1f
xor x12,x17,x14
sub x12,x12,x17
bge x22,x12,300 <_start+0x300>
addi x14,x6,0
bge x21,x12,114 <_start+0x114>
slli x14,x6,0x1
bge x23,x12,114 <_start+0x114>
add x14,x14,x6
jal x0,114 <_start+0x114>
addi x24,x0,-1
jal x0,258 <_start+0x258>
addi x6,x0,1
jal x0,2a8 <_start+0x2a8>
addi x6,x0,-1
blt x22,x12,294 <_start+0x294>
addi x15,x0,0
jal x0,2a8 <_start+0x2a8>
addi x6,x0,-1
jal x0,2a8 <_start+0x2a8>
addi x15,x0,0
jal x0,114 <_start+0x114>
addi x14,x0,0
jal x0,114 <_start+0x114>
