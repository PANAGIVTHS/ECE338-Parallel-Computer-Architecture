# Compiled from software/programs/memspaces/memspaces.c (default profile: 32 lanes,
# 128-byte stacks, GPGPU_ARGS at DMEM 0, .shared at 0x80, compiler data at GMEM_BASE).
# Every memory space of linker.ld: GPGPU_ARGS (op = 0, DMEM cleared), out[] in .shared,
# tmp[] on the stack, gain[] and a jump table in .rodata, call_count and bias[] in
# .data, slots[] and last_op in .bss. ddr_seed.mem is the program's GMEM image.

addi	x5,x31,0
slli	x6,x5,0x7
lui	x2,0x4
addi	x2,x2,0 # 4000 <__stack_top>
sub	x2,x2,x6
jal	x1,20 <kernel_main>
addi	x17,x0,0
ecall
addi	x2,x2,-16
addi	x14,x31,0
lui	x15,0x0
lw	x10,0(x15) # 0 <_start>
addi	x16,x14,1
sw	x14,0(x2)
sw	x16,4(x2)
addi	x15,x14,2
sw	x15,8(x2)
addi	x15,x14,3
sw	x15,12(x2)
lw	x13,0(x2)
lw	x11,4(x2)
lw	x12,8(x2)
lw	x15,12(x2)
add	x13,x13,x11
add	x13,x13,x12
addi	x12,x0,5
add	x13,x13,x15
bltu	x12,x10,144 <__shared_end+0x44>
lui	x11,0x18800
addi	x11,x11,0 # 18800000 <__gmem_data_start>
slli	x12,x10,0x2
add	x12,x12,x11
lw	x12,0(x12)
addi	x15,x14,0
jalr	x0,0(x12)
slli	x15,x14,0x4
lui	x12,0x18800
andi	x11,x14,7
slli	x11,x11,0x2
addi	x12,x12,24 # 18800018 <gain>
add	x12,x12,x11
andi	x17,x14,3
lui	x11,0x18800
slli	x17,x17,0x2
addi	x11,x11,56 # 18800038 <bias>
add	x11,x11,x17
lw	x17,0(x12)
lui	x12,0x18800
lw	x11,0(x11)
slli	x6,x14,0x2
lui	x28,0x18800
addi	x12,x12,76 # 1880004c <slots>
add	x15,x15,x17
add	x12,x12,x6
lw	x17,72(x28) # 18800048 <call_count>
lw	x29,0(x12)
add	x15,x15,x11
add	x15,x15,x17
lui	x11,0x0
add	x15,x15,x29
addi	x11,x11,128 # 80 <out>
add	x15,x15,x13
add	x13,x11,x6
sw	x16,0(x12)
sw	x15,0(x13)
bne	x14,x0,118 <__shared_end+0x18>
addi	x17,x17,1
lui	x15,0x18800
sw	x17,72(x28)
sw	x10,204(x15) # 188000cc <last_op>
addi	x2,x2,16
jalr	x0,0(x1)
xori	x15,x14,85
jal	x0,90 <out+0x10>
slli	x15,x14,0x1
add	x15,x15,x14
jal	x0,90 <out+0x10>
addi	x15,x14,77
jal	x0,90 <out+0x10>
sub	x15,x0,x14
jal	x0,90 <out+0x10>
addi	x15,x0,0
jal	x0,90 <out+0x10>
