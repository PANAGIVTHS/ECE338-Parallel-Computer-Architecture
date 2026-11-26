/*
 * subword: the host program. Fills test 6's DDR words with bytes and halves
 * of both signs, launches the kernel with and without test 6, and prints the
 * failed checks of every lane (the error bits in subword.c).
 */
#include "gpgpu.h"
#include "subword_kernels.h"

#define LANES GPGPU_BLOCK_SIZE

static const char *const checks[20] = {
    "test 1: SB changed more than its byte", "test 1: LBU did not read the stored byte back",
    "test 2: four SBs did not build 0x44332211", "test 2: LBU read a wrong byte", "test 2: LHU read a wrong half",
    "test 3: SH changed more than its half", "test 3: LH did not sign-extend the stored half",
    "test 4: LB sign extension wrong", "test 4: LBU zero extension wrong", "test 4: LH sign extension wrong",
    "test 4: LHU zero extension wrong", "test 5: own byte lost in the shared word",
    "test 5: neighbour's byte lost in the shared word", "test 5: shared halfword word wrong",
    "test 5: neighbour's halfword lost", "test 6: DDR LB differs from the byte of the word",
    "test 6: DDR LBU differs from the byte of the word", "test 6: DDR LH differs from the half of the word",
    "test 6: DDR LHU differs from the half of the word", "test 6: DDR LHU wrong where lanes span two bursts",
};

/* One launch; the number of lanes with an error bit. */
static int run(const char *what, const volatile uint32_t *ddr)
{
    uint32_t errors[LANES];
    int failed = 0;

    GPGPU_CHECK(gpgpu_launch(subword, gpgpu_dim3(1), gpgpu_symbol_address(subword_sym_lane_errors), ddr));
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(errors, subword_sym_lane_errors, sizeof errors, 0));
    for (unsigned int lane = 0; lane < LANES; lane++) {
        if (errors[lane] == 0)
            continue;
        failed++;
        gpgpu_printf("  lane %u: errors 0x%05x\n", lane, (unsigned)errors[lane]);
        for (unsigned int bit = 0; bit < 20; bit++)
            if (errors[lane] & (1u << bit))
                gpgpu_printf("    bit %u, %s\n", bit, checks[bit]);
    }
    gpgpu_printf("%s: %d of %u lanes failed\n", what, failed, LANES);
    return failed;
}

int gpgpu_main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    uint32_t words[SUBWORD_DDR_WORDS];

    /* Every byte and half takes a sign bit in turn. */
    for (unsigned int i = 0; i < SUBWORD_DDR_WORDS; i++)
        words[i] = (i * 0x9E3779B9u) ^ (i & 1 ? 0x80008080u : 0x00800000u);
    GPGPU_CHECK(gpgpu_memcpy_to_symbol(subword_sym_ddr_words, words, sizeof words, 0));

    int failed = run("shared memory, tests 1-5", NULL);
    failed += run("shared memory and DDR, tests 1-6", gpgpu_symbol_address(subword_sym_ddr_words));
    gpgpu_printf("%s\n", failed ? "FAIL" : "PASS");
    return failed ? 1 : 0;
}
