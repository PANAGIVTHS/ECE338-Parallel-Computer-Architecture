/*
 * Run one RTL case (tests/hardware/rtl/cases/test<N>) on the C simulator and
 * write the files tools/tests/expected_generator.py writes with the Python
 * model, so `gpgpu software runtime:check` can compare the two.
 *
 *   gpgpu_sim_case <case directory> <output directory>
 *
 * Inputs: program.mem, and optionally smem_seed.mem and ddr_seed.mem.
 * Outputs: regfile_c<lane>.mem, data.mem, perf.mem and, when the case seeds
 * or writes DDR, ddr.mem. Exit status 0 on completion, 1 on a fault or a
 * simulation error, 2 on a usage or file error.
 */
#include <ctype.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gpgpu_sim.h"

#define MAX_INSTRUCTIONS 100000u /* expected_generator.py --max-instructions */

static void fail(const char *what, const char *path)
{
    fprintf(stderr, "gpgpu_sim_case: %s: %s\n", path, what);
    exit(2);
}

/* The code part of a line: up to '#' or '//'. */
static void strip_comment(char *line)
{
    for (char *p = line; *p; p++)
        if (*p == '#' || (p[0] == '/' && p[1] == '/')) {
            *p = '\0';
            return;
        }
}

static FILE *open_file(const char *directory, const char *name, const char *mode, char *path, size_t size)
{
    snprintf(path, size, "%s/%s", directory, name);
    return fopen(path, mode);
}

static void load_words(const char *directory, const char *name, uint32_t *memory, uint32_t depth, int required,
                       int addressed)
{
    char path[4096], line[1024];
    FILE *file = open_file(directory, name, "r", path, sizeof path);
    if (file == NULL) {
        if (required)
            fail(strerror(errno), path);
        return;
    }
    uint32_t index = 0;
    while (fgets(line, sizeof line, file)) {
        strip_comment(line);
        for (char *token = strtok(line, " \t\r\n"); token; token = strtok(NULL, " \t\r\n")) {
            if (addressed && token[0] == '@') {
                index = (uint32_t)strtoul(token + 1, NULL, 16);
                if (index >= depth)
                    fail("seed address outside the memory", path);
                continue;
            }
            if (index >= depth)
                fail("more words than the memory holds", path);
            memory[index++] = (uint32_t)strtoul(token, NULL, 16);
        }
    }
    fclose(file);
}

static void mark(uint8_t *touched, uint32_t low, uint32_t addr)
{
    uint32_t index = (addr - low) >> 2;
    touched[index >> 3] |= (uint8_t)(1u << (index & 7u));
}

static void load_ddr_seed(const char *directory, uint8_t *ddr, uint8_t *touched, uint32_t low, uint32_t high)
{
    char path[4096], line[1024];
    FILE *file = open_file(directory, "ddr_seed.mem", "r", path, sizeof path);
    if (file == NULL)
        return;
    while (fgets(line, sizeof line, file)) {
        strip_comment(line);
        char *p = line;
        while (isspace((unsigned char)*p))
            p++;
        if (*p == '\0')
            continue;
        unsigned long addr, word;
        if (sscanf(p, "%lx %lx", &addr, &word) != 2)
            fail("expected '<address> <word>' in hex", path);
        if (addr & 3u || addr < low || addr + 4u > high)
            fail("a seed word is not aligned or not in DDR", path);
        uint32_t value = (uint32_t)word;
        memcpy(ddr + (addr - low), &value, 4);
        mark(touched, low, (uint32_t)addr);
    }
    fclose(file);
}

static FILE *create(const char *directory, const char *name)
{
    char path[4096];
    FILE *file = open_file(directory, name, "w", path, sizeof path);
    if (file == NULL)
        fail(strerror(errno), path);
    return file;
}

static void divergence(void *context, uint32_t pc)
{
    (void)context;
    fprintf(stderr, "  [WARNING] lanes disagree on the branch or ECALL at PC 0x%x; "
                    "the hardware follows lane 0 and so does the simulator\n", pc);
}

