#include "../gpgpu_runtime.h"

#define CORES GPGPU_NUM_CORES

#ifdef __riscv

#define FB0_BASE   0x18000000u
#define FB_WIDTH   1080
#define FB_HEIGHT  720
#define BAR_W      (FB_WIDTH / 3)   /* 360 pixels per bar */

/* XRGB8888: 0x00RRGGBB */
#define RED        0x00FF0000u
#define GREEN      0x0000FF00u
#define BLUE       0x000000FFu

void main(void)
{
    unsigned int tid = gpgpu_thread_id();

    volatile unsigned int *fb = (volatile unsigned int *)(uintptr_t)FB0_BASE;

    for (int i = 0; i < 320; i++) {
        for (int j = 0; j < 720; j++) {
            FB0_BASE[i][j] = RED;
        }
    }

    for (int i = 320; i < 640; i++) {
        for (int j = 0; j < 720; j++) {
            FB0_BASE[i][j] = GREEN;
        }
    }

    for (int i = 640; i < 960; i++) {
        for (int j = 0; j < 720; j++) {
            FB0_BASE[i][j] = BLUE;
        }
    }

    return;
}

GPGPU_START(main)

#else

#endif