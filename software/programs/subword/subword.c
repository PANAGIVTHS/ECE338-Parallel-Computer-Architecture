#include "../gpgpu_runtime.h"

#define CORES GPGPU_NUM_CORES

/*
 * Test of the byte and halfword instructions: LB, LBU, LH, LHU, SB, SH.
 *
 * Each lane runs five small tests in DMEM and a sixth in DDR, and checks
 * what it reads back. Every failed check sets one bit in errors[tid], so a
 * correct GPU leaves errors[] all zero.
 *
 * GPGPU_ARGS[0] = DMEM byte address of the test area, e.g. 0x100.
 * GPGPU_ARGS[1] = byte address of CORES + 31 words in the texture region
 *                 (DDR, read-only for the GPU) for test 6, aligned to a DDR
 *                 group (128 bytes), or 0 to skip the test.
 *                 Test 6 checks the sub-word loads against a word load of the
 *                 same word, so any contents work; bytes and halfwords with
 *                 their sign bit both set and clear exercise the extension.
 * CORES must be even (test 5 pairs each lane with lane tid ^ 1).
 *
 * Test area, in words from GPGPU_ARGS[0]:
 *   errors[CORES]           0 = lane passed
 *   lane[CORES][4]          one word per test 1-4, per lane
 *   shared_bytes[(CORES+3)/4]  test 5: 4 lanes write one byte each into a word
 *   shared_halves[CORES/2]  test 5: 2 lanes write one halfword each into a word
 *
 * Error bits:
 *    0  test 1: SB changed more than its byte
 *    1  test 1: LBU did not read the stored byte back
 *    2  test 2: four SBs did not build 0x44332211
 *    3  test 2: LBU read a wrong byte
 *    4  test 2: LHU read a wrong half
 *    5  test 3: SH changed more than its half
 *    6  test 3: LH did not sign-extend the stored half
 *    7  test 4: LB  sign extension wrong
 *    8  test 4: LBU zero extension wrong
 *    9  test 4: LH  sign extension wrong
 *   10  test 4: LHU zero extension wrong
 *   11  test 5: own byte lost in the shared word
 *   12  test 5: neighbour's byte lost in the shared word
 *   13  test 5: shared halfword word wrong
 *   14  test 5: neighbour's halfword lost
 *   15  test 6: DDR LB  differs from the byte of the word
 *   16  test 6: DDR LBU differs from the byte of the word
 *   17  test 6: DDR LH  differs from the half of the word
 *   18  test 6: DDR LHU differs from the half of the word
 *   19  test 6: DDR LHU wrong where lanes span two bursts
 */

#define BACKGROUND 0xA5A5A5A5u

/* errors |= 1 << bit when got != expected (no branch: != gives 0 or 1). */
#define CHECK(bit, got, expected) (errors |= (uint32_t)((got) != (expected)) << (bit))

/* GCC likes to replace LB/LH with LBU/LHU plus shifts, and to clear the upper
 * bits before SB/SH. These macros force the exact instruction. */
#define LOAD(insn, addr)                                                         \
    ({ uint32_t v_; __asm__ volatile(insn " %0, 0(%1)" : "=r"(v_) : "r"(addr) : "memory"); v_; })
#define STORE(insn, value, addr)                                                 \
    __asm__ volatile(insn " %0, 0(%1)" : : "r"(value), "r"(addr) : "memory")

/* Ends one test. Without it GCC computes every test's addresses and expected
 * values up front, runs out of registers and spills more than the 64 bytes of
 * stack each lane has. */
#define END_OF_TEST() __asm__ volatile("" : "+r"(errors), "+r"(mine), "+r"(tid), "+r"(tex) : : "memory")

/* Ends one group of test 6's checks, for the same reason as END_OF_TEST. */
#define END_OF_GROUP() __asm__ volatile("" : "+r"(word6), "+r"(bytes6) : : "memory")

/* The byte or halfword at byte offset `at` of `word`, sign- or zero-extended,
 * as LB/LBU/LH/LHU must return it. */
#define BYTE_S(word, at) ((uint32_t)(int32_t)(int8_t)((word) >> (8 * (at))))
#define BYTE_U(word, at) (((word) >> (8 * (at))) & 0xFFu)
#define HALF_S(word, at) ((uint32_t)(int32_t)(int16_t)((word) >> (8 * (at))))
#define HALF_U(word, at) (((word) >> (8 * (at))) & 0xFFFFu)

#ifdef __riscv

