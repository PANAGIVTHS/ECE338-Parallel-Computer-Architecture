addi x15,x31,0
addi x1,x15,0
addi x9,x1,0
jal x0,1ec <_start+0x1ec>
srai x15,x9,0x1f
srli x15,x15,0x1c
add x14,x9,x15
andi x14,x14,15
sub x15,x14,x15
addi x1,x15,0
srai x15,x9,0x1f
andi x15,x15,15
add x15,x15,x9
srai x15,x15,0x4
addi x8,x15,0
beq x1,x0,54 <_start+0x54>
addi x15,x0,15
beq x1,x15,54 <_start+0x54>
beq x8,x0,54 <_start+0x54>
addi x15,x0,15
bne x8,x15,6c <_start+0x6c>
lui x15,0x1
addi x14,x15,1528 # 15f8 <output>
slli x15,x9,0x2
add x15,x14,x15
sw x0,0(x15)
jal x0,1e8 <_start+0x1e8>
addi x15,x8,-1
slli x14,x15,0x4
addi x15,x1,-1
add x15,x14,x15
lui x14,0x1
addi x14,x14,504 # 11f8 <image>
slli x15,x15,0x2
add x15,x14,x15
lw x19,0(x15)
addi x15,x8,-1
slli x15,x15,0x4
add x15,x1,x15
lui x14,0x1
addi x14,x14,504 # 11f8 <image>
slli x15,x15,0x2
add x15,x14,x15
lw x21,0(x15)
addi x15,x8,-1
slli x14,x15,0x4
addi x15,x1,1
add x15,x14,x15
lui x14,0x1
addi x14,x14,504 # 11f8 <image>
slli x15,x15,0x2
add x15,x14,x15
lw x18,0(x15)
slli x14,x8,0x4
addi x15,x1,-1
add x15,x14,x15
lui x14,0x1
addi x14,x14,504 # 11f8 <image>
slli x15,x15,0x2
add x15,x14,x15
lw x23,0(x15)
slli x14,x8,0x4
addi x15,x1,1
add x15,x14,x15
lui x14,0x1
addi x14,x14,504 # 11f8 <image>
slli x15,x15,0x2
add x15,x14,x15
lw x24,0(x15)
addi x15,x8,1
slli x14,x15,0x4
addi x15,x1,-1
add x15,x14,x15
lui x14,0x1
addi x14,x14,504 # 11f8 <image>
slli x15,x15,0x2
add x15,x14,x15
lw x20,0(x15)
addi x15,x8,1
slli x15,x15,0x4
add x15,x1,x15
lui x14,0x1
addi x14,x14,504 # 11f8 <image>
slli x15,x15,0x2
add x15,x14,x15
lw x22,0(x15)
addi x15,x8,1
slli x14,x15,0x4
addi x15,x1,1
add x15,x14,x15
lui x14,0x1
addi x14,x14,504 # 11f8 <image>
slli x15,x15,0x2
add x15,x14,x15
lw x1,0(x15)
slli x15,x24,0x1
add x15,x18,x15
add x14,x1,x15
slli x15,x23,0x1
add x15,x19,x15
add x15,x20,x15
sub x8,x14,x15
slli x15,x22,0x1
add x15,x20,x15
add x14,x1,x15
slli x15,x21,0x1
add x15,x19,x15
add x15,x18,x15
sub x1,x14,x15
bge x8,x0,1bc <_start+0x1bc>
sub x8,x0,x8
bge x1,x0,1c4 <_start+0x1c4>
sub x1,x0,x1
add x1,x8,x1
addi x15,x0,255
bge x15,x1,1d4 <_start+0x1d4>
addi x1,x0,255
lui x15,0x1
addi x14,x15,1528 # 15f8 <output>
slli x15,x9,0x2
add x15,x14,x15
sw x1,0(x15)
addi x9,x9,32
addi x15,x0,255
bge x15,x9,10 <_start+0x10>
jalr x0,0(x1)
