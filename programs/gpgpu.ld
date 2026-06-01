/*
 * Linker script for the GPGPU.
 *
 * The RTL has separate instruction and data memories, but the RISC-V cores still
 * uses ordinary byte addresses for loads/stores. Host-side DMEM commands use
 * word offsets, so byte address A corresponds to host DMEM word A / 4.
 */
OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
    /* 2048 instructions / 2048 data words in src/constants.vh. */
    IMEM (rx)  : ORIGIN = 0x00000000, LENGTH = 8K
    DMEM (rw)  : ORIGIN = 0x00000000, LENGTH = 8K
}

/* Host/kernel ABI windows, expressed as RISC-V byte addresses. */
__gpu_args_base      = 0x00000040; /* host DMEM word 16 */
__gpu_args_end       = 0x00000050; /* words 16..19 */

/* Per-lane spill stacks: 32 lanes * 64 bytes = DMEM[1536..2047]. */
__gpu_num_cores      = 32;
__gpu_stack_stride   = 64;
__gpu_stack_bottom   = 0x00001800;
__stack_top          = 0x00002000;

/*
 * Compiler-owned data.
 *
 * Starts at 0x1000, available for .rodata/.sdata/.data/.bss.
 */
__gpu_data_base      = 0x00001000;
__gpu_data_limit     = __gpu_stack_bottom;

SECTIONS
{
    . = ORIGIN(IMEM);

    .text :
    {
        /* Put reset/entry code at PC 0 when built with -ffunction-sections. */
        KEEP(*(.text.start .text.start.*))
        KEEP(*(.text._start))
        *(.text .text.*)
    } > IMEM

    /*
     * Move the DMEM location counter to the compiler-owned data region.
     * This keeps compiler-generated data away from the host argument window.
     */
    . = __gpu_data_base;
    . = ALIGN(4);
    PROVIDE(__data_start = .);

    .rodata ALIGN(4) :
    {
        *(.srodata .srodata.*)
        *(.rodata .rodata.*)
    } > DMEM

    .sdata ALIGN(4) :
    {
        *(.sdata .sdata.*)
    } > DMEM

    .data ALIGN(4) :
    {
        *(.data .data.*)
    } > DMEM

    .bss ALIGN(4) (NOLOAD) :
    {
        PROVIDE(__bss_start = .);
        *(.sbss .sbss.*)
        *(.bss .bss.*)
        *(COMMON)
        . = ALIGN(4);
        PROVIDE(__bss_end = .);
    } > DMEM

    PROVIDE(__data_end = .);

    /DISCARD/ :
    {
        *(.comment)
        *(.riscv.attributes)
        *(.note .note.*)
        *(__patchable_function_entries)
    }
}

ASSERT(SIZEOF(.text) <= LENGTH(IMEM), "GPGPU IMEM overflow: program has more than 2048 instructions/8 KiB");
ASSERT(__data_end <= __gpu_data_limit, "GPGPU DMEM overflow: compiler data/bss collides with per-lane stack window");
ASSERT(__gpu_args_end <= __gpu_data_base, "GPGPU ABI error: data region collides with argument window");