int main(int argc, char **argv)
{
    if (argc != 3) {
        fprintf(stderr, "usage: gpgpu_sim_case <case directory> <output directory>\n");
        return 2;
    }
    const char *case_dir = argv[1], *out_dir = argv[2];
    gpgpu_sim_config_t config = gpgpu_sim_default_config();
    uint32_t low, high;
    gpgpu_sim_ddr_bounds(&config, &low, &high);
    uint8_t *ddr = calloc(high - low, 1);
    uint8_t *touched = calloc((high - low) / 32u + 1u, 1);
    gpgpu_sim_t *sim = ddr && touched ? gpgpu_sim_create(&config, ddr, low, high, touched) : NULL;
    if (sim == NULL)
        fail("out of memory", case_dir);

    load_words(case_dir, "program.mem", gpgpu_sim_imem(sim), config.imem_words, 1, 0);
    load_words(case_dir, "smem_seed.mem", gpgpu_sim_smem(sim), config.smem_words, 0, 1);
    load_ddr_seed(case_dir, ddr, touched, low, high);

    gpgpu_sim_result_t result;
    gpgpu_sim_run(sim, MAX_INSTRUCTIONS, divergence, NULL, NULL, &result);
    if (result.status == GPGPU_SIM_FAULT) {
        fprintf(stderr, "%s: the kernel faults at PC 0x%x (lanes 0x%x, kinds 0x%x)\n", case_dir, result.fault_pc,
                result.fault_lanes, result.fault_kinds);
        return 1;
    }
    if (result.status != GPGPU_SIM_DONE) {
        fprintf(stderr, "%s: %s\n", case_dir, result.error);
        return 1;
    }

    for (uint32_t lane = 0; lane < config.lanes; lane++) {
        char name[64];
        snprintf(name, sizeof name, "regfile_c%u.mem", lane);
        FILE *file = create(out_dir, name);
        for (uint32_t reg = 0; reg < 32; reg++)
            fprintf(file, "%08x\n", gpgpu_sim_register(sim, lane, reg));
        fclose(file);
    }
    FILE *file = create(out_dir, "data.mem");
    for (uint32_t i = 0; i < config.smem_words; i++)
        fprintf(file, "%08x\n", gpgpu_sim_smem(sim)[i]);
    fclose(file);

    file = create(out_dir, "perf.mem");
    fprintf(file, "instructions %llu\nddr_lane_stores %llu\nsmem_lane_accesses %llu\nddr_lane_loads %llu\n"
                  "ddr_read_bursts %llu\nddr_read_beats %llu\n",
            (unsigned long long)result.instructions, (unsigned long long)result.ddr_lane_stores,
            (unsigned long long)result.smem_lane_accesses, (unsigned long long)result.ddr_lane_loads,
            (unsigned long long)result.ddr_read_bursts, (unsigned long long)result.ddr_read_beats);
    fclose(file);

    int any = result.ddr_bursts != 0;
    for (uint32_t i = 0; !any && i < (high - low) / 32u + 1u; i++)
        any = touched[i] != 0;
    if (any) {
        file = create(out_dir, "ddr.mem");
        fprintf(file, "bursts %llu\n", (unsigned long long)result.ddr_bursts);
        for (uint32_t byte = 0; byte < (high - low) / 32u + 1u; byte++) {
            if (touched[byte] == 0)
                continue;
            for (uint32_t bit = 0; bit < 8; bit++) {
                uint32_t addr = low + 4u * (8u * byte + bit), word;
                if (!(touched[byte] & (1u << bit)) || addr >= high)
                    continue;
                memcpy(&word, ddr + (addr - low), 4);
                fprintf(file, "%08x %08x\n", addr, word);
            }
        }
        fclose(file);
    }
    gpgpu_sim_destroy(sim);
    free(ddr);
    free(touched);
    return 0;
}
