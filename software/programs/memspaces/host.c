/*
 * memspaces: the host program. It launches the kernels of memspaces.c and
 * checks every memory space against the formula there.
 *
 *   gpgpu_main([launches])    default 4 launches of memspaces
 *
 * Then it rewrites a GPGPU_CONSTANT, reloads the module (the globals return
 * to their initial values), and checks that a fault is reported once and the
 * next launch works. Status 0 when everything matches.
 */
#include <stdlib.h>
#include <string.h>

#include "gpgpu.h"
#include "memspaces_kernels.h"

static const int gain[8] = MEMSPACES_GAIN;
static const int bias[4] = MEMSPACES_BIAS;

static int failures;

static void expect(int ok, const char *what)
{
    if (!ok) {
        gpgpu_printf("FAIL: %s\n", what);
        failures++;
    }
}

/* The out[] of a launch that `calls` launches of memspaces followed since the module was loaded. */
static int expected(int op, int calls, unsigned int block, unsigned int tid, const int *offsets)
{
    int slot = calls > 0 ? (int)tid + 1 : 0;
    int neighbour = 3 * (int)((tid + 1u) & (MEMSPACES_LANES - 1u)) + (int)block;
    return memspaces_op(op, (int)tid) + gain[tid & 7u] + bias[tid & 3u] + MEMSPACES_CALL_COUNT + calls + slot +
           (4 * (int)tid + 6) + neighbour + offsets[block];
}

/* One launch of memspaces, checked. */
static void launch(int op, int calls, const int *offsets)
{
    static int results[MEMSPACES_THREADS];
    int *out = gpgpu_symbol_address(memspaces_sym_out);
    int call_count = 0;

    GPGPU_CHECK(gpgpu_launch(memspaces, gpgpu_dim3(MEMSPACES_BLOCKS), op, out));
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(results, memspaces_sym_out, sizeof results, 0));
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(&call_count, memspaces_sym_call_count, sizeof call_count, 0));

    int wrong = 0;
    for (unsigned int block = 0; block < MEMSPACES_BLOCKS; block++)
        for (unsigned int tid = 0; tid < MEMSPACES_LANES; tid++) {
            int want = expected(op, calls, block, tid, offsets);
            int got = results[block * MEMSPACES_LANES + tid];
            if (got != want && wrong++ < 4)
                gpgpu_printf("  op %d, call %d: out[%u] is %d, expected %d\n", op, calls,
                             block * MEMSPACES_LANES + tid, got, want);
        }
    expect(wrong == 0, "out[] differs from the formula");
    expect(call_count == MEMSPACES_CALL_COUNT + calls + 1, "call_count did not count the launch");
    gpgpu_printf("launch: op %d, call %d, call_count %d%s\n", op, calls, call_count, wrong ? ", wrong" : "");
}

int gpgpu_main(int argc, char **argv)
{
    int launches = argc > 1 ? atoi(argv[1]) : 4;
    const int offsets[MEMSPACES_BLOCKS] = MEMSPACES_OFFSETS;
    const int changed[MEMSPACES_BLOCKS] = {5, 20000};
    gpgpu_properties_t properties;

    GPGPU_CHECK(gpgpu_get_properties(&properties));
    gpgpu_printf("memspaces on the %s: %u lanes, %u blocks of the grid\n", properties.backend,
                 (unsigned)properties.lanes, (unsigned)MEMSPACES_BLOCKS);

    /* The globals keep their values from one launch to the next. */
    int calls = 0;
    for (; calls < launches; calls++)
        launch(calls % 7, calls, offsets);

    /* A GPGPU_CONSTANT is constant for the kernels, not for the host. */
    GPGPU_CHECK(gpgpu_memcpy_to_symbol(memspaces_sym_offsets, changed, sizeof changed, 0));
    launch(2, calls++, changed);

    /* Reloading the module restores every initial value. */
    GPGPU_CHECK(gpgpu_module_reload());
    launch(1, 0, offsets);

    /* A fault is reported by the next call that waits, once. */
    gpgpu_fault_t fault;
    GPGPU_CHECK(gpgpu_launch(memspaces_fault, gpgpu_dim3(1), gpgpu_framebuffer(0), gpgpu_symbol_address(memspaces_sym_out)));
    expect(gpgpu_synchronize() == GPGPU_ERROR_FAULT, "the faulting launch was not reported");
    GPGPU_CHECK(gpgpu_get_fault(&fault));
    expect(fault.cause == GPGPU_CAUSE_MEMORY && fault.kinds == 1u << (2 - 1) /* ST_PERMISSION */,
           "the fault is not a permission fault");
    expect(gpgpu_synchronize() == GPGPU_SUCCESS, "the fault was reported twice");
    launch(0, 1, offsets);

    /* Kernel parameters are checked before anything starts. */
    expect(gpgpu_launch(memspaces, gpgpu_dim3(0), 0, NULL) == GPGPU_ERROR_INVALID_VALUE, "an empty grid was launched");
    int on_the_stack = 0;
    expect(gpgpu_memcpy(&on_the_stack, &on_the_stack, sizeof on_the_stack, GPGPU_HOST_TO_DEVICE) ==
               GPGPU_ERROR_INVALID_VALUE, "a copy to host memory was accepted");

    gpgpu_printf("%s\n", failures ? "FAIL" : "PASS");
    return failures ? 1 : 0;
}
