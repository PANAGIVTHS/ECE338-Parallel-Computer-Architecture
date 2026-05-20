addi x2,x2,-320
addi x15,x0,100
sw x15,56(x2)
addi x15,x0,150
sw x15,60(x2)
addi x15,x0,50
sw x15,64(x2)
addi x15,x0,100
sw x15,44(x2)
addi x15,x0,150
sw x15,48(x2)
addi x15,x0,50
sw x15,52(x2)
sw x0,32(x2)
sw x0,36(x2)
addi x15,x0,-5
sw x15,40(x2)
sw x0,20(x2)
addi x15,x0,5
sw x15,24(x2)
sw x0,28(x2)
addi x15,x0,10
sw x15,8(x2)
addi x15,x0,10
sw x15,12(x2)
addi x15,x0,10
sw x15,16(x2)
sw x0,308(x2)
jal x0,a78 <_start+0xa78>
sw x0,316(x2)
jal x0,9c0 <_start+0x9c0>
sw x0,304(x2)
sw x0,300(x2)
sw x0,312(x2)
jal x0,6f0 <_start+0x6f0>
lw x14,316(x2)
lw x15,312(x2)
beq x14,x15,6c8 <_start+0x6c8>
lw x15,312(x2)
slli x15,x15,0x2
addi x14,x2,320
add x15,x14,x15
lw x14,-264(x15)
lw x15,316(x2)
slli x15,x15,0x2
addi x13,x2,320
add x15,x13,x15
lw x15,-264(x15)
sub x15,x14,x15
sw x15,292(x2)
lw x15,312(x2)
slli x15,x15,0x2
addi x14,x2,320
add x15,x14,x15
lw x14,-276(x15)
lw x15,316(x2)
slli x15,x15,0x2
addi x13,x2,320
add x15,x13,x15
lw x15,-276(x15)
sub x15,x14,x15
sw x15,288(x2)
lw x14,292(x2)
addi x15,x0,1000
blt x15,x14,6d0 <_start+0x6d0>
lw x14,292(x2)
addi x15,x0,-1000
blt x14,x15,6d0 <_start+0x6d0>
lw x14,288(x2)
addi x15,x0,1000
blt x15,x14,6d0 <_start+0x6d0>
lw x14,288(x2)
addi x15,x0,-1000
blt x14,x15,6d0 <_start+0x6d0>
lw x15,292(x2)
mul x14,x15,x15
lw x15,288(x2)
mul x15,x15,x15
add x15,x14,x15
sw x15,284(x2)
lw x15,284(x2)
beq x15,x0,6d8 <_start+0x6d8>
lw x15,284(x2)
sw x15,268(x2)
lw x15,268(x2)
blt x0,x15,160 <_start+0x160>
addi x15,x0,0
jal x0,3e4 <_start+0x3e4>
lw x15,268(x2)
sw x15,264(x2)
lw x15,268(x2)
sw x15,260(x2)
lw x15,264(x2)
sw x15,256(x2)
lw x15,256(x2)
bne x15,x0,188 <_start+0x188>
addi x15,x0,0
jal x0,288 <_start+0x288>
addi x15,x0,1
sw x15,252(x2)
lw x15,260(x2)
bge x15,x0,1b4 <_start+0x1b4>
lw x15,252(x2)
sub x15,x0,x15
sw x15,252(x2)
lw x15,260(x2)
sub x15,x0,x15
sw x15,248(x2)
jal x0,1bc <_start+0x1bc>
lw x15,260(x2)
sw x15,248(x2)
lw x15,256(x2)
bge x15,x0,1e0 <_start+0x1e0>
lw x15,252(x2)
sub x15,x0,x15
sw x15,252(x2)
lw x15,256(x2)
sub x15,x0,x15
sw x15,244(x2)
jal x0,1e8 <_start+0x1e8>
lw x15,256(x2)
sw x15,244(x2)
sw x0,240(x2)
sw x0,236(x2)
addi x15,x0,31
sw x15,232(x2)
jal x0,264 <_start+0x264>
lw x15,236(x2)
slli x15,x15,0x1
sw x15,236(x2)
lw x15,232(x2)
lw x14,248(x2)
srl x15,x14,x15
andi x15,x15,1
lw x14,236(x2)
or x15,x14,x15
sw x15,236(x2)
lw x14,236(x2)
lw x15,244(x2)
bltu x14,x15,258 <_start+0x258>
lw x14,236(x2)
lw x15,244(x2)
sub x15,x14,x15
sw x15,236(x2)
lw x15,232(x2)
addi x14,x0,1
sll x15,x14,x15
lw x14,240(x2)
or x15,x14,x15
sw x15,240(x2)
lw x15,232(x2)
addi x15,x15,-1
sw x15,232(x2)
lw x15,232(x2)
bge x15,x0,1fc <_start+0x1fc>
lw x14,252(x2)
addi x15,x0,-1
bne x14,x15,284 <_start+0x284>
lw x15,240(x2)
sub x15,x0,x15
jal x0,288 <_start+0x288>
lw x15,240(x2)
lw x14,264(x2)
add x15,x15,x14
srai x15,x15,0x1
sw x15,228(x2)
jal x0,3d4 <_start+0x3d4>
lw x15,228(x2)
sw x15,264(x2)
lw x15,268(x2)
sw x15,224(x2)
lw x15,264(x2)
sw x15,220(x2)
lw x15,220(x2)
bne x15,x0,2c4 <_start+0x2c4>
addi x15,x0,0
jal x0,3c4 <_start+0x3c4>
addi x15,x0,1
sw x15,216(x2)
lw x15,224(x2)
bge x15,x0,2f0 <_start+0x2f0>
lw x15,216(x2)
sub x15,x0,x15
sw x15,216(x2)
lw x15,224(x2)
sub x15,x0,x15
sw x15,212(x2)
jal x0,2f8 <_start+0x2f8>
lw x15,224(x2)
sw x15,212(x2)
lw x15,220(x2)
bge x15,x0,31c <_start+0x31c>
lw x15,216(x2)
sub x15,x0,x15
sw x15,216(x2)
lw x15,220(x2)
sub x15,x0,x15
sw x15,208(x2)
jal x0,324 <_start+0x324>
lw x15,220(x2)
sw x15,208(x2)
sw x0,204(x2)
sw x0,200(x2)
addi x15,x0,31
sw x15,196(x2)
jal x0,3a0 <_start+0x3a0>
lw x15,200(x2)
slli x15,x15,0x1
sw x15,200(x2)
lw x15,196(x2)
lw x14,212(x2)
srl x15,x14,x15
andi x15,x15,1
lw x14,200(x2)
or x15,x14,x15
sw x15,200(x2)
lw x14,200(x2)
lw x15,208(x2)
bltu x14,x15,394 <_start+0x394>
lw x14,200(x2)
lw x15,208(x2)
sub x15,x14,x15
sw x15,200(x2)
lw x15,196(x2)
addi x14,x0,1
sll x15,x14,x15
lw x14,204(x2)
or x15,x14,x15
sw x15,204(x2)
lw x15,196(x2)
addi x15,x15,-1
sw x15,196(x2)
lw x15,196(x2)
bge x15,x0,338 <_start+0x338>
lw x14,216(x2)
addi x15,x0,-1
bne x14,x15,3c0 <_start+0x3c0>
lw x15,204(x2)
sub x15,x0,x15
jal x0,3c4 <_start+0x3c4>
lw x15,204(x2)
lw x14,264(x2)
add x15,x15,x14
srai x15,x15,0x1
sw x15,228(x2)
lw x14,228(x2)
lw x15,264(x2)
blt x14,x15,29c <_start+0x29c>
lw x15,264(x2)
sw x15,280(x2)
lw x15,280(x2)
beq x15,x0,6e0 <_start+0x6e0>
lw x14,284(x2)
lw x15,280(x2)
mul x15,x14,x15
sw x15,276(x2)
lw x15,276(x2)
srli x15,x15,0x6
sw x15,296(x2)
lw x15,296(x2)
bne x15,x0,41c <_start+0x41c>
addi x15,x0,1
sw x15,296(x2)
lw x15,316(x2)
slli x15,x15,0x2
addi x14,x2,320
add x15,x14,x15
lw x14,-312(x15)
lw x15,312(x2)
slli x15,x15,0x2
addi x13,x2,320
add x15,x13,x15
lw x15,-312(x15)
mul x14,x14,x15
addi x15,x14,0
slli x15,x15,0x2
add x15,x15,x14
slli x15,x15,0x1
sw x15,272(x2)
lw x14,272(x2)
lw x15,292(x2)
mul x14,x14,x15
lw x15,296(x2)
sw x14,160(x2)
sw x15,156(x2)
lw x15,156(x2)
bne x15,x0,484 <_start+0x484>
addi x15,x0,0
jal x0,584 <_start+0x584>
addi x15,x0,1
sw x15,152(x2)
lw x15,160(x2)
bge x15,x0,4b0 <_start+0x4b0>
lw x15,152(x2)
sub x15,x0,x15
sw x15,152(x2)
lw x15,160(x2)
sub x15,x0,x15
sw x15,148(x2)
jal x0,4b8 <_start+0x4b8>
lw x15,160(x2)
sw x15,148(x2)
lw x15,156(x2)
bge x15,x0,4dc <_start+0x4dc>
lw x15,152(x2)
sub x15,x0,x15
sw x15,152(x2)
lw x15,156(x2)
sub x15,x0,x15
sw x15,144(x2)
jal x0,4e4 <_start+0x4e4>
lw x15,156(x2)
sw x15,144(x2)
sw x0,140(x2)
sw x0,136(x2)
addi x15,x0,31
sw x15,132(x2)
jal x0,560 <_start+0x560>
lw x15,136(x2)
slli x15,x15,0x1
sw x15,136(x2)
lw x15,132(x2)
lw x14,148(x2)
srl x15,x14,x15
andi x15,x15,1
lw x14,136(x2)
or x15,x14,x15
sw x15,136(x2)
lw x14,136(x2)
lw x15,144(x2)
bltu x14,x15,554 <_start+0x554>
lw x14,136(x2)
lw x15,144(x2)
sub x15,x14,x15
sw x15,136(x2)
lw x15,132(x2)
addi x14,x0,1
sll x15,x14,x15
lw x14,140(x2)
or x15,x14,x15
sw x15,140(x2)
lw x15,132(x2)
addi x15,x15,-1
sw x15,132(x2)
lw x15,132(x2)
bge x15,x0,4f8 <_start+0x4f8>
lw x14,152(x2)
addi x15,x0,-1
bne x14,x15,580 <_start+0x580>
lw x15,140(x2)
sub x15,x0,x15
jal x0,584 <_start+0x584>
lw x15,140(x2)
lw x14,304(x2)
add x15,x14,x15
sw x15,304(x2)
lw x14,272(x2)
lw x15,288(x2)
mul x14,x14,x15
lw x15,296(x2)
sw x14,192(x2)
sw x15,188(x2)
lw x15,188(x2)
bne x15,x0,5b8 <_start+0x5b8>
addi x15,x0,0
jal x0,6b8 <_start+0x6b8>
addi x15,x0,1
sw x15,184(x2)
lw x15,192(x2)
bge x15,x0,5e4 <_start+0x5e4>
lw x15,184(x2)
sub x15,x0,x15
sw x15,184(x2)
lw x15,192(x2)
sub x15,x0,x15
sw x15,180(x2)
jal x0,5ec <_start+0x5ec>
lw x15,192(x2)
sw x15,180(x2)
lw x15,188(x2)
bge x15,x0,610 <_start+0x610>
lw x15,184(x2)
sub x15,x0,x15
sw x15,184(x2)
lw x15,188(x2)
sub x15,x0,x15
sw x15,176(x2)
jal x0,618 <_start+0x618>
lw x15,188(x2)
sw x15,176(x2)
sw x0,172(x2)
sw x0,168(x2)
addi x15,x0,31
sw x15,164(x2)
jal x0,694 <_start+0x694>
lw x15,168(x2)
slli x15,x15,0x1
sw x15,168(x2)
lw x15,164(x2)
lw x14,180(x2)
srl x15,x14,x15
andi x15,x15,1
lw x14,168(x2)
or x15,x14,x15
sw x15,168(x2)
lw x14,168(x2)
lw x15,176(x2)
bltu x14,x15,688 <_start+0x688>
lw x14,168(x2)
lw x15,176(x2)
sub x15,x14,x15
sw x15,168(x2)
lw x15,164(x2)
addi x14,x0,1
sll x15,x14,x15
lw x14,172(x2)
or x15,x14,x15
sw x15,172(x2)
lw x15,164(x2)
addi x15,x15,-1
sw x15,164(x2)
lw x15,164(x2)
bge x15,x0,62c <_start+0x62c>
lw x14,184(x2)
addi x15,x0,-1
bne x14,x15,6b4 <_start+0x6b4>
lw x15,172(x2)
sub x15,x0,x15
jal x0,6b8 <_start+0x6b8>
lw x15,172(x2)
lw x14,300(x2)
add x15,x14,x15
sw x15,300(x2)
jal x0,6e4 <_start+0x6e4>
addi x0,x0,0
jal x0,6e4 <_start+0x6e4>
addi x0,x0,0
jal x0,6e4 <_start+0x6e4>
addi x0,x0,0
jal x0,6e4 <_start+0x6e4>
addi x0,x0,0
lw x15,312(x2)
addi x15,x15,1
sw x15,312(x2)
lw x14,312(x2)
addi x15,x0,2
bge x15,x14,8c <_start+0x8c>
lw x15,316(x2)
slli x15,x15,0x2
addi x14,x2,320
add x15,x14,x15
lw x15,-312(x15)
lw x14,304(x2)
sw x14,96(x2)
sw x15,92(x2)
lw x15,92(x2)
bne x15,x0,72c <_start+0x72c>
addi x14,x0,0
jal x0,82c <_start+0x82c>
addi x15,x0,1
sw x15,88(x2)
lw x15,96(x2)
bge x15,x0,758 <_start+0x758>
lw x15,88(x2)
sub x15,x0,x15
sw x15,88(x2)
lw x15,96(x2)
sub x15,x0,x15
sw x15,84(x2)
jal x0,760 <_start+0x760>
lw x15,96(x2)
sw x15,84(x2)
lw x15,92(x2)
bge x15,x0,784 <_start+0x784>
lw x15,88(x2)
sub x15,x0,x15
sw x15,88(x2)
lw x15,92(x2)
sub x15,x0,x15
sw x15,80(x2)
jal x0,78c <_start+0x78c>
lw x15,92(x2)
sw x15,80(x2)
sw x0,76(x2)
sw x0,72(x2)
addi x15,x0,31
sw x15,68(x2)
jal x0,808 <_start+0x808>
lw x15,72(x2)
slli x15,x15,0x1
sw x15,72(x2)
lw x15,68(x2)
lw x14,84(x2)
srl x15,x14,x15
andi x15,x15,1
lw x14,72(x2)
or x15,x14,x15
sw x15,72(x2)
lw x14,72(x2)
lw x15,80(x2)
bltu x14,x15,7fc <_start+0x7fc>
lw x14,72(x2)
lw x15,80(x2)
sub x15,x14,x15
sw x15,72(x2)
lw x15,68(x2)
addi x14,x0,1
sll x15,x14,x15
lw x14,76(x2)
or x15,x14,x15
sw x15,76(x2)
lw x15,68(x2)
addi x15,x15,-1
sw x15,68(x2)
lw x15,68(x2)
bge x15,x0,7a0 <_start+0x7a0>
lw x14,88(x2)
addi x15,x0,-1
bne x14,x15,828 <_start+0x828>
lw x15,76(x2)
sub x14,x0,x15
jal x0,82c <_start+0x82c>
lw x14,76(x2)
lw x15,316(x2)
slli x15,x15,0x2
addi x13,x2,320
add x15,x13,x15
lw x15,-288(x15)
add x14,x14,x15
lw x15,316(x2)
slli x15,x15,0x2
addi x13,x2,320
add x15,x13,x15
sw x14,-288(x15)
lw x15,316(x2)
slli x15,x15,0x2
addi x14,x2,320
add x15,x14,x15
lw x15,-312(x15)
lw x14,300(x2)
sw x14,128(x2)
sw x15,124(x2)
lw x15,124(x2)
bne x15,x0,888 <_start+0x888>
addi x14,x0,0
jal x0,988 <_start+0x988>
addi x15,x0,1
sw x15,120(x2)
lw x15,128(x2)
bge x15,x0,8b4 <_start+0x8b4>
lw x15,120(x2)
sub x15,x0,x15
sw x15,120(x2)
lw x15,128(x2)
sub x15,x0,x15
sw x15,116(x2)
jal x0,8bc <_start+0x8bc>
lw x15,128(x2)
sw x15,116(x2)
lw x15,124(x2)
bge x15,x0,8e0 <_start+0x8e0>
lw x15,120(x2)
sub x15,x0,x15
sw x15,120(x2)
lw x15,124(x2)
sub x15,x0,x15
sw x15,112(x2)
jal x0,8e8 <_start+0x8e8>
lw x15,124(x2)
sw x15,112(x2)
sw x0,108(x2)
sw x0,104(x2)
addi x15,x0,31
sw x15,100(x2)
jal x0,964 <_start+0x964>
lw x15,104(x2)
slli x15,x15,0x1
sw x15,104(x2)
lw x15,100(x2)
lw x14,116(x2)
srl x15,x14,x15
andi x15,x15,1
lw x14,104(x2)
or x15,x14,x15
sw x15,104(x2)
lw x14,104(x2)
lw x15,112(x2)
bltu x14,x15,958 <_start+0x958>
lw x14,104(x2)
lw x15,112(x2)
sub x15,x14,x15
sw x15,104(x2)
lw x15,100(x2)
addi x14,x0,1
sll x15,x14,x15
lw x14,108(x2)
or x15,x14,x15
sw x15,108(x2)
lw x15,100(x2)
addi x15,x15,-1
sw x15,100(x2)
lw x15,100(x2)
bge x15,x0,8fc <_start+0x8fc>
lw x14,120(x2)
addi x15,x0,-1
bne x14,x15,984 <_start+0x984>
lw x15,108(x2)
sub x14,x0,x15
jal x0,988 <_start+0x988>
lw x14,108(x2)
lw x15,316(x2)
slli x15,x15,0x2
addi x13,x2,320
add x15,x13,x15
lw x15,-300(x15)
add x14,x14,x15
lw x15,316(x2)
slli x15,x15,0x2
addi x13,x2,320
add x15,x13,x15
sw x14,-300(x15)
lw x15,316(x2)
addi x15,x15,1
sw x15,316(x2)
lw x14,316(x2)
addi x15,x0,2
bge x15,x14,7c <_start+0x7c>
sw x0,316(x2)
jal x0,a60 <_start+0xa60>
lw x15,316(x2)
slli x15,x15,0x2
addi x14,x2,320
add x15,x14,x15
lw x14,-264(x15)
lw x15,316(x2)
slli x15,x15,0x2
addi x13,x2,320
add x15,x13,x15
lw x15,-288(x15)
add x14,x14,x15
lw x15,316(x2)
slli x15,x15,0x2
addi x13,x2,320
add x15,x13,x15
sw x14,-264(x15)
lw x15,316(x2)
slli x15,x15,0x2
addi x14,x2,320
add x15,x14,x15
lw x14,-276(x15)
lw x15,316(x2)
slli x15,x15,0x2
addi x13,x2,320
add x15,x13,x15
lw x15,-300(x15)
add x14,x14,x15
lw x15,316(x2)
slli x15,x15,0x2
addi x13,x2,320
add x15,x13,x15
sw x14,-276(x15)
lw x15,316(x2)
addi x15,x15,1
sw x15,316(x2)
lw x14,316(x2)
addi x15,x0,2
bge x15,x14,9d4 <_start+0x9d4>
lw x15,308(x2)
addi x15,x15,1
sw x15,308(x2)
lw x14,308(x2)
addi x15,x0,999
bge x15,x14,74 <_start+0x74>
addi x15,x0,0
addi x10,x15,0
addi x2,x2,320
jalr x0,0(x1)
