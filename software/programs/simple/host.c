/*
 * simple: the host program. One launch of one block, then both arrays are
 * read back, printed and checked.
 */
#include "gpgpu.h"
#include "simple_kernels.h"
#include "gpgpu_types.h"

int gpgpu_main(int argc, char **argv)
{
    int indexes_result[GPGPU_BLOCK_SIZE];
    int tens_result[GPGPU_BLOCK_SIZE];

    // The device addresses of the arrays, for the kernel's pointer parameters
    int *indexes_array = gpgpu_symbol_address(simple_sym_indexes);
    int *ten_array = gpgpu_symbol_address(simple_sym_tens);

    // Kernel call
    GPGPU_CHECK(
        gpgpu_launch(
            simple,        // kernel
            gpgpu_dim3(1), // grid dimensions, one block of GPGPU_BLOCK_SIZE threads
            indexes_array, // kernel arg 0
            ten_array      // kernel arg 1
        )
    );

    // The first copy waits for the kernel
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(indexes_result, simple_sym_indexes, sizeof indexes_result, 0));
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(tens_result, simple_sym_tens, sizeof tens_result, 0));

    int failures = 0;

    gpgpu_printf("Indexes array: ");
    for (int i = 0; i < GPGPU_BLOCK_SIZE; i++) {
        gpgpu_printf("%d ", indexes_result[i]);
        failures += indexes_result[i] != i;
    }

    gpgpu_printf("\nTen array: ");
    for (int i = 0; i < GPGPU_BLOCK_SIZE; i++) {
        gpgpu_printf("%d ", tens_result[i]);
        failures += tens_result[i] != MY_VALUE;
    }
    gpgpu_printf("\n%s\n", failures ? "FAIL" : "PASS");

    return failures ? 1 : 0;
}
