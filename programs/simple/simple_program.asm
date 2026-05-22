slli x5,x31,0x8
lui x2,0x2
add x2,x2,x5
jal x1,14 <main>
jal x0,10 <_start+0x10>
addi x14,x31,0
slli x13,x14,0x2
addi x15,x0,56
add x15,x15,x13
sw x14,0(x15)
addi x14,x0,10
sw x14,128(x15)
addi x10,x0,0
jalr x0,0(x1)