void main(void)
{
    uint32_t tid = gpgpu_thread_id();
    volatile uint32_t *area = (volatile uint32_t *)(uintptr_t)GPGPU_ARGS[0];
    volatile uint32_t *mine = area + CORES + 4 * tid;  /* this lane's 4 words */
    const volatile uint32_t *tex = (const volatile uint32_t *)(uintptr_t)GPGPU_ARGS[1];
    uint32_t errors = 0;

    /* ---- Test 1: SB writes one byte and leaves the other three alone ----
     * Lane tid writes 0x80 + tid at byte (tid % 4) of a background word.
     * The register also holds 0xDEADBE in its upper bits; SB must ignore them. */
    volatile uint32_t *word1 = &mine[0];
    uint32_t byte = 0x80 + tid;
    uint32_t offset = tid & 3;
    *word1 = BACKGROUND;
    STORE("sb", 0xDEADBE00u | byte, (volatile uint8_t *)word1 + offset);

    uint32_t expected1 = (BACKGROUND & ~(0xFFu << (8 * offset))) | (byte << (8 * offset));
    CHECK(0, *word1, expected1);
    CHECK(1, LOAD("lbu", (volatile uint8_t *)word1 + offset), byte);

    END_OF_TEST();

    /* ---- Test 2: four SBs build a whole word ---- */
    volatile uint32_t *word2 = &mine[1];
    volatile uint8_t *bytes2 = (volatile uint8_t *)word2;
    *word2 = BACKGROUND;
    bytes2[0] = 0x11;
    bytes2[1] = 0x22;
    bytes2[2] = 0x33;
    bytes2[3] = 0x44;

    CHECK(2, *word2, 0x44332211u);
    CHECK(3, LOAD("lbu", bytes2 + 0), 0x11u);
    CHECK(3, LOAD("lbu", bytes2 + 1), 0x22u);
    CHECK(3, LOAD("lbu", bytes2 + 2), 0x33u);
    CHECK(3, LOAD("lbu", bytes2 + 3), 0x44u);
    CHECK(4, LOAD("lhu", bytes2 + 0), 0x2211u);
    CHECK(4, LOAD("lhu", bytes2 + 2), 0x4433u);

    END_OF_TEST();

    /* ---- Test 3: SH writes one half and leaves the other alone ----
     * Lane tid writes 0x8000 + tid in the low half (even lanes) or the high
     * half (odd lanes). Upper register bits 0xBEEF must be ignored. */
    volatile uint32_t *word3 = &mine[2];
    uint32_t half = 0x8000 + tid;
    uint32_t half_offset = 2 * (tid & 1);
    *word3 = BACKGROUND;
    STORE("sh", 0xBEEF0000u | half, (volatile uint8_t *)word3 + half_offset);

    uint32_t expected3 = (BACKGROUND & ~(0xFFFFu << (8 * half_offset))) | (half << (8 * half_offset));
    CHECK(5, *word3, expected3);
    /* 0x8000 + tid has its sign bit set, so LH must give 0xFFFF8000 + tid. */
    CHECK(6, LOAD("lh", (volatile uint8_t *)word3 + half_offset), 0xFFFF8000u + tid);

    END_OF_TEST();

    /* ---- Test 4: sign and zero extension at every offset ----
     * The word 0x80FF7F01 holds the bytes 01, 7F, FF, 80 (offsets 0..3):
     * two with the sign bit clear and two with it set. */
    volatile uint32_t *word4 = &mine[3];
    volatile uint8_t *bytes4 = (volatile uint8_t *)word4;
    *word4 = 0x80FF7F01u;

    CHECK(7, LOAD("lb", bytes4 + 0), 0x00000001u);
    CHECK(7, LOAD("lb", bytes4 + 1), 0x0000007Fu);
    CHECK(7, LOAD("lb", bytes4 + 2), 0xFFFFFFFFu);
    CHECK(7, LOAD("lb", bytes4 + 3), 0xFFFFFF80u);

    CHECK(8, LOAD("lbu", bytes4 + 0), 0x01u);
    CHECK(8, LOAD("lbu", bytes4 + 1), 0x7Fu);
    CHECK(8, LOAD("lbu", bytes4 + 2), 0xFFu);
    CHECK(8, LOAD("lbu", bytes4 + 3), 0x80u);

    CHECK(9, LOAD("lh", bytes4 + 0), 0x00007F01u);
    CHECK(9, LOAD("lh", bytes4 + 2), 0xFFFF80FFu);

    CHECK(10, LOAD("lhu", bytes4 + 0), 0x7F01u);
    CHECK(10, LOAD("lhu", bytes4 + 2), 0x80FFu);

    END_OF_TEST();

    /* ---- Test 5: several lanes write into the same word ----
     * Lane tid writes byte tid of shared_bytes and halfword tid of
     * shared_halves, so 4 lanes share each byte word and 2 lanes each half
     * word. All lanes store in the same instruction; none may erase another. */
    volatile uint32_t *shared_bytes = area + 5 * CORES;
    volatile uint32_t *shared_halves = shared_bytes + (CORES + 3) / 4;
    volatile uint8_t *bytes5 = (volatile uint8_t *)shared_bytes;
    volatile uint16_t *halves5 = (volatile uint16_t *)shared_halves;
    uint32_t neighbour = tid ^ 1;  /* the other lane of the same pair */

    shared_bytes[tid / 4] = 0;      /* several lanes store the same zero */
    shared_halves[tid / 2] = 0;
    bytes5[tid] = 0x80 + tid;
    halves5[tid] = 0x8000 + tid;

    CHECK(11, LOAD("lbu", bytes5 + tid), 0x80 + tid);
    CHECK(12, LOAD("lbu", bytes5 + neighbour), 0x80 + neighbour);

    uint32_t even = tid & ~1u;     /* the pair is lanes even and even + 1 */
    CHECK(13, shared_halves[tid / 2], (0x8000 + even) | (0x8000 + even + 1) << 16);
    CHECK(14, LOAD("lhu", halves5 + neighbour), 0x8000 + neighbour);

    END_OF_TEST();

    /* ---- Test 6: sub-word loads from DDR ----
     * Lane tid loads texture word tid whole, then every byte and halfword of
     * it, so each load is one read burst whose beats serve all lanes. The
     * last load reads the high half of word tid + 31, 126 bytes on: lane 0
     * stays in the first 128-byte group and the others move to the next, so
     * the lanes of one instruction span two bursts. */
    if (tex != 0) {
        const volatile uint8_t *bytes6 = (const volatile uint8_t *)(tex + tid);
        uint32_t word6 = tex[tid];

        CHECK(15, LOAD("lb", bytes6 + 0), BYTE_S(word6, 0));
        CHECK(15, LOAD("lb", bytes6 + 1), BYTE_S(word6, 1));
        CHECK(15, LOAD("lb", bytes6 + 2), BYTE_S(word6, 2));
        CHECK(15, LOAD("lb", bytes6 + 3), BYTE_S(word6, 3));

        END_OF_GROUP();

        CHECK(16, LOAD("lbu", bytes6 + 0), BYTE_U(word6, 0));
        CHECK(16, LOAD("lbu", bytes6 + 1), BYTE_U(word6, 1));
        CHECK(16, LOAD("lbu", bytes6 + 2), BYTE_U(word6, 2));
        CHECK(16, LOAD("lbu", bytes6 + 3), BYTE_U(word6, 3));

        END_OF_GROUP();

        CHECK(17, LOAD("lh", bytes6 + 0), HALF_S(word6, 0));
        CHECK(17, LOAD("lh", bytes6 + 2), HALF_S(word6, 2));

        CHECK(18, LOAD("lhu", bytes6 + 0), HALF_U(word6, 0));
        CHECK(18, LOAD("lhu", bytes6 + 2), HALF_U(word6, 2));

        END_OF_TEST();

        uint32_t far = tex[tid + 31];
        CHECK(19, LOAD("lhu", (const volatile uint8_t *)(tex + tid) + 126), HALF_U(far, 2));
    }

    END_OF_TEST();

    area[tid] = errors;
    return;
}

