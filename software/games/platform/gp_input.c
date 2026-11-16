#include "gp_port.h"

/*
 * Key events from every input device, in the order they arrive.
 *
 * To add a device (a keyboard): write a file like gp_input_uart.c that
 * defines a gp_input_source_t, declare it in gp.h and add it to `sources`.
 * A game never knows which device a key came from.
 */

static const gp_input_source_t *const sources[] = {
    &gp_input_uart,
};

#define SOURCES (sizeof(sources) / sizeof(sources[0]))

void gp_input_init(void)
{
    for (unsigned int i = 0; i < SOURCES; i++) {
        if (sources[i]->init != NULL)
            sources[i]->init();
        gp_log("input: %s\r\n", sources[i]->name);
    }
}

int gp_input_poll(gp_key_event_t *event)
{
    for (unsigned int i = 0; i < SOURCES; i++)
        if (sources[i]->poll(event))
            return 1;
    return 0;
}
