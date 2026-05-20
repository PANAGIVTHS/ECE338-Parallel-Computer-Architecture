addi x15,x31,0
addi x1,x15,0
jal x0,74 <_start+0x74>
bne x1,x0,2c <_start+0x2c>
lui x15,0x1
addi x15,x15,128 # 1080 <data>
lw x14,0(x15)
lui x15,0x1
addi x15,x15,256 # 1100 <diff>
sw x14,0(x15)
jal x0,70 <_start+0x70>
lui x15,0x1
addi x14,x15,128 # 1080 <data>
slli x15,x1,0x2
add x15,x14,x15
lw x14,0(x15)
addi x15,x1,-1
lui x13,0x1
addi x13,x13,128 # 1080 <data>
slli x15,x15,0x2
add x15,x13,x15
lw x15,0(x15)
sub x14,x14,x15
lui x15,0x1
addi x13,x15,256 # 1100 <diff>
slli x15,x1,0x2
add x15,x13,x15
sw x14,0(x15)
addi x1,x1,32
addi x15,x0,31
bge x15,x1,c <_start+0xc>
jalr x0,0(x1)
