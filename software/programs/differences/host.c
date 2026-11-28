/*
 * differences: the host program. Writes n + 1 values start, start + stride,
 * ... (with a square term, so the differences are not all equal), computes
 * the n adjacent differences on the GPU and checks them.
 *
 *   gpgpu_main([n [start [stride [csv]]]])   n a multiple of 32, default 1024
 *
 * With a fourth argument "csv" it also prints every difference as CSV, the
 * input of visualize.py.
 */
#include <stdlib.h>
#include <string.h>

#include "gpgpu.h"
#include "differences_kernels.h"

static int data[DIFFERENCES_MAX + 1];
static int diff[DIFFERENCES_MAX];

int gpgpu_main(int argc, char **argv)
{
    unsigned int n = argc > 1 ? (unsigned int)strtoul(argv[1], NULL, 0) : 1024u;
    int start = argc > 2 ? (int)strtol(argv[2], NULL, 0) : 0;
    int stride = argc > 3 ? (int)strtol(argv[3], NULL, 0) : 1;
    int csv = argc > 4 && strcmp(argv[4], "csv") == 0;

    if (n == 0 || n % GPGPU_BLOCK_SIZE != 0 || n > DIFFERENCES_MAX) {
        gpgpu_printf("n must be a multiple of %u up to %u\n", GPGPU_BLOCK_SIZE, DIFFERENCES_MAX);
        return 1;
    }
    for (unsigned int i = 0; i <= n; i++)
        data[i] = start + (int)i * stride + (int)((i * i) & 0xFFu);

    GPGPU_CHECK(gpgpu_memcpy_to_symbol(differences_sym_input, data, (n + 1) * sizeof data[0], 0));
    GPGPU_CHECK(gpgpu_launch(differences, gpgpu_dim3(n / GPGPU_BLOCK_SIZE), gpgpu_symbol_address(differences_sym_input),
                             gpgpu_symbol_address(differences_sym_output)));
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(diff, differences_sym_output, n * sizeof diff[0], 0));

    unsigned int wrong = 0;
    if (csv)
        gpgpu_printf("call,index,data_left,data_right,diff,expected,ok\n");
    for (unsigned int i = 0; i < n; i++) {
        int expected = data[i + 1] - data[i];
        if (csv)
            gpgpu_printf("0,%u,%d,%d,%d,%d,%d\n", i, data[i], data[i + 1], diff[i], expected, diff[i] == expected);
        if (diff[i] != expected && wrong++ < 4 && !csv)
            gpgpu_printf("  diff[%u] is %d, expected %d\n", i, diff[i], expected);
    }
    gpgpu_printf("%s: %u of %u differences wrong\n", wrong ? "FAIL" : "PASS", wrong, n);
    return wrong ? 1 : 0;
}
