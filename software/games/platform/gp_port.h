#ifndef GP_PORT_H
#define GP_PORT_H

/*
 * What an implementation of the platform (xc7z020/, sim/) gives the shared
 * code in this directory, besides the functions of gp.h it implements
 * itself: gp_time_ms, gp_sleep_ms, gp_gmem_sync, gp_gpu_lanes,
 * gp_gpu_set_arg and gp_display_flip. It also has main(), which calls
 * gp_main() once it stands on a stack large enough for a game.
 *
 * The build generates three files per game next to these (see
 * `gpgpu software games:<game>:generate`):
 *   gp_config.h  the settings below, from the manifest and the configuration
 *   gp_kernel.c  the kernel's IMEM image (gp_kernel_*)
 *   gp_assets.c  the files linked into the game (gp_assets)
 */

#include "gp.h"
#include "gp_config.h"

/* The platform's part of main(): never returns. */
void gp_main(void) __attribute__((noreturn));

/* Console, timer, GPU and display, in that order. The GPU is left idle with
 * the game's kernel loaded; both framebuffers are black. */
void gp_port_init(void);

/* The game's arguments: `configured` (GP_GAME_ARGV, NULL-terminated), or a
 * vector that extends it. The simulation appends its own command line. */
char **gp_port_arguments(char **configured);

/* One byte from the console, or -1 when none is waiting. Never blocks. */
int gp_port_console_read(void);

/* Stop for good. */
void gp_port_halt(int status) __attribute__((noreturn));

/* GMEM as the ARM sees it. */
void gp_port_gmem(uint8_t **base, size_t *bytes);

/* Bytes of GMEM handed out so far, from its base (shared code). */
size_t gp_gmem_used(void);

/* Run the loaded kernel and wait. Returns 0, or non-zero after printing why
 * the GPU did not finish (a fault report). */
int gp_port_gpu_run(void);

/* The display: its size in pixels, the bytes from one row to the next, and
 * the GPU address of the framebuffer that is not being shown. */
void gp_port_display(unsigned int *width, unsigned int *height, uint32_t *stride);
uint32_t gp_port_display_hidden(void);

/* The kernel image of the game (gp_kernel.c). */
extern const uint32_t gp_kernel_image[];
extern const unsigned int gp_kernel_words;
extern const unsigned int gp_kernel_args_word; /* DMEM word of GPGPU_ARGS[0] */
extern const unsigned int gp_kernel_args;      /* words GPGPU_ARGS holds */
extern const unsigned int gp_kernel_lanes;     /* the lanes it was compiled for (architecture.num_cores) */

/* The files of the game (gp_assets.c). A file's size is end - start. */
typedef struct {
    const char *name;
    const uint8_t *start;
    const uint8_t *end;
} gp_asset_file_t;

extern const gp_asset_file_t gp_assets[];
extern const unsigned int gp_asset_count;

/* Shared code the implementations call. */
void gp_input_init(void);

#endif /* GP_PORT_H */
