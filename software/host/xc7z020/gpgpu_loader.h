#ifndef GPGPU_LOADER_H
#define GPGPU_LOADER_H

/*
 * The monitor's program loader (docs/runtime-spec.md, section 9.2): it
 * receives an A9 program over the UART and runs it, without a reset.
 *
 *   load <entry_hex> <segments>   then, per segment, the PC sends a header of
 *                                 three little-endian words (address, size,
 *                                 CRC-32) and, after SEGMENT_READY, the bytes
 *   run <name> [arguments]        run the loaded program; it returns here
 *
 * Replies, one per line: READY_LOAD, SEGMENT_READY, SEGMENT_OK, LOAD_COMPLETE;
 * RUN_START, then the program's own output, then RUN_RETURN <status>; or a
 * line starting with ERROR.
 */

/* The `load` command; arguments are the rest of the command line. 0 or -1. */
int gpgpu_loader_load(const char *entry, const char *segments);

/* The `run` command: `line` holds the program's name and arguments, separated
 * by spaces. Returns the program's status, or -1 if nothing is loaded. */
int gpgpu_loader_run(char *line);

#endif /* GPGPU_LOADER_H */
