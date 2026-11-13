# RV32M high-half multiplies: MULH (signed x signed), MULHSU (signed x
# unsigned) and MULHU (unsigned x unsigned) on the corner values (-2^31, -1,
# 2^31 - 1), on a different signed pair per lane, and through the pipeline:
# a result used by the next instruction, a MULHU fed by a MULH, a MULH fed by
# a load, a MULH result stored at once, a write to x0, and MUL around them.
# Each lane stores every result in its own slot, for the benches that only
# check memory.
lui    x3, 0x1
slli   x4, x31, 2
add    x3, x3, x4        # x3: 0x1000 + lane * 4, one array every 128 bytes

lui    x5, 0x80000       # -2^31 (2^31 unsigned)
addi   x6, x0, -1        # -1 (2^32 - 1 unsigned)
addi   x7, x5, -1        # 2^31 - 1

mulh   x10, x5, x5       # 0x40000000
mulhsu x11, x5, x5       # -2^31 * 2^31: 0xC0000000
mulhu  x12, x5, x5       # 0x40000000
mulh   x13, x6, x6       # 1: 0x00000000
mulhsu x14, x6, x6       # -1 * (2^32 - 1): 0xFFFFFFFF
mulhu  x15, x6, x6       # 0xFFFFFFFE
mulh   x16, x7, x5       # (2^31 - 1) * -2^31: 0xC0000000
mul    x17, x5, x6       # low half unchanged: 0x80000000

lui    x8, 0x9E378
addi   x8, x8, -0x64F    # 0x9E3779B1
addi   x9, x31, 1
mul    x8, x8, x9        # a: (lane + 1) * 0x9E3779B1, either sign
slli   x9, x31, 27
xor    x9, x9, x8
mul    x9, x9, x8        # b: another word per lane, either sign
mulh   x18, x8, x9
mulhsu x19, x8, x9
mulhu  x20, x8, x9
mul    x21, x8, x9

mulh   x22, x8, x9
add    x22, x22, x31     # uses the MULH result in the next instruction
mulh   x23, x8, x9
mulhu  x23, x23, x9      # MULHU of a MULH result, back to back
sw     x8, 0(x4)         # DMEM[lane] = a
lw     x24, 0(x4)
mulh   x24, x24, x9      # load-use into MULH
mulhu  x0, x8, x9        # writes nothing
mulhsu x25, x9, x8
sw     x25, 1920(x3)     # a MULHSU result as store data at once

sw     x10, 0(x3)
sw     x11, 128(x3)
sw     x12, 256(x3)
sw     x13, 384(x3)
sw     x14, 512(x3)
sw     x15, 640(x3)
sw     x16, 768(x3)
sw     x17, 896(x3)
sw     x18, 1024(x3)
sw     x19, 1152(x3)
sw     x20, 1280(x3)
sw     x21, 1408(x3)
sw     x22, 1536(x3)
sw     x23, 1664(x3)
sw     x24, 1792(x3)
addi   x17, x0, 0
ecall
