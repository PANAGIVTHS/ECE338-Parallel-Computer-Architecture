#include "gp_port.h"

/*
 * Keys from a terminal on the console UART.
 *
 * A terminal sends a byte when a key goes down and more bytes while it is
 * held (its auto-repeat), but nothing when it comes up. So a key counts as
 * held until GP_INPUT_HOLD_MS pass without another byte for it, and is then
 * released (software.games.platform.input.hold_ms). Three consequences:
 *
 *  - A tap lasts hold_ms. Lower it for finer steps, but not below the
 *    terminal's repeat interval, or a held key stutters.
 *  - A terminal waits before it starts repeating (often 500 ms), which is
 *    longer than hold_ms: a held key stops once, then runs. A shorter
 *    repeat delay on the PC removes that (`xset r rate 150 30`).
 *  - A terminal repeats only the last key pressed, so two keys cannot be
 *    held together. A real keyboard, as another gp_input_source_t, has
 *    neither limit.
 *
 * Decoded: printable ASCII (upper case as Shift + the lower-case key),
 * Enter, Tab, Backspace, Escape, and the escape sequences of the arrow,
 * navigation and function keys, with their Shift/Alt/Ctrl modifiers.
 */

#define HELD_KEYS    8u
#define QUEUE_EVENTS 16u
#define SEQUENCE_MAX 8u
/* A lone ESC is the Escape key once this long passes with no byte after it. */
#define ESCAPE_MS    30u

typedef struct {
    uint16_t key;
    uint32_t release_at;
} held_key_t;

static held_key_t held[HELD_KEYS];
static unsigned int held_count;

static gp_key_event_t queue[QUEUE_EVENTS];
static unsigned int queue_head, queue_count;

static char sequence[SEQUENCE_MAX]; /* bytes after ESC */
static unsigned int sequence_length;
static int in_sequence;
static uint32_t sequence_started;

static void emit(uint16_t key, int pressed)
{
    if (queue_count == QUEUE_EVENTS)
        return; /* the game is not reading: drop, the release timers recover */
    queue[(queue_head + queue_count++) % QUEUE_EVENTS] = (gp_key_event_t){ key, (uint8_t)pressed };
}

/* The key is down now: press it, or keep it held a while longer. */
static void touch(uint16_t key, uint32_t now)
{
    for (unsigned int i = 0; i < held_count; i++) {
        if (held[i].key == key) {
            held[i].release_at = now + GP_INPUT_HOLD_MS;
            return;
        }
    }
    if (held_count == HELD_KEYS) { /* release the oldest to make room */
        emit(held[0].key, 0);
        for (unsigned int i = 1; i < held_count; i++)
            held[i - 1] = held[i];
        held_count--;
    }
    held[held_count++] = (held_key_t){ key, now + GP_INPUT_HOLD_MS };
    emit(key, 1);
}

static void release_expired(uint32_t now)
{
    unsigned int kept = 0;

    for (unsigned int i = 0; i < held_count; i++) {
        if ((int32_t)(now - held[i].release_at) >= 0)
            emit(held[i].key, 0);
        else
            held[kept++] = held[i];
    }
    held_count = kept;
}

/* xterm's modifier parameter: 1 + (1 Shift | 2 Alt | 4 Ctrl). */
static void touch_modified(uint16_t key, unsigned int modifier, uint32_t now)
{
    unsigned int bits = modifier > 0 ? modifier - 1u : 0u;

    if (bits & 1u)
        touch(GP_KEY_SHIFT, now);
    if (bits & 2u)
        touch(GP_KEY_ALT, now);
    if (bits & 4u)
        touch(GP_KEY_CTRL, now);
    touch(key, now);
}

