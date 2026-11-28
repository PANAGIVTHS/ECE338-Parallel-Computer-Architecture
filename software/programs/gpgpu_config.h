#ifndef GPGPU_CONFIG_H
#define GPGPU_CONFIG_H

/* The gpgpu CLI supplies these from the configuration for every build of a
 * program (kernels, simulator, A9): GPGPU_NUM_CORES from architecture.num_cores, the rest from
 * architecture.memory. The fallbacks keep programs directly compilable; they
 * match the default profile. */
#ifndef GPGPU_NUM_CORES
#define GPGPU_NUM_CORES 32u
#endif

/* Bytes of each lane's stack, a power of two: 1 << GPGPU_STACK_SHIFT. */
#ifndef GPGPU_STACK_STRIDE
#define GPGPU_STACK_STRIDE 128
#endif
#ifndef GPGPU_STACK_SHIFT
#define GPGPU_STACK_SHIFT 7
#endif

#define GPGPU_XSTR(x) #x
#define GPGPU_STR(x) GPGPU_XSTR(x)

#endif /* GPGPU_CONFIG_H */
