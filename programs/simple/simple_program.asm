addi x15,x31,0
addi x1,x15,0
lui x15,0x1
addi x14,x15,56 # 1038 <__DATA_BEGIN__>
slli x15,x1,0x2
add x15,x14,x15
sw x1,0(x15)
addi x8,x0,10
lui x15,0x1
addi x14,x15,184 # 10b8 <ten_array>
slli x15,x1,0x2
add x15,x14,x15
sw x8,0(x15)
jalr x0,0(x1)
