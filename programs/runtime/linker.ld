ENTRY(_start)

/*
 * The GPU has separate IMEM and DMEM blocks, but the RISC-V compiler
 * still emits normal byte addresses for data accesses.  Keep the linked address
 * space within the 2048-word/8192-byte DMEM range so pointers used by lw/sw map
 * to valid hardware DMEM addresses.
 */
MEMORY
{
    RAM (rwx) : ORIGIN = 0x00000000, LENGTH = 8K
}

/* Fixed DMEM ABI used by the UART host scripts.  These are symbols, not
 * allocated storage; host code writes the actual words into DMEM before launch.
 */
PROVIDE(__gpu_args_base = 0x00000000);   /* UART DMEM word 0 */
PROVIDE(__gpu_output_base = 0x00000100); /* UART DMEM word 64 */
PROVIDE(__gpu_reserved_end = 0x00000200);
PROVIDE(__gpu_stack_stride = 0x00000080); /* 128 bytes per lane */
PROVIDE(__stack_top = ORIGIN(RAM) + LENGTH(RAM));

SECTIONS
{
    .text : {
        *(.text*)
    } > RAM

    /* Do not let compiler-allocated data collide with the host argument/output
     * ABI window at byte addresses [0x000, 0x200).  Text lives in IMEM on the
     * hardware, but data/rodata/bss pointers target DMEM.
     */
    . = MAX(., __gpu_reserved_end);

    .rodata : {
        *(.rodata*)
    } > RAM

    .data : {
        *(.data*)
    } > RAM

    .bss : {
        *(.bss*)
        *(COMMON)
    } > RAM

    PROVIDE(__end = .);
}
