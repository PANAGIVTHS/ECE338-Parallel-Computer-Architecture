/*
 * stress: the host program. Runs every mode, or one, on the GPU and checks
 * each lane's result against stress_lane() run here.
 *
 *   gpgpu_main([iterations [seed [mode]]])   default 1000 iterations, seed 0x9E3779B9, every mode
 */
#include <stdlib.h>

#include "gpgpu.h"
#include "stress_kernels.h"

static unsigned int buffer[DDR_BURSTS * CORES];

static const char *const names[] = {"LOOP", "ALU", "MUL", "SMEM", "DDR", "XOR", "ADD", "ROT", "XOR_INDEP",
                                    "XOR_RING", "XOR_CONST"};

/* One mode on the GPU; the number of lanes that differ from the host. */
static int run(unsigned int mode, unsigned int iterations, unsigned int seed)
{
    unsigned int got[CORES];
    int wrong = 0;

    uint32_t start = gpgpu_time_ms();
    GPGPU_CHECK(gpgpu_launch(stress, gpgpu_dim3(1), mode, iterations, seed, gpgpu_symbol_address(stress_sym_results),
                             gpgpu_framebuffer(1)));
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(got, stress_sym_results, sizeof got, 0));
    uint32_t elapsed = gpgpu_time_ms() - start;
    for (unsigned int tid = 0; tid < CORES; tid++) {
        unsigned int want = stress_lane(tid, mode, iterations, seed, buffer);
        if (got[tid] != want && wrong++ < 2)
            gpgpu_printf("  lane %u: 0x%08x, expected 0x%08x\n", tid, got[tid], want);
    }
    gpgpu_printf("%-9s %u iterations: %u ms, %s\n", names[mode & MODE_MASK], iterations, (unsigned)elapsed,
                 wrong ? "FAIL" : "ok");
    return wrong;
}

int gpgpu_main(int argc, char **argv)
{
    unsigned int iterations = argc > 1 ? (unsigned int)strtoul(argv[1], NULL, 0) : 1000u;
    unsigned int seed = argc > 2 ? (unsigned int)strtoul(argv[2], NULL, 0) : 0x9E3779B9u;
    int failures = 0;

    if (argc > 3) {
        failures += run((unsigned int)strtoul(argv[3], NULL, 0), iterations, seed);
    } else {
        for (unsigned int mode = MODE_LOOP; mode <= MODE_XOR_CONST; mode++)
            failures += run(mode, iterations, seed);
    }
    gpgpu_printf("%s\n", failures ? "FAIL" : "PASS");
    return failures ? 1 : 0;
}
