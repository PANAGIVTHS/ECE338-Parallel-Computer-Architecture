#include "../gpgpu_runtime.h"

#define CORES GPGPU_NUM_CORES

/*
 * Switching-activity stress test: each mode keeps one part of the SPs busy
 * for a host-chosen number of iterations, to find which activity disturbs
 * the board (e.g. the HDMI output).
 *
 * The seed sets how much the data toggles while the instructions stay the
 * same: every mode keeps zero data at zero, so seed 0 runs the identical
 * instruction stream with a constant data path, and a random-looking odd
 * seed (e.g. 0x9E3779B9) toggles about half of the bits every operation.
 *
 * Lanes branch with lane 0; the mode and the loop count are the same for
 * every lane, so the branches are uniform.
 */
#define MODE_LOOP 0u  /* loop counter and branch only */
#define MODE_ALU  1u  /* xorshift32: shifts and xor */
#define MODE_MUL  2u  /* eight independent x[k] *= y[k]; odd seeds stay odd */
#define MODE_DMEM 3u  /* load, xor, store to buf[tid] */
#define MODE_DDR  4u  /* stores to consecutive bursts of a framebuffer */
/* MODE_ALU split into its parts; every result feeds the next instruction. */
#define MODE_XOR  5u  /* x ^= y, y ^= x */
#define MODE_ADD  6u  /* x += y, y += x: carry chains */
#define MODE_ROT  7u  /* x = x rotated by 13: shifter and or */
/* MODE_XOR without the dependency: no result is forwarded. */
#define MODE_XOR_INDEP 8u  /* eight independent p[k] ^= y */
/* Separate forwarding from a toggling operand B. Results are forwarded one
 * and two instructions later, through the register file after three. */
#define MODE_XOR_RING  9u  /* p[k] ^= p[k + 4 mod 8]: both operands random, read
                            * four and eight instructions after their write */
#define MODE_XOR_CONST 10u /* x ^= y: operand A forwarded, operand B constant */

/* Hides v's value from the optimizer, so a chain of steps is not folded
 * into fewer instructions (e.g. eight rotations into one). */
#define KEEP(v) __asm__ volatile("" : "+r"(v))

/* MODE_DDR cycles through this many bursts (CORES words each) of buf. */
#define DDR_BURSTS 1024u

