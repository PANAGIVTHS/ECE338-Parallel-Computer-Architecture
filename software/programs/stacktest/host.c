/*
 * stacktest: the host program. The stack pointers of neighbouring lanes are
 * GPGPU_STACK_STRIDE bytes apart, inside shared memory, and a value each lane
 * kept on its stack came back unchanged.
 */
#include "gpgpu.h"
#include "stacktest_kernels.h"

#define LANES GPGPU_BLOCK_SIZE

int gpgpu_main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    const unsigned int seed = 1000;
    unsigned int pointers[LANES], values[LANES];
    gpgpu_properties_t properties;
    int failures = 0;

    GPGPU_CHECK(gpgpu_get_properties(&properties));
    GPGPU_CHECK(gpgpu_launch(stacktest, gpgpu_dim3(1), gpgpu_symbol_address(stacktest_sym_stack_pointers),
                             gpgpu_symbol_address(stacktest_sym_stack_values), seed));
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(pointers, stacktest_sym_stack_pointers, sizeof pointers, 0));
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(values, stacktest_sym_stack_values, sizeof values, 0));

    gpgpu_printf("lane 0: sp 0x%04x, lane %u: sp 0x%04x\n", pointers[0], LANES - 1, pointers[LANES - 1]);
    for (unsigned int lane = 0; lane < LANES; lane++) {
        if (pointers[lane] >= properties.shared_bytes) {
            gpgpu_printf("  lane %u: sp 0x%x is outside shared memory\n", lane, pointers[lane]);
            failures++;
        }
        if (lane > 0 && pointers[lane - 1] - pointers[lane] != GPGPU_STACK_STRIDE) {
            gpgpu_printf("  lanes %u and %u: stacks 0x%x apart, expected 0x%x\n", lane - 1, lane,
                         pointers[lane - 1] - pointers[lane], GPGPU_STACK_STRIDE);
            failures++;
        }
        if (values[lane] != seed + lane) {
            gpgpu_printf("  lane %u: kept %u on its stack, got %u back\n", lane, seed + lane, values[lane]);
            failures++;
        }
    }
    gpgpu_printf("%s\n", failures ? "FAIL" : "PASS");
    return failures ? 1 : 0;
}