GPGPU_START(main)

#else

#include <stdio.h>

/* Prints the words a correct GPU leaves in the test area (offsets in words).
 * Test 6 only reads the texture and leaves no words of its own. */
int main(void)
{
    printf("errors[0..%d] = 0\n\n", CORES - 1);
    printf("lane  test1     test2     test3     test4\n");
    for (unsigned tid = 0; tid < CORES; tid++) {
        unsigned offset = tid & 3, half_offset = 2 * (tid & 1);
        unsigned w1 = (BACKGROUND & ~(0xFFu << (8 * offset))) | ((0x80 + tid) << (8 * offset));
        unsigned w3 = (BACKGROUND & ~(0xFFFFu << (8 * half_offset))) | ((0x8000 + tid) << (8 * half_offset));
        printf("%4u  %08x  %08x  %08x  %08x\n", tid, w1, 0x44332211u, w3, 0x80FF7F01u);
    }
    printf("\nshared_bytes:\n");
    for (unsigned w = 0; w < (CORES + 3) / 4; w++) {
        unsigned word = 0;
        for (unsigned k = 0; k < 4; k++)
            if (4 * w + k < CORES)  /* the last word may have fewer lanes */
                word |= (0x80 + 4 * w + k) << (8 * k);
        printf("  %08x\n", word);
    }
    printf("shared_halves:\n");
    for (unsigned w = 0; w < CORES / 2; w++)
        printf("  %08x\n", (0x8000 + 2 * w) | (0x8001u + 2 * w) << 16);
    return 0;
}

#endif