static inline __attribute__((always_inline)) unsigned int stress_lane(
    unsigned int tid,
    unsigned int mode,
    unsigned int iterations,
    unsigned int seed,
    volatile unsigned int *buf
)
{
    /* Odd multiples of the seed: zero for seed 0, odd for an odd seed. */
    unsigned int x = seed * (2u * tid + 1u);
    unsigned int y = seed * (2u * tid + 3u);

    if (mode == MODE_LOOP) {
        for (unsigned int i = 0; i < iterations; i++)
            __asm__ volatile("" ::: "memory");
    } else if (mode == MODE_ALU) {
        for (unsigned int i = 0; i < iterations; i++) {
#pragma GCC unroll 8
            for (unsigned int k = 0; k < 8; k++) {
                x ^= x << 13;
                x ^= x >> 17;
                x ^= x << 5;
            }
        }
    } else if (mode == MODE_MUL) {
        /* Independent products, so they issue back to back: the multiplier
         * is pipelined, and the hazard unit holds a MUL only while one it
         * depends on is still in that pipeline. */
        unsigned int p0 = x, p1 = y, p2 = x ^ y, p3 = x + y;
        unsigned int p4 = x * 3u, p5 = y * 3u, p6 = x * 5u, p7 = y * 5u;

        for (unsigned int i = 0; i < iterations; i++) {
            p0 *= y; p1 *= x; p2 *= y; p3 *= x;
            p4 *= y; p5 *= x; p6 *= y; p7 *= x;
        }
        x = p0 ^ p1 ^ p2 ^ p3 ^ p4 ^ p5 ^ p6 ^ p7;
    } else if (mode == MODE_DMEM) {
        buf[tid] = x;
        for (unsigned int i = 0; i < iterations; i++) {
#pragma GCC unroll 8
            for (unsigned int k = 0; k < 8; k++)
                buf[tid] = buf[tid] ^ y;
        }
        x = buf[tid];
    } else if (mode == MODE_DDR) {
        for (unsigned int i = 0; i < iterations; i++) {
            buf[(i % DDR_BURSTS) * CORES + tid] = x;
            x ^= y;
        }
    } else if (mode == MODE_XOR) {
        for (unsigned int i = 0; i < iterations; i++) {
#pragma GCC unroll 8
            for (unsigned int k = 0; k < 8; k++) {
                x ^= y;
                KEEP(x);
                y ^= x;
                KEEP(y);
            }
        }
    } else if (mode == MODE_ADD) {
        for (unsigned int i = 0; i < iterations; i++) {
#pragma GCC unroll 8
            for (unsigned int k = 0; k < 8; k++) {
                x += y;
                KEEP(x);
                y += x;
                KEEP(y);
            }
        }
    } else if (mode == MODE_ROT) {
        for (unsigned int i = 0; i < iterations; i++) {
#pragma GCC unroll 8
            for (unsigned int k = 0; k < 8; k++) {
                x = (x << 13) | (x >> 19);
                KEEP(x);
            }
        }
    } else if (mode == MODE_XOR_INDEP) {
        unsigned int p0 = x, p1 = x * 3u, p2 = x * 5u, p3 = x * 7u;
        unsigned int p4 = x * 9u, p5 = x * 11u, p6 = x * 13u, p7 = x * 15u;

        for (unsigned int i = 0; i < iterations; i++) {
            p0 ^= y; p1 ^= y; p2 ^= y; p3 ^= y;
            p4 ^= y; p5 ^= y; p6 ^= y; p7 ^= y;
        }
        x = p0 ^ p1 ^ p2 ^ p3 ^ p4 ^ p5 ^ p6 ^ p7;
    } else if (mode == MODE_XOR_RING) {
        unsigned int p0 = x, p1 = y, p2 = x * 3u, p3 = y * 3u;
        unsigned int p4 = x * 5u, p5 = y * 5u, p6 = x * 7u, p7 = y * 7u;

        for (unsigned int i = 0; i < iterations; i++) {
            p0 ^= p4; KEEP(p0); p1 ^= p5; KEEP(p1);
            p2 ^= p6; KEEP(p2); p3 ^= p7; KEEP(p3);
            p4 ^= p0; KEEP(p4); p5 ^= p1; KEEP(p5);
            p6 ^= p2; KEEP(p6); p7 ^= p3; KEEP(p7);
        }
        x = p0 ^ p1 ^ p2 ^ p3 ^ p4 ^ p5 ^ p6 ^ p7;
    } else if (mode == MODE_XOR_CONST) {
        for (unsigned int i = 0; i < iterations; i++) {
#pragma GCC unroll 8
            for (unsigned int k = 0; k < 8; k++) {
#ifdef __riscv
                /* Fixed operand order: the compiler would put x in rs2. */
                __asm__ volatile("xor %0, %0, %1" : "+r"(x) : "r"(y));
#else
                x ^= y;
#endif
            }
        }
    }

    return x ^ y;
}

#ifdef __riscv

/* No jump table for the mode: it would be read-only data in DMEM, which only
 * IMEM loading does not fill. */
__attribute__((optimize("no-jump-tables"))) void main(void)
{
    unsigned int tid = gpgpu_thread_id();

    /*
     * Args:
     *   GPGPU_ARGS[0] = mode (MODE_*)
     *   GPGPU_ARGS[1] = iterations
     *   GPGPU_ARGS[2] = seed; 0 keeps every data value at zero
     *   GPGPU_ARGS[3] = buffer, byte address: DMEM (e.g. 0x1000) for the
     *                   other modes, a framebuffer for MODE_DDR, which uses
     *                   DDR_BURSTS * CORES words of it. buf[tid] gets the
     *                   lane's result, so the computation is not removed.
     */
    unsigned int mode = (unsigned int)GPGPU_ARGS[0];
    unsigned int iterations = (unsigned int)GPGPU_ARGS[1];
    unsigned int seed = (unsigned int)GPGPU_ARGS[2];
    volatile unsigned int *buf = (volatile unsigned int *)(uintptr_t)GPGPU_ARGS[3];

    buf[tid] = stress_lane(tid, mode, iterations, seed, buf);

    return;
}

GPGPU_START(main)

#else

#include <stdio.h>
#include <stdlib.h>

static unsigned int buffer[DDR_BURSTS * CORES];

/* ./stress_x86 mode iterations seed prints every lane's result word. */
int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "usage: %s mode iterations seed\n", argv[0]);
        return 1;
    }

    unsigned int mode = (unsigned int)strtoul(argv[1], NULL, 0);
    unsigned int iterations = (unsigned int)strtoul(argv[2], NULL, 0);
    unsigned int seed = (unsigned int)strtoul(argv[3], NULL, 0);

    for (unsigned int tid = 0; tid < CORES; tid++) {
        buffer[tid] = stress_lane(tid, mode, iterations, seed, buffer);
        printf("%08x\n", buffer[tid]);
    }

    return 0;
}

#endif
