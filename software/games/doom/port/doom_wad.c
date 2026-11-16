/*
 * DOOM's WAD file, from the game's built-in files (replaces doomgeneric's
 * w_file.c and w_file_stdc.c, which read it with fopen).
 *
 * The WAD is copied into GMEM and handed to DOOM as a memory-mapped file.
 * DOOM then uses every lump where it lies, so the textures, flats, sprites
 * and colormaps it gives its drawing loops are already where the GPU reads.
 */

#include <stdlib.h>
#include <string.h>

#include "gp.h"

#include "doomtype.h"
#include "w_file.h"

boolean __real_M_FileExists(char *filename);

static wad_file_t *memory_open(char *path);

static void memory_close(wad_file_t *file)
{
    free(file); /* the copy in GMEM stays: lumps point into it */
}

static size_t memory_read(wad_file_t *file, unsigned int offset, void *buffer, size_t length)
{
    if (offset >= file->length)
        return 0;
    if (length > file->length - offset)
        length = file->length - offset;
    memcpy(buffer, file->mapped + offset, length);
    return length;
}

static wad_file_class_t memory_class = { memory_open, memory_close, memory_read };

static wad_file_t *memory_open(char *path)
{
    const gp_asset_t *asset = gp_asset_find(path);

    if (asset == NULL)
        return NULL;

    wad_file_t *file = malloc(sizeof(*file));
    byte *copy = gp_gmem_alloc(asset->size);

    if (file == NULL)
        gp_fatal("W_OpenFile: out of memory");
    memcpy(copy, asset->data, asset->size);
    gp_gmem_sync(copy, asset->size);

    file->file_class = &memory_class;
    file->mapped = copy;
    file->length = (unsigned int)asset->size;
    gp_log("doom: %s, %lu bytes, in GMEM at %p\r\n", asset->name, (unsigned long)asset->size, (void *)copy);
    return file;
}

wad_file_t *W_OpenFile(char *path)
{
    return memory_open(path);
}

void W_CloseFile(wad_file_t *wad)
{
    wad->file_class->CloseFile(wad);
}

size_t W_Read(wad_file_t *wad, unsigned int offset, void *buffer, size_t length)
{
    return wad->file_class->Read(wad, offset, buffer, length);
}

/* DOOM looks for its WAD with fopen before it opens it: a built-in file
 * exists. (Linked with --wrap=M_FileExists; see the game's manifest.) */
boolean __wrap_M_FileExists(char *filename)
{
    return gp_asset_find(filename) != NULL || __real_M_FileExists(filename);
}
