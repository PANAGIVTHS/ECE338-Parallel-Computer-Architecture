/*
 * simple: every lane writes its index into one array and MY_VALUE (simple.h)
 * into another.
 *
 * The kernel takes a pointer to each array. Both arrays are GPGPU_DEVICE
 * variables in GMEM: the linker places them, and the host finds them through
 * their symbols.
 */
#include "gpgpu_device.h"
#include "gpgpu_types.h"
#include "simple.h"

GPGPU_DEVICE int indexes[GPGPU_BLOCK_SIZE];
GPGPU_DEVICE int tens[GPGPU_BLOCK_SIZE];

GPGPU_GLOBAL void simple(int *indexes_array, int *ten_array)
{
    unsigned int tid = gpgpu_thread_idx();

    /* Every lane writes its index */
    indexes_array[tid] = (int)tid;

    /* Every lane writes MY_VALUE at its index */
    int x = MY_VALUE;
    ten_array[tid] = x;
}
