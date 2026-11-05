/* SPDX-License-Identifier: GPL-2.0-only
 * Host side of the camera developer: bakes every film of a profile bundle
 * for the camera's output size and writes MFDEV.BIN.
 *
 *     mfdev_gen BUNDLE OUT.BIN [W H]          (default 1024 768)
 *
 * MFDEV.BIN (little endian, read by mfd_film_load on the camera):
 *   mfd_devfile_header
 *   nfilms x mfd_devfile_entry   (key, offset of the film's block)
 *   per film: mf_fx_look (16 x int32) + the 33^3 RGB uint16 table
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "mfd.h"

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "usage: mfdev_gen BUNDLE OUT.BIN [W H]\n"); return 2; }
    int w = argc > 4 ? atoi(argv[3]) : MFD_OUT_W, h = argc > 4 ? atoi(argv[4]) : MFD_OUT_H;
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 2; }
    fseek(f, 0, SEEK_END);
    size_t len = (size_t) ftell(f);
    fseek(f, 0, SEEK_SET);
    uint8_t *data = malloc(len);
    if (!data || fread(data, 1, len, f) != len) { perror(argv[1]); return 2; }
    fclose(f);
    mf_bundle b;
    if (mf_bundle_parse(data, len, &b) != MF_OK) { fprintf(stderr, "bad bundle\n"); return 1; }
    int n = b.nfilms;
    if (n <= 0 || n > 4096) { fprintf(stderr, "no films\n"); return 1; }

    mfd_devfile_header hd;
    memset(&hd, 0, sizeof hd);
    memcpy(hd.magic, MFD_DEVFILE_MAGIC, 8);
    hd.nfilms = (uint32_t) n, hd.width = (uint32_t) w, hd.height = (uint32_t) h;
    hd.block_bytes = (uint32_t) (sizeof(mf_fx_look) + sizeof(mf_table));
    mfd_devfile_entry *ix = calloc((size_t) n, sizeof *ix);
    static mf_table table;
    mf_develop_params p = { .grain_seed = 0, .grain_scale = 1, .halation_scale = 1, .softness_scale = 1,
                            .exposure_ev = 0, .reference_width = 0 };
    FILE *o = fopen(argv[2], "wb");
    if (!o || !ix) { perror(argv[2]); return 1; }
    long first = (long) (sizeof hd + sizeof *ix * (size_t) n);
    if (fseek(o, first, SEEK_SET)) { perror(argv[2]); return 1; }
    int baked = 0;
    for (int i = 0; i < n; i++)
    {
        char key[sizeof ix[0].key];
        memset(key, 0, sizeof key);
        strncpy(key, b.films[i].key, sizeof key - 1);
        const struct mf_film *film = &b.films[i];
        mf_fx_look look;
        if (!film || mf_fx_look_bake(film, &p, w, h, &look) != MF_OK)
        {
            fprintf(stderr, "skip %s: no fixed-point look at %dx%d\n", key, w, h);
            continue;
        }
        mf_table_from_film(film, &table);
        memcpy(ix[baked].key, key, sizeof ix[baked].key);
        ix[baked].offset = (uint32_t) (first + (long) baked * (long) hd.block_bytes);
        if (fwrite(&look, sizeof look, 1, o) != 1 || fwrite(&table, sizeof table, 1, o) != 1) { perror(argv[2]); return 1; }
        baked++;
    }
    hd.nfilms = (uint32_t) baked;
    /* entries of skipped films are left zero at the end of the index */
    if (fseek(o, 0, SEEK_SET) || fwrite(&hd, sizeof hd, 1, o) != 1 || fwrite(ix, sizeof *ix, (size_t) n, o) != (size_t) n
        || fclose(o) != 0)
    {
        perror(argv[2]);
        return 1;
    }
    printf("%s: %d films at %dx%d, %u bytes each\n", argv[2], baked, w, h, hd.block_bytes);
    mf_bundle_free(&b);
    free(ix), free(data);
    return 0;
}
