# Compiled from software/programs/memspaces/memspaces.c and its generated entry code (default
# profile: 32 lanes, 128-byte stacks): the runtime ABI of docs/runtime-spec.md. _start jumps to the
# entry named by the launch block in ddr_seed.mem, which runs memspaces over a grid of 2 blocks:
# tp/gp block indices, parameters from GMEM, .rodata (gain[], a jump table), .data, .bss, shared
# memory, the stack and a call through auipc/jalr.
slli	x6,x31,0x7
lui	x2,0x4
addi	x2,x2,0 # 4000 <__stack_top>
sub	x2,x2,x6
lui	x5,0x18800
lw	x5,0(x5) # 18800000 <__gpu_launch>
jalr	x1,0(x5)
addi	x17,x0,0
ecall
addi	x15,x0,5
bltu	x15,x10,78 <op_result+0x54>
lui	x14,0x18800
slli	x15,x10,0x2
addi	x14,x14,256 # 18800100 <__gmem_data_start>
add	x15,x15,x14
lw	x15,0(x15)
jalr	x0,0(x15)
addi	x10,x11,0
jalr	x0,0(x1)
slli	x15,x11,0x1
add	x10,x15,x11
jalr	x0,0(x1)
addi	x10,x11,77
jalr	x0,0(x1)
sub	x10,x0,x11
jalr	x0,0(x1)
slli	x10,x11,0x4
jalr	x0,0(x1)
xori	x10,x11,85
jalr	x0,0(x1)
addi	x10,x0,0
jalr	x0,0(x1)
addi	x2,x2,-64
sw	x8,56(x2)
sw	x19,44(x2)
addi	x8,x31,0
sw	x8,0(x2)
addi	x19,x8,1
sw	x19,4(x2)
addi	x15,x8,2
sw	x15,8(x2)
addi	x15,x8,3
sw	x15,12(x2)
sw	x9,52(x2)
lw	x9,0(x2)
lw	x15,4(x2)
lw	x14,8(x2)
sw	x18,48(x2)
add	x9,x9,x15
lw	x15,12(x2)
add	x9,x9,x14
slli	x18,x4,0x10
slli	x14,x8,0x1
add	x9,x9,x15
lui	x15,0x0
sw	x21,36(x2)
srli	x18,x18,0x10
add	x14,x14,x8
slli	x21,x8,0x2
addi	x15,x15,128 # 80 <memspaces>
sw	x22,32(x2)
sw	x23,28(x2)
sw	x1,60(x2)
sw	x20,40(x2)
add	x14,x14,x18
add	x13,x15,x21
sw	x14,0(x13)
addi	x22,x11,0
addi	x23,x10,0
andi	x14,x19,31
slli	x14,x14,0x2
add	x15,x15,x14
addi	x11,x8,0
lw	x20,0(x15)
auipc	x1,0x0
jalr	x1,-260(x1) # 24 <op_result>
andi	x15,x8,7
lui	x13,0x18800
slli	x15,x15,0x2
addi	x13,x13,288 # 18800120 <gain>
add	x13,x13,x15
andi	x12,x8,3
lui	x15,0x18800
slli	x12,x12,0x2
addi	x15,x15,324 # 18800144 <bias>
add	x15,x15,x12
lw	x17,0(x13)
lui	x14,0x18800
lw	x13,0(x15)
addi	x14,x14,596 # 18800254 <slots>
lui	x11,0x18800
lw	x16,320(x11) # 18800140 <call_count>
add	x15,x10,x17
add	x14,x14,x21
lw	x12,0(x14)
add	x15,x15,x13
lui	x13,0x18800
slli	x10,x18,0x2
addi	x13,x13,280 # 18800118 <offsets>
add	x13,x13,x10
add	x15,x15,x16
lw	x10,0(x13)
add	x15,x15,x12
slli	x13,x18,0x5
lui	x12,0x18800
lw	x12,4(x12) # 18800004 <__gpu_launch+0x4>
add	x15,x15,x9
add	x13,x13,x8
add	x15,x15,x20
slli	x13,x13,0x2
add	x15,x15,x10
add	x13,x22,x13
sw	x15,0(x13)
addi	x15,x12,-1
bne	x15,x18,1e4 <__shared_end+0xe4>
lw	x15,320(x11)
lui	x13,0x18800
sw	x19,0(x14)
addi	x15,x15,1
sw	x15,320(x11)
sw	x23,724(x13) # 188002d4 <last_op>
lw	x1,60(x2)
lw	x8,56(x2)
lw	x9,52(x2)
lw	x18,48(x2)
lw	x19,44(x2)
lw	x20,40(x2)
lw	x21,36(x2)
lw	x22,32(x2)
lw	x23,28(x2)
addi	x2,x2,64
jalr	x0,0(x1)
addi	x15,x31,0
slli	x15,x15,0x2
add	x10,x10,x15
lw	x14,0(x10)
add	x11,x11,x15
sw	x14,0(x11)
jalr	x0,0(x1)
lui	x15,0x18800
addi	x2,x2,-48
addi	x15,x15,0 # 18800000 <__gpu_launch>
sw	x24,8(x2)
lw	x24,12(x15)
sw	x1,44(x2)
sw	x18,32(x2)
sw	x19,28(x2)
sw	x20,24(x2)
sw	x21,20(x2)
sw	x23,12(x2)
beq	x24,x0,27c <__gpgpu_kernel_memspaces+0x50>
lw	x23,8(x15)
lw	x20,32(x15)
lw	x21,36(x15)
lw	x19,4(x15)
addi	x18,x0,0
bne	x23,x0,2a0 <__gpgpu_kernel_memspaces+0x74>
addi	x18,x18,1
bne	x24,x18,274 <__gpgpu_kernel_memspaces+0x48>
lw	x1,44(x2)
lw	x18,32(x2)
lw	x19,28(x2)
lw	x20,24(x2)
lw	x21,20(x2)
lw	x23,12(x2)
lw	x24,8(x2)
addi	x2,x2,48
jalr	x0,0(x1)
sw	x8,40(x2)
sw	x9,36(x2)
sw	x22,16(x2)
beq	x19,x0,2fc <__gpgpu_kernel_memspaces+0xd0>
addi	x22,x0,0
slli	x9,x22,0x10
addi	x8,x0,0
or	x4,x9,x8
addi	x3,x18,0
addi	x11,x21,0
addi	x10,x20,0
auipc	x1,0x0
jalr	x1,-588(x1) # 80 <memspaces>
addi	x8,x8,1
bne	x19,x8,2bc <__gpgpu_kernel_memspaces+0x90>
addi	x22,x22,1
bne	x23,x22,2b4 <__gpgpu_kernel_memspaces+0x88>
addi	x18,x18,1
bne	x18,x24,2ac <__gpgpu_kernel_memspaces+0x80>
lw	x8,40(x2)
lw	x9,36(x2)
lw	x22,16(x2)
jal	x0,27c <__gpgpu_kernel_memspaces+0x50>
addi	x18,x18,1
beq	x18,x24,2ec <__gpgpu_kernel_memspaces+0xc0>
addi	x18,x18,1
bne	x18,x24,2fc <__gpgpu_kernel_memspaces+0xd0>
jal	x0,2ec <__gpgpu_kernel_memspaces+0xc0>
lui	x15,0x18800
addi	x2,x2,-48
addi	x15,x15,0 # 18800000 <__gpu_launch>
sw	x24,8(x2)
lw	x24,12(x15)
sw	x1,44(x2)
sw	x18,32(x2)
sw	x19,28(x2)
sw	x20,24(x2)
sw	x21,20(x2)
sw	x23,12(x2)
beq	x24,x0,360 <__gpgpu_kernel_memspaces_fault+0x50>
lw	x23,8(x15)
lw	x20,32(x15)
lw	x21,36(x15)
lw	x19,4(x15)
addi	x18,x0,0
bne	x23,x0,384 <__gpgpu_kernel_memspaces_fault+0x74>
addi	x18,x18,1
bne	x24,x18,358 <__gpgpu_kernel_memspaces_fault+0x48>
lw	x1,44(x2)
lw	x18,32(x2)
lw	x19,28(x2)
lw	x20,24(x2)
lw	x21,20(x2)
lw	x23,12(x2)
lw	x24,8(x2)
addi	x2,x2,48
jalr	x0,0(x1)
sw	x8,40(x2)
sw	x9,36(x2)
sw	x22,16(x2)
beq	x19,x0,3e0 <__gpgpu_kernel_memspaces_fault+0xd0>
addi	x22,x0,0
slli	x9,x22,0x10
addi	x8,x0,0
or	x4,x9,x8
addi	x3,x18,0
addi	x11,x21,0
addi	x10,x20,0
auipc	x1,0x0
jalr	x1,-416(x1) # 210 <memspaces_fault>
addi	x8,x8,1
bne	x19,x8,3a0 <__gpgpu_kernel_memspaces_fault+0x90>
addi	x22,x22,1
bne	x23,x22,398 <__gpgpu_kernel_memspaces_fault+0x88>
addi	x18,x18,1
bne	x18,x24,390 <__gpgpu_kernel_memspaces_fault+0x80>
lw	x8,40(x2)
lw	x9,36(x2)
lw	x22,16(x2)
jal	x0,360 <__gpgpu_kernel_memspaces_fault+0x50>
addi	x18,x18,1
beq	x18,x24,3d0 <__gpgpu_kernel_memspaces_fault+0xc0>
addi	x18,x18,1
bne	x18,x24,3e0 <__gpgpu_kernel_memspaces_fault+0xd0>
jal	x0,3d0 <__gpgpu_kernel_memspaces_fault+0xc0>
