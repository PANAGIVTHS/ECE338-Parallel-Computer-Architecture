# AUIPC: rd = PC + (imm << 12), with the PC of the instruction itself. Its
# immediate overlaps the rs1/rs2 fields, which must select no operand. Each lane
# stores every result in its own slot, for the benches that only check memory.
lui   x3, 0x1
slli  x4, x31, 2
add   x3, x3, x4        # x3: 0x1000 + lane * 4, one array every 128 bytes
lui   x4, 0x1
srli  x4, x4, 1
add   x4, x3, x4        # x4: the same 0x800 higher

auipc x5, 0
auipc x6, 1
auipc x7, 0xFFFFF       # wraps around 32 bits
auipc x8, 0x80000

addi  x9, x0, 0x55
auipc x10, 0x48         # rs1 field = x9, in EX/MEM: not forwarded
auipc x11, 0x900        # rs2 field = x9, in MEM/WB: not forwarded

lw    x12, 0(x0)
auipc x13, 0x60         # rs1 field = x12, a load: stalls, keeps its own PC
mul   x14, x9, x9
auipc x15, 2            # stalls behind the multiplier, keeps its own PC

auipc x16, 3
add   x17, x16, x16     # forwarded from EX/MEM
auipc x18, 4
nop
add   x19, x18, x18     # forwarded from MEM/WB

auipc x20, 0            # the call sequence GCC emits
jalr  x21, 16(x20)      # to helper, x21 = return address
addi  x22, x21, 1       # back from helper
jal   x0, after_call
helper:
addi  x23, x0, 77
jalr  x0, 0(x21)        # not RET: the link register is x21

after_call:
auipc x24, 0            # first instruction after a jump: the target's PC
beq   x0, x0, taken
auipc x25, 7            # flushed: x25 stays 0
taken:
auipc x26, 5            # first instruction after a taken branch

sw    x5, 0(x3)
sw    x6, 128(x3)
sw    x7, 256(x3)
sw    x8, 384(x3)
sw    x10, 512(x3)
sw    x11, 640(x3)
sw    x13, 768(x3)
sw    x15, 896(x3)
sw    x16, 1024(x3)
sw    x17, 1152(x3)
sw    x18, 1280(x3)
sw    x19, 1408(x3)
sw    x20, 1536(x3)
sw    x21, 1664(x3)
sw    x22, 1792(x3)
sw    x23, 1920(x3)
sw    x24, 0(x4)
sw    x25, 128(x4)
sw    x26, 256(x4)
addi  x17, x0, 0
ecall
