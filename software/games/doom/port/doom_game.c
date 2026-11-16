/*
 * DOOM as a game of the platform: start-up, the frame, time and keys.
 *
 * The game is doomgeneric (fetched by the build, not changed). It asks its
 * port for the time and for key events; this file answers from the platform.
 */

#include "gp.h"

#include "doomgeneric.h"
#include "doomkeys.h"
#include "m_argv.h"

void D_DoomMain(void);
void M_FindResponseFile(void);

static void doom_init(int argc, char **argv)
{
    myargc = argc;
    myargv = argv;
    M_FindResponseFile();
    D_DoomMain(); /* returns after the first frame; doomgeneric_Tick draws the rest */
}

static void doom_tick(void)
{
    doomgeneric_Tick();
}

const gp_game_t gp_game = { "doom", doom_init, doom_tick };

uint32_t DG_GetTicksMs(void)
{
    return gp_time_ms();
}

void DG_SleepMs(uint32_t ms)
{
    gp_sleep_ms(ms);
}

void DG_SetWindowTitle(const char *title)
{
    gp_log("doom: %s\r\n", title);
}

/*
 * Platform key -> DOOM key. Keys not listed are their own ASCII code, which
 * is what DOOM expects for digits (weapons), y/n and the menu's letters.
 *
 * The movement keys are doubled on letters for a terminal with no usable
 * arrow keys. Those letters then never reach DOOM as letters, so a cheat
 * code or a savegame name cannot contain w, a, s, d, q, e or f.
 */
static const struct {
    uint16_t key;
    unsigned char doom;
} keymap[] = {
    { GP_KEY_UP, KEY_UPARROW },       { 'w', KEY_UPARROW },
    { GP_KEY_DOWN, KEY_DOWNARROW },   { 's', KEY_DOWNARROW },
    { GP_KEY_LEFT, KEY_LEFTARROW },   { 'a', KEY_LEFTARROW },
    { GP_KEY_RIGHT, KEY_RIGHTARROW }, { 'd', KEY_RIGHTARROW },
    { 'q', KEY_STRAFE_L },            { 'e', KEY_STRAFE_R },
    { 'f', KEY_FIRE },                { GP_KEY_CTRL, KEY_FIRE },
    { ' ', KEY_USE },
    { GP_KEY_SHIFT, KEY_RSHIFT },     { GP_KEY_ALT, KEY_RALT },
    { GP_KEY_ENTER, KEY_ENTER },      { GP_KEY_ESCAPE, KEY_ESCAPE },
    { GP_KEY_TAB, KEY_TAB },          { GP_KEY_BACKSPACE, KEY_BACKSPACE },
    { GP_KEY_HOME, KEY_HOME },        { GP_KEY_END, KEY_END },
    { GP_KEY_PAGE_UP, KEY_PGUP },     { GP_KEY_PAGE_DOWN, KEY_PGDN },
    { GP_KEY_INSERT, KEY_INS },       { GP_KEY_DELETE, KEY_DEL },
    { GP_KEY_F1, KEY_F1 },            { GP_KEY_F1 + 1, KEY_F2 },
    { GP_KEY_F1 + 2, KEY_F3 },        { GP_KEY_F1 + 3, KEY_F4 },
    { GP_KEY_F1 + 4, KEY_F5 },        { GP_KEY_F1 + 5, KEY_F6 },
    { GP_KEY_F1 + 6, KEY_F7 },        { GP_KEY_F1 + 7, KEY_F8 },
    { GP_KEY_F1 + 8, KEY_F9 },        { GP_KEY_F1 + 9, KEY_F10 },
    { GP_KEY_F1 + 10, KEY_F11 },      { GP_KEY_F12, KEY_F12 },
};

int DG_GetKey(int *pressed, unsigned char *key)
{
    gp_key_event_t event;

    while (gp_input_poll(&event)) {
        unsigned char doom = event.key < 128 ? (unsigned char)event.key : 0;

        for (unsigned int i = 0; i < sizeof(keymap) / sizeof(keymap[0]); i++) {
            if (keymap[i].key == event.key) {
                doom = keymap[i].doom;
                break;
            }
        }
        if (doom != 0) {
            *pressed = event.pressed;
            *key = doom;
            return 1;
        }
    }
    return 0;
}
