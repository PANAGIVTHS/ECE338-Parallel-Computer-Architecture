#ifndef GP_H
#define GP_H

/*
 * The game platform: what a game on the ARM uses instead of the board.
 *
 * A game is the logic of a program running on the ARM CPU and its drawing
 * running on the GPU. This header is everything the game sees of the
 * machine: time, a console, key presses, memory the GPU can reach, the
 * GPU's kernel and the display. Two implementations exist:
 *
 *   xc7z020/  the board: PS timer and UART, the GPU driver, the VDMA.
 *   sim/      a PC: the kernel runs natively lane by lane and frames are
 *             written as pictures, so a game is developed without a board.
 *
 * A game defines one gp_game_t named gp_game; the platform owns main().
 *
 * Shared between the two, in this directory: the GMEM allocator, the input
 * queue and the UART key decoder, and the placement of the picture on the
 * display.
 */

#include <stddef.h>
#include <stdint.h>
#include "gpgpu_blit.h"

/* ---- The game --------------------------------------------------------- */

typedef struct {
    const char *name;
    /* Once, after the platform is up. argv comes from the game's manifest
     * and the configuration (software.games.settings.<game>.args). */
    void (*init)(int argc, char **argv);
    /* Forever after: one frame of the game. */
    void (*tick)(void);
} gp_game_t;

extern const gp_game_t gp_game;

/* ---- Time and console ------------------------------------------------- */

uint32_t gp_time_ms(void);
void gp_sleep_ms(uint32_t ms);

/* printf to the console (the UART on the board). */
void gp_log(const char *format, ...) __attribute__((format(printf, 1, 2)));

/* Print the message and stop the game: the board halts, the simulation exits. */
void gp_fatal(const char *format, ...) __attribute__((format(printf, 1, 2), noreturn));

/* The game is over (its own Quit): the board halts, the simulation exits. */
void gp_exit(int status) __attribute__((noreturn));

/* ---- Memory the GPU can reach ----------------------------------------- */

/*
 * GMEM is the part of DDR the GPU reads and writes. The ARM sees it at the
 * same addresses, so a pointer into it is also the address the GPU uses:
 * gp_gpu_address(). Everything a kernel reads must be allocated here.
 *
 * The GPU goes around the ARM's caches. Before a kernel reads what the game
 * wrote, and before the game reads what a kernel wrote, the game calls
 * gp_gmem_sync() on that memory. It is safe on memory nobody changed.
 */
void *gp_gmem_alloc(size_t bytes);              /* 128-byte aligned, never freed; fatal when GMEM is full */
int gp_gmem_contains(const void *pointer, size_t bytes);
void gp_gmem_sync(const void *pointer, size_t bytes);

static inline uint32_t gp_gpu_address(const void *pointer)
{
    return (uint32_t)(uintptr_t)pointer;
}

/* ---- The GPU ---------------------------------------------------------- */

unsigned int gp_gpu_lanes(void);

/* Word `index` of GPGPU_ARGS, as the kernel reads it. */
void gp_gpu_set_arg(unsigned int index, uint32_t value);

/* Run the game's kernel once and wait for it. A kernel that faults is fatal:
 * the fault report is printed first. */
void gp_gpu_run(void);

/* ---- The display ------------------------------------------------------ */

/*
 * Two framebuffers of 0x00RRGGBB words. A kernel draws into the hidden one,
 * then gp_display_flip() shows it. gp_present_setup() fills the descriptor
 * that gpgpu_blit() (software/programs/gpgpu_blit.h) needs to put an indexed
 * picture in the middle of the display at the configured size
 * (software.games.platform.output); gp_present_target() points it at the
 * hidden framebuffer, once per frame.
 */
void gp_present_setup(gpgpu_blit_t *blit, const uint8_t *picture, unsigned int width, unsigned int height,
                      const uint32_t *palette);
void gp_present_target(gpgpu_blit_t *blit);
void gp_display_flip(void);

/* ---- Input ------------------------------------------------------------ */

/* Printable keys are their ASCII code, in lower case. */
enum {
    GP_KEY_ENTER = '\r',
    GP_KEY_ESCAPE = 27,
    GP_KEY_TAB = '\t',
    GP_KEY_BACKSPACE = 127,
    GP_KEY_UP = 0x100,
    GP_KEY_DOWN,
    GP_KEY_LEFT,
    GP_KEY_RIGHT,
    GP_KEY_HOME,
    GP_KEY_END,
    GP_KEY_PAGE_UP,
    GP_KEY_PAGE_DOWN,
    GP_KEY_INSERT,
    GP_KEY_DELETE,
    GP_KEY_F1, /* F1..F12 follow in order */
    GP_KEY_F12 = GP_KEY_F1 + 11,
    GP_KEY_SHIFT,
    GP_KEY_CTRL,
    GP_KEY_ALT,
};

typedef struct {
    uint16_t key;
    uint8_t pressed; /* 1 press, 0 release */
} gp_key_event_t;

/* The next key event, if any: returns 1 and fills *event, or 0. */
int gp_input_poll(gp_key_event_t *event);

/*
 * An input device. The UART decoder (gp_input_uart.c) is one; a keyboard is
 * another file with its own gp_input_source_t, added to the platform's list
 * in gp_input.c. `poll` is called until it returns 0.
 */
typedef struct {
    const char *name;
    void (*init)(void);
    int (*poll)(gp_key_event_t *event);
} gp_input_source_t;

extern const gp_input_source_t gp_input_uart;

/* ---- Files built into the game ---------------------------------------- */

/* A file the build linked into the game (software.games.settings.<game>.assets),
 * under the name the game's manifest gives it. */
typedef struct {
    const char *name;
    const uint8_t *data;
    size_t size;
} gp_asset_t;

const gp_asset_t *gp_asset_find(const char *name);

#endif /* GP_H */
