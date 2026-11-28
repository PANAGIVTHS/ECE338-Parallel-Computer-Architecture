/*
 * memfault: the host program. One launch that works, then launches that fault,
 * each checked against the report: the cause, the memory status of the lanes,
 * which lanes, and that the next launch works again.
 */
#include <stdint.h>

#include "gpgpu.h"
#include "memfault_kernels.h"

#define LANES GPGPU_BLOCK_SIZE

/* MemorySubsystemPkg::mem_status_t */
#define ST_UNMAPPED   1u
#define ST_MISALIGNED 3u

static int failures;

static void expect(int ok, const char *what)
{
    if (!ok) {
        gpgpu_printf("  FAIL: %s\n", what);
        failures++;
    }
}

/* Launch at `target` and expect a memory fault of `status` in `lanes`. */
static void faulting(const char *what, uintptr_t target, uint32_t status, uint32_t lanes)
{
    gpgpu_fault_t fault;

    gpgpu_printf("%s: 0x%08x\n", what, (unsigned)target);
    GPGPU_CHECK(gpgpu_launch(memfault, gpgpu_dim3(1), (volatile int *)target));
    expect(gpgpu_synchronize() == GPGPU_ERROR_FAULT, "no fault reported");
    GPGPU_CHECK(gpgpu_get_fault(&fault));
    gpgpu_printf("  fault: cause %u, kinds 0x%x, lanes 0x%08x, PC 0x%x\n", (unsigned)fault.cause, (unsigned)fault.kinds,
                 (unsigned)fault.lanes, (unsigned)fault.pc);
    expect(fault.cause == GPGPU_CAUSE_MEMORY, "the cause is not a memory fault");
    expect(fault.kinds == 1u << (status - 1u), "another memory status");
    expect(fault.lanes == lanes, "other lanes");
}

int gpgpu_main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    gpgpu_properties_t properties;
    int values[LANES];

    GPGPU_CHECK(gpgpu_get_properties(&properties));
    const uintptr_t out = (uintptr_t)gpgpu_symbol_address(memfault_sym_out);
    const uintptr_t gmem_end = (uintptr_t)properties.gmem_base + properties.gmem_bytes;
    const uint32_t all = LANES == 32 ? 0xFFFFFFFFu : (1u << LANES) - 1u;

    /* Half the lanes past the end of GMEM: those lanes fault. */
    faulting("past the end of GMEM", gmem_end - 4u * (LANES / 2), ST_UNMAPPED, all & ~((1u << (LANES / 2)) - 1u));
    /* Words two bytes off: every lane. */
    faulting("misaligned", out + 2u, ST_MISALIGNED, all);

    /* The faults were reported once: this launch works. */
    gpgpu_printf("into out[]: 0x%08x\n", (unsigned)out);
    GPGPU_CHECK(gpgpu_launch(memfault, gpgpu_dim3(1), (volatile int *)out));
    GPGPU_CHECK(gpgpu_memcpy_from_symbol(values, memfault_sym_out, sizeof values, 0));
    for (int lane = 0; lane < LANES; lane++)
        expect(values[lane] == lane, "out[] does not hold the lane indices");

    gpgpu_printf("%s\n", failures ? "FAIL" : "PASS");
    return failures ? 1 : 0;
}
