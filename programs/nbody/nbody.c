#define NUM_BODIES 3
#define G_CONST 10
#define DT 1
#define STEPS 1000


static inline __attribute__((always_inline)) int int_div(int numerator, int denominator) {
    if (denominator == 0)
        return 0;

    int sign = 1;
    unsigned int unum, uden;

    if (numerator < 0) {
        sign = -sign;
        unum = (unsigned int)(-numerator);
    } else {
        unum = (unsigned int)numerator;
    }

    if (denominator < 0) {
        sign = -sign;
        uden = (unsigned int)(-denominator);
    } else {
        uden = (unsigned int)denominator;
    }

    unsigned int quotient = 0;
    unsigned int remainder = 0;

    for (int i = 31; i >= 0; i--) {
        remainder = remainder << 1;
        remainder = remainder | ((unum >> i) & 1U); 

        if (remainder >= uden) {
            remainder = remainder - uden;
            quotient = quotient | (1U << i);
        }
    }
    
    if (sign == -1)
        return -(int)quotient;

    return (int)quotient;
}

static inline __attribute__((always_inline)) int int_sqrt(int n) {
    if (n <= 0)
        return 0;

    int x = n;
    int y = (x + int_div(n, x)) >> 1;

    while (y < x) {
        x = y;
        y = (x + int_div(n, x)) >> 1;
    }

    return x;
}

#ifdef __riscv
int _start() {
#else
#include <stdio.h>
int main() {
#endif
    int x[NUM_BODIES]    = {100, 150, 50};
    int y[NUM_BODIES]    = {100, 150, 50};
    int vx[NUM_BODIES]   = {  0,   0,  -5};
    int vy[NUM_BODIES]   = {  0,   5,   0};
    int mass[NUM_BODIES] = { 10,  10,  10};

    int i, j, step;

    #ifdef __riscv
    #else
    printf("step,x0,y0,x1,y1,x2,y2\n");
    #endif

    for (step = 0; step < STEPS; step++) {

        for (i = 0; i < NUM_BODIES; i++) {
            int fx = 0;
            int fy = 0;

            for (j = 0; j < NUM_BODIES; j++) {
                if (i == j)
                    continue;

                int dx = x[j] - x[i];
                int dy = y[j] - y[i];

                if (dx > 1000 || dx < -1000 || dy > 1000 || dy < -1000) {
                    continue;
                }

                int dist_sq = (dx * dx) + (dy * dy);
                if (dist_sq == 0)
                    continue;

                int dist = int_sqrt(dist_sq);
                if (dist == 0)
                    continue;

                unsigned int r_cubed = dist_sq * dist;

                unsigned int r_cubed_scaled = r_cubed >> 6;
                if (r_cubed_scaled == 0)
                    r_cubed_scaled = 1;

                int force_mag = G_CONST * mass[i] * mass[j];

                fx += int_div((force_mag * dx), (int)r_cubed_scaled);
                fy += int_div((force_mag * dy), (int)r_cubed_scaled);
            }

            vx[i] += int_div(fx, mass[i]) * DT;
            vy[i] += int_div(fy, mass[i]) * DT;
        }

        // Update the positions
        for (i = 0; i < NUM_BODIES; i++) {
            x[i] += vx[i] * DT;
            y[i] += vy[i] * DT;
        }

        #ifdef __riscv
        #else
        printf("%d", step);
        for (i = 0; i < NUM_BODIES; i++) {
            printf(",%d,%d", x[i], y[i]);
        }
        printf("\n");
        #endif
    }

    return 0;
}
