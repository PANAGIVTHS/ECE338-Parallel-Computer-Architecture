/*
 * The monitor's program loader (gpgpu_loader.h).
 *
 * A loaded program is an ordinary standalone application linked at
 * GPGPU_PROGRAM_BASE: its own vectors, startup code (boot.S), MMU table,
 * stacks and heap. Two things make running it from the monitor safe:
 *
 * - Before the jump, the caches are cleaned. The program's boot.S invalidates
 *   L1 and L2 without writing them back, which would lose the program's own
 *   code and data, and the monitor's saved context.
 * - On return, the monitor restores what boot.S changed: the vector base
 *   (VBAR), the translation table (TTBR0) and the stack of every mode.
 */
#include "gpgpu_loader.h"

#include <string.h>

#include "gpgpu_boot.h"
#include "gpgpu_driver.h"
#include "xil_cache.h"
#include "xil_printf.h"

extern char inbyte(void);

static u32 loaded_entry; /* 0: nothing loaded */

/* ---- Entering and leaving a program ------------------------------------ */

/* The monitor's stack pointer while a program runs; used by the assembly below. */
u32 gpgpu_monitor_sp_ __attribute__((used));

/* Save the monitor's registers on its stack, clean the caches, invalidate the
 * instruction cache and the branch predictor, and jump to `entry`. Returns
 * the program's status, through gpgpu_monitor_resume_(). */
__attribute__((naked, noinline)) static int monitor_call(__attribute__((unused)) u32 entry)
{
    __asm__ volatile(
        "push   {r4-r12, lr}\n"          /* callee-saved, and 8-byte alignment */
        "vpush  {d8-d15}\n"              /* callee-saved VFP registers (hard float) */
        "mov    r4, r0\n"
        "ldr    r1, =gpgpu_monitor_sp_\n"
        "str    sp, [r1]\n"
        "bl     Xil_DCacheFlush\n"       /* L1 and L2, after the saves above */
        "bl     Xil_ICacheInvalidate\n"
        "mov    r0, #0\n"
        "mcr    p15, 0, r0, c7, c5, 6\n" /* BPIALL */
        "dsb\n"
        "isb\n"
        "bx     r4\n");
}

/* Where a program returns to, with its status in r0, in SYS mode. Restores
 * the monitor's vectors, translation table and mode stacks, then returns from
 * monitor_call(). */
__attribute__((naked, noreturn, used)) void gpgpu_monitor_resume_(int status)
{
    (void)status;
    __asm__ volatile(
        "cpsid  if\n"
        "mov    r4, r0\n"
        "ldr    r0, =_vector_table\n"
        "mcr    p15, 0, r0, c12, c0, 0\n" /* VBAR */
        "ldr    r0, =MMUTable\n"
        "orr    r0, r0, #0x5B\n"          /* as boot.S: outer cacheable, write-back */
        "mcr    p15, 0, r0, c2, c0, 0\n"  /* TTBR0 */
        "mov    r0, #0\n"
        "mcr    p15, 0, r0, c8, c7, 0\n"  /* TLBIALL */
        "mcr    p15, 0, r0, c7, c5, 0\n"  /* ICIALLU */
        "mcr    p15, 0, r0, c7, c5, 6\n"  /* BPIALL */
        "dsb\n"
        "isb\n"
        "cps    #0x12\n"                  /* IRQ */
        "ldr    sp, =__irq_stack\n"
        "cps    #0x13\n"                  /* SVC */
        "ldr    sp, =__supervisor_stack\n"
        "cps    #0x17\n"                  /* ABT */
        "ldr    sp, =__abort_stack\n"
        "cps    #0x11\n"                  /* FIQ */
        "ldr    sp, =__fiq_stack\n"
        "cps    #0x1b\n"                  /* UND */
        "ldr    sp, =__undef_stack\n"
        "cps    #0x1f\n"                  /* SYS: where main() runs */
        "ldr    r0, =gpgpu_monitor_sp_\n"
        "ldr    sp, [r0]\n"
        "mov    r0, r4\n"
        "vpop   {d8-d15}\n"
        "pop    {r4-r12, pc}\n");
}

/* ---- Loading ----------------------------------------------------------- */

static u32 read_word(void)
{
    u32 value = 0;
    for (u32 i = 0; i < 4U; i++)
        value |= ((u32)inbyte() & 0xFFU) << (8U * i);
    return value;
}

/* CRC-32 (IEEE 802.3, as Python's zlib.crc32), one byte at a time. */
static u32 crc32_update(u32 crc, u8 byte)
{
    crc ^= byte;
    for (u32 bit = 0; bit < 8U; bit++)
        crc = (crc >> 1) ^ (0xEDB88320U & (0U - (crc & 1U)));
    return crc;
}

static int parse_hex(const char *text, u32 *value)
{
    u32 result = 0;
    if (text == NULL || *text == '\0')
        return -1;
    if (text[0] == '0' && (text[1] == 'x' || text[1] == 'X'))
        text += 2;
    for (; *text; text++) {
        char c = *text;
        u32 digit = c >= '0' && c <= '9' ? (u32)(c - '0') :
                    c >= 'a' && c <= 'f' ? (u32)(c - 'a' + 10) :
                    c >= 'A' && c <= 'F' ? (u32)(c - 'A' + 10) : 16U;
        if (digit > 15U)
            return -1;
        result = (result << 4) | digit;
    }
    *value = result;
    return 0;
}

static int in_program(u32 address, u32 size)
{
    return address >= GPGPU_PROGRAM_BASE && address <= GPGPU_PROGRAM_END && size <= GPGPU_PROGRAM_END - address;
}

int gpgpu_loader_load(const char *entry_text, const char *segments_text)
{
    u32 entry, segments;

    if (parse_hex(entry_text, &entry) != 0 || parse_hex(segments_text, &segments) != 0 || segments == 0U) {
        xil_printf("ERROR: usage: load <entry_hex> <segments_hex>\r\n");
        return -1;
    }
    if (!in_program(entry, 4U)) {
        xil_printf("ERROR: entry 0x%08x is outside the program region 0x%08x-0x%08x\r\n", entry,
                   GPGPU_PROGRAM_BASE, GPGPU_PROGRAM_END);
        return -1;
    }
    loaded_entry = 0U;
    xil_printf("READY_LOAD\r\n");
    for (u32 n = 0; n < segments; n++) {
        const u32 address = read_word(), size = read_word(), crc = read_word();
        if (size == 0U || !in_program(address, size)) {
            xil_printf("ERROR: segment %u at 0x%08x, %u bytes, is outside the program region 0x%08x-0x%08x\r\n",
                       n, address, size, GPGPU_PROGRAM_BASE, GPGPU_PROGRAM_END);
            return -1;
        }
        xil_printf("SEGMENT_READY\r\n");
        u8 *bytes = (u8 *)(UINTPTR)address;
        u32 sum = 0xFFFFFFFFU;
        for (u32 i = 0; i < size; i++) {
            bytes[i] = (u8)inbyte();
            sum = crc32_update(sum, bytes[i]);
        }
        sum = ~sum;
        if (sum != crc) {
            xil_printf("ERROR: segment %u at 0x%08x: CRC-32 0x%08x, expected 0x%08x\r\n", n, address, sum, crc);
            return -1;
        }
        xil_printf("SEGMENT_OK\r\n");
    }
    loaded_entry = entry;
    xil_printf("LOAD_COMPLETE\r\n");
    return 0;
}

/* ---- Running ----------------------------------------------------------- */

int gpgpu_loader_run(char *line)
{
    volatile gpgpu_boot_record_t *boot = GPGPU_BOOT_RECORD;

    if (loaded_entry == 0U) {
        xil_printf("ERROR: no program is loaded: use `load` first\r\n");
        return -1;
    }

    /* The arguments: tokens separated by spaces, each copied with its '\0'. */
    u32 argc = 0, used = 0;
    for (char *token = strtok(line, " \t"); token != NULL; token = strtok(NULL, " \t")) {
        u32 length = (u32)strlen(token) + 1U;
        if (argc == GPGPU_BOOT_MAX_ARGS || used + length > GPGPU_BOOT_ARGS_BYTES) {
            xil_printf("ERROR: at most %u arguments and %u bytes\r\n", GPGPU_BOOT_MAX_ARGS, GPGPU_BOOT_ARGS_BYTES);
            return -1;
        }
        for (u32 i = 0; i < length; i++)
            boot->args[used + i] = token[i];
        used += length;
        argc++;
    }
    if (argc == 0U) {
        xil_printf("ERROR: usage: run <name> [arguments]\r\n");
        return -1;
    }
    boot->argc = argc;
    boot->status = 0;
    boot->resume = (u32)(UINTPTR)gpgpu_monitor_resume_;
    boot->magic = GPGPU_BOOT_MAGIC;

    xil_printf("RUN_START\r\n");
    gpgpu_shutdown();
    int status = monitor_call(loaded_entry);

    /* Back in the monitor: the interrupt controller as the program left it. */
    boot->magic = 0U;
    if (gpgpu_init() != GPGPU_OK)
        xil_printf("ERROR: GPGPU initialization after the program failed\r\n");
    xil_printf("RUN_RETURN %d\r\n", status);
    return status;
}
