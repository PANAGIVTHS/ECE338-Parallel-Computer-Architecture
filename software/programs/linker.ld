/*
 * Linker script for the GPGPU kernels.
 *
 * Three memories, each at its own addresses:
 *
 *   IMEM  (BRAM)  instructions, a separate address space from PC 0
 *   DMEM  (BRAM)  shared memory: .shared, the per-lane stacks
 *   GMEM  (DDR)   compiler data (.rodata, .data, .bss), then program buffers
 *
 * linker_layout.ld is generated for every build (software:programs:layout)
 * from architecture.memory in the configuration and the RTL's memory map. It
 * defines the regions IMEM, DMEM, GDATA (the compiler data at GMEM_BASE) and
 * GFREE (the rest of GMEM), and the symbols __gpu_num_cores and
 * __gpu_stack_stride.
 *
 * DMEM, from byte 0:
 *
 *   __shared_start    GPGPU_SHARED variables, undefined when a block starts
 *   __gpu_stack_bottom   lane n's stack: __stack_top - n * stride downwards
 *   __stack_top       the end of DMEM
 *
 * GMEM, from GMEM_BASE:
 *
 *   __gpu_launch      the launch block: 256 bytes the runtime host writes before
 *                     every launch (software/runtime, docs/runtime-spec.md)
 *   __gmem_data_start .rodata and .data: the image the host writes at load
 *   __bss_start       .bss: zeroed when the module loads
 *   __gmem_data_end
 *   __gmem_free_base  .. __gmem_free_end: free for program buffers
 *
 * The runtime loads the data once per module, with IMEM, not before every
 * launch: globals keep their values from one launch to the next.
 *
 * Only .text and GMEM hold loadable contents. DMEM starts at address 0 like
 * IMEM, so everything placed there is NOLOAD: the linker then does not see
 * an overlap with .text.
 */
OUTPUT_ARCH(riscv)
ENTRY(_start)

INCLUDE linker_layout.ld

SECTIONS
{
    .text :
    {
        /* Put reset/entry code at PC 0 when built with -ffunction-sections. */
        KEEP(*(.text.start .text.start.*))
        KEEP(*(.text._start))
        *(.text .text.*)
    } > IMEM

    /* ---- DMEM: shared memory ------------------------------------------ */

    /* GPGPU_SHARED variables, from DMEM byte 0. They cannot have
     * initializers: the section is not loaded. GPGPU_SHARED_FIXED
     * (.shared.fixed) comes first, at GPGPU_SHARED_BASE. */
    .shared (NOLOAD) : ALIGN(16)
    {
        __shared_start = .;
        KEEP(*(.shared.fixed))
        *(.shared .shared.*)
        . = ALIGN(4);
        __shared_end = .;
    } > DMEM

    __stack_top        = ORIGIN(DMEM) + LENGTH(DMEM);
    __gpu_stack_bottom = __stack_top - __gpu_num_cores * __gpu_stack_stride;

    /* ---- GMEM: launch block, then compiler data ------------------------- */

    /* Entry, grid and parameters of a launch (gpgpu_launch_block_t). Only the
     * host writes it, so it is not part of the image. */
    .launch (NOLOAD) :
    {
        __gpu_launch = .;
        . += 256;
    } > GDATA

    .rodata : ALIGN(4)
    {
        __gmem_data_start = .;
        *(.srodata .srodata.*)
        *(.rodata .rodata.*)
    } > GDATA

    .data : ALIGN(4)
    {
        *(.sdata .sdata.*)
        *(.data .data.*)
        . = ALIGN(4);
    } > GDATA

    .bss (NOLOAD) : ALIGN(4)
    {
        __bss_start = .;
        *(.sbss .sbss.*)
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > GDATA

    __gmem_data_end  = .;
    __gmem_free_base = ORIGIN(GFREE);
    __gmem_free_end  = ORIGIN(GFREE) + LENGTH(GFREE);

    /DISCARD/ :
    {
        *(.comment)
        *(.riscv.attributes)
        *(.note .note.*)
        *(__patchable_function_entries)
    }
}

/* The regions already reject .text, .shared and compiler data that do not
 * fit; these check what the regions cannot. */
ASSERT(__shared_end <= __gpu_stack_bottom, "GPGPU DMEM overflow: GPGPU_SHARED variables collide with the per-lane stacks")
ASSERT(__gpu_launch == ORIGIN(GDATA), "GPGPU layout error: the launch block must be at GMEM_BASE")
ASSERT(__shared_start == ORIGIN(DMEM), "GPGPU layout error: .shared must start at GPGPU_SHARED_BASE, DMEM byte 0")
