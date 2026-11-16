/*
 * DOOM's system layer (replaces doomgeneric's i_system.c, which wants a
 * desktop: malloc for the heap, exit(), a dialog box for errors).
 *
 * The one thing that matters here is I_ZoneBase: DOOM's heap goes into
 * GMEM, because wall textures made of several patches are built in that
 * heap and the GPU reads them there.
 */

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gp.h"

#include "config.h"
#include "doomtype.h"
#include "i_system.h"
#include "m_argv.h"
#include "m_misc.h"

/* The heap in MiB: the game's manifest sets it; -mb overrides it. */
#ifndef DOOM_ZONE_MB
#define DOOM_ZONE_MB 16
#endif

typedef struct exit_entry_s {
    atexit_func_t function;
    boolean run_on_error;
    struct exit_entry_s *next;
} exit_entry_t;

static exit_entry_t *exit_functions;

void I_AtExit(atexit_func_t function, boolean run_on_error)
{
    exit_entry_t *entry = malloc(sizeof(*entry));

    if (entry == NULL)
        gp_fatal("I_AtExit: out of memory");
    *entry = (exit_entry_t){ function, run_on_error, exit_functions };
    exit_functions = entry;
}

static void run_exit_functions(boolean after_error)
{
    for (exit_entry_t *entry = exit_functions; entry != NULL; entry = entry->next)
        if (!after_error || entry->run_on_error)
            entry->function();
}

byte *I_ZoneBase(int *size)
{
    int megabytes = DOOM_ZONE_MB;
    int parameter = M_CheckParmWithArgs("-mb", 1);

    if (parameter > 0)
        megabytes = atoi(myargv[parameter + 1]);
    *size = megabytes * 1024 * 1024;

    byte *zone = gp_gmem_alloc((size_t)*size);

    gp_log("doom: %d MiB heap in GMEM at %p\r\n", megabytes, (void *)zone);
    return zone;
}

void I_Quit(void)
{
    run_exit_functions(false);
    gp_exit(0);
}

void I_Error(char *error, ...)
{
    static boolean already_quitting;
    char message[512];
    va_list arguments;

    va_start(arguments, error);
    M_vsnprintf(message, sizeof(message), error, arguments);
    va_end(arguments);

    if (!already_quitting) { /* an exit function may fail too */
        already_quitting = true;
        run_exit_functions(true);
    }
    gp_fatal("%s", message);
}

void I_Tactile(int on, int off, int total)
{
    (void)on;
    (void)off;
    (void)total;
}

boolean I_ConsoleStdout(void)
{
    return false;
}

void I_PrintBanner(char *text)
{
    int spaces = 35 - (int)(strlen(text) / 2);

    for (int i = 0; i < spaces; i++)
        putchar(' ');
    puts(text);
}

void I_PrintDivider(void)
{
    for (int i = 0; i < 75; i++)
        putchar('=');
    putchar('\n');
}

void I_PrintStartupBanner(char *description)
{
    I_PrintDivider();
    I_PrintBanner(description);
    I_PrintDivider();
    printf(" " PACKAGE_NAME " is free software, covered by the GNU General Public\n"
           " License. There is NO warranty; not even for MERCHANTABILITY or FITNESS\n"
           " FOR A PARTICULAR PURPOSE. See the source for more information.\n");
    I_PrintDivider();
}

/*
 * DOOM read through a null pointer in one place, and maps (and demos) came
 * to depend on what MS-DOS kept at address 0. These are the bytes of DOS
 * 6.22, the default of every port.
 */
boolean I_GetMemoryValue(unsigned int offset, void *value, int size)
{
    static const unsigned char dos622[10] = { 0x57, 0x92, 0x19, 0x00, 0xF4, 0x06, 0x70, 0x00, 0x16, 0x00 };

    if ((size != 1 && size != 2 && size != 4) || offset + (unsigned int)size > sizeof(dos622))
        return false;

    unsigned int word = 0;

    for (int i = size - 1; i >= 0; i--)
        word = (word << 8) | dos622[offset + (unsigned int)i];
    if (size == 1)
        *(unsigned char *)value = (unsigned char)word;
    else if (size == 2)
        *(unsigned short *)value = (unsigned short)word;
    else
        *(unsigned int *)value = word;
    return true;
}
