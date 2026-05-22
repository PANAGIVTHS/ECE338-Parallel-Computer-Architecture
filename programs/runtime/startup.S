.section .text
.global _start

_start:

    # ==========================================
    # Compute private stack per SP
    #
    # x31 = core ID
    #
    # STACK_BASE = 0x2000
    # STACK_SIZE = 256 bytes
    # ==========================================

    slli t0, x31, 8

    lui sp, 0x2

    add sp, sp, t0

    # ==========================================
    # Call C main()
    # ==========================================

    call main

1:
    jal x0, 1b