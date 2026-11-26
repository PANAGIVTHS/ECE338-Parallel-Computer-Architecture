/*
 * differences: adjacent differences, diff[i] = data[i + 1] - data[i].
 *
 * Thread i of the grid computes diff[i]: launch it over n / 32 blocks for
 * n differences (data has n + 1 values). Each load and store is 32
 * neighbouring words, one DDR burst.
 */
#include "gpgpu_device.h"
#include "differences.h"

GPGPU_DEVICE int input[DIFFERENCES_MAX + 1];
GPGPU_DEVICE int output[DIFFERENCES_MAX];

GPGPU_GLOBAL void differences(const int *data, int *diff)
{
    unsigned int i = gpgpu_block_idx_x() * gpgpu_block_dim() + gpgpu_thread_idx();

    diff[i] = data[i + 1] - data[i];
}