/* A complete sequence after ESC: "[A", "[1;2A", "[15~", "OP". */
static void decode_sequence(uint32_t now)
{
    static const uint16_t letters[][2] = {
        { 'A', GP_KEY_UP }, { 'B', GP_KEY_DOWN }, { 'C', GP_KEY_RIGHT }, { 'D', GP_KEY_LEFT },
        { 'H', GP_KEY_HOME }, { 'F', GP_KEY_END },
        { 'P', GP_KEY_F1 }, { 'Q', GP_KEY_F1 + 1 }, { 'R', GP_KEY_F1 + 2 }, { 'S', GP_KEY_F1 + 3 },
    };
    static const uint16_t numbers[][2] = {
        { 1, GP_KEY_HOME }, { 2, GP_KEY_INSERT }, { 3, GP_KEY_DELETE }, { 4, GP_KEY_END },
        { 5, GP_KEY_PAGE_UP }, { 6, GP_KEY_PAGE_DOWN }, { 7, GP_KEY_HOME }, { 8, GP_KEY_END },
        { 11, GP_KEY_F1 }, { 12, GP_KEY_F1 + 1 }, { 13, GP_KEY_F1 + 2 }, { 14, GP_KEY_F1 + 3 },
        { 15, GP_KEY_F1 + 4 }, { 17, GP_KEY_F1 + 5 }, { 18, GP_KEY_F1 + 6 }, { 19, GP_KEY_F1 + 7 },
        { 20, GP_KEY_F1 + 8 }, { 21, GP_KEY_F1 + 9 }, { 23, GP_KEY_F1 + 10 }, { 24, GP_KEY_F12 },
    };
    unsigned int values[2] = { 0, 0 }, value = 0;
    char final = sequence[sequence_length - 1u];

    for (unsigned int i = 1; i + 1u < sequence_length; i++) {
        if (sequence[i] >= '0' && sequence[i] <= '9')
            values[value] = values[value] * 10u + (unsigned int)(sequence[i] - '0');
        else if (sequence[i] == ';' && value == 0)
            value = 1;
    }

    if (final == '~') {
        for (unsigned int i = 0; i < sizeof(numbers) / sizeof(numbers[0]); i++)
            if (numbers[i][0] == values[0])
                touch_modified(numbers[i][1], values[1], now);
        return;
    }
    for (unsigned int i = 0; i < sizeof(letters) / sizeof(letters[0]); i++)
        if (letters[i][0] == (uint16_t)final)
            touch_modified(letters[i][1], values[1], now);
}

static void decode_byte(int byte, uint32_t now)
{
    if (in_sequence) {
        /* ESC ESC: the first was the Escape key. */
        if (sequence_length == 0 && byte == 27) {
            touch(GP_KEY_ESCAPE, now);
            sequence_started = now;
            return;
        }
        /* Only "[" and "O" introduce a sequence; anything else was Escape
         * followed by a key of its own. */
        if (sequence_length == 0 && byte != '[' && byte != 'O') {
            in_sequence = 0;
            touch(GP_KEY_ESCAPE, now);
        } else {
            sequence[sequence_length++] = (char)byte;
            /* The final byte of a sequence is a letter or "~". */
            if (sequence_length > 1u && (byte >= '@' && byte <= '~')) {
                decode_sequence(now);
                in_sequence = 0;
            } else if (sequence_length == SEQUENCE_MAX) {
                in_sequence = 0; /* not a sequence this decoder knows */
            }
            return;
        }
    }

    if (byte == 27) {
        in_sequence = 1;
        sequence_length = 0;
        sequence_started = now;
    } else if (byte == '\r' || byte == '\n') {
        touch(GP_KEY_ENTER, now);
    } else if (byte == '\t') {
        touch(GP_KEY_TAB, now);
    } else if (byte == 8 || byte == 127) {
        touch(GP_KEY_BACKSPACE, now);
    } else if (byte >= 'A' && byte <= 'Z') {
        touch(GP_KEY_SHIFT, now);
        touch((uint16_t)(byte - 'A' + 'a'), now);
    } else if (byte >= ' ' && byte < 127) {
        touch((uint16_t)byte, now);
    }
}

static int uart_poll(gp_key_event_t *event)
{
    uint32_t now = gp_time_ms();
    int byte;

    /* Leave room for the events one byte can make: Shift, Alt, Ctrl, the key. */
    while (queue_count + 4u <= QUEUE_EVENTS && (byte = gp_port_console_read()) >= 0)
        decode_byte(byte, now);
    if (in_sequence && sequence_length == 0 && now - sequence_started >= ESCAPE_MS) {
        in_sequence = 0;
        touch(GP_KEY_ESCAPE, now);
    }
    release_expired(now);

    if (queue_count == 0)
        return 0;
    *event = queue[queue_head];
    queue_head = (queue_head + 1u) % QUEUE_EVENTS;
    queue_count--;
    return 1;
}

const gp_input_source_t gp_input_uart = { "UART terminal", NULL, uart_poll };
