/*
 * DOOM's video layer (replaces doomgeneric's i_video.c, which converts the
 * screen to RGB and scales it on the CPU).
 *
 * DOOM's screen, 320x200 with one byte per pixel, lives in GMEM. The game
 * draws its status bar, menus and text into it on the ARM; the kernel draws
 * the 3D view into it (doom_render.c) and then scales it to the display
 * through the palette, which is kept here as 256 words the GPU reads.
 */

#include <limits.h>
#include <string.h>

#include "gp.h"
#include "doom_abi.h"
#include "doom_gpu.h"

#include "doomtype.h"
#include "i_video.h"
#include "tables.h"

void I_GetEvent(void);
void I_InitInput(void);
void DG_SetWindowTitle(const char *title);

_Static_assert(SCREENWIDTH == DOOM_SURFACE_WIDTH && SCREENHEIGHT == DOOM_SURFACE_HEIGHT,
               "the kernel draws DOOM's 320x200 screen");

byte *I_VideoBuffer = NULL;

/* What the rest of DOOM reads of the video layer's state. */
boolean screensaver_mode = false;
boolean screenvisible;
int usegamma = 0;
int usemouse = 0;
float mouse_acceleration = 2.0;
int mouse_threshold = 10;

static uint32_t *palette; /* 256 words, 0x00RRGGBB */

void I_InitGraphics(void)
{
    I_VideoBuffer = gp_gmem_alloc(SCREENWIDTH * SCREENHEIGHT);
    palette = gp_gmem_alloc(256 * sizeof(*palette));
    doom_gpu_init(I_VideoBuffer, palette);
    screenvisible = true;
    I_InitInput();
}

void I_ShutdownGraphics(void)
{
}

void I_StartFrame(void)
{
}

void I_StartTic(void)
{
    I_GetEvent();
}

void I_UpdateNoBlit(void)
{
}

void I_FinishUpdate(void)
{
    doom_gpu_present();
}

void I_ReadScreen(byte *screen)
{
    memcpy(screen, I_VideoBuffer, SCREENWIDTH * SCREENHEIGHT);
}

void I_SetPalette(byte *doom_palette)
{
    for (int i = 0; i < 256; i++) {
        uint32_t red = gammatable[usegamma][*doom_palette++];
        uint32_t green = gammatable[usegamma][*doom_palette++];
        uint32_t blue = gammatable[usegamma][*doom_palette++];

        palette[i] = (red << 16) | (green << 8) | blue;
    }
    gp_gmem_sync(palette, 256 * sizeof(*palette));
}

int I_GetPaletteIndex(int r, int g, int b)
{
    int best = 0, best_difference = INT_MAX;

    for (int i = 0; i < 256; i++) {
        int dr = r - (int)((palette[i] >> 16) & 0xFF);
        int dg = g - (int)((palette[i] >> 8) & 0xFF);
        int db = b - (int)(palette[i] & 0xFF);
        int difference = dr * dr + dg * dg + db * db;

        if (difference < best_difference) {
            best = i;
            best_difference = difference;
        }
    }
    return best;
}

void I_BeginRead(void)
{
}

void I_EndRead(void)
{
}

void I_SetWindowTitle(char *title)
{
    DG_SetWindowTitle(title);
}

void I_GraphicsCheckCommandLine(void)
{
}

void I_SetGrabMouseCallback(grabmouse_callback_t callback)
{
    (void)callback;
}

void I_EnableLoadingDisk(void)
{
}

void I_BindVideoVariables(void)
{
}

void I_DisplayFPSDots(boolean dots_on)
{
    (void)dots_on;
}

void I_CheckIsScreensaver(void)
{
}
