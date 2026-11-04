/* SPDX-License-Identifier: GPL-2.0-only
 * Host side of the camera benchmark: bakes the looks for a film, develops
 * the synthetic frames exactly as the camera module will and writes
 * MFBENCH.BIN (looks, expected output hashes, the film's 33^3 table).
 *
 *     mfbench_gen BUNDLE FILM OUT.BIN [PREVIEW.PPM]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "mfbench.h"

static long host_clock(void) { return (long) (clock() * 1000.0 / CLOCKS_PER_SEC); }

static void ppm_rows(void *ctx, const uint16_t *rows, int y0, int n, int w)
{
    FILE *f = ctx;
    (void) y0;
    for (size_t i = 0; i < 3 * (size_t) n * w; i++) fputc((rows[i] * 255u + 32767u) / 65535u, f);
}

int main(int argc, char **argv)
{
    if (argc < 4) { fprintf(stderr, "usage: mfbench_gen BUNDLE FILM OUT.BIN [PREVIEW.PPM]\n"); return 2; }
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
    const struct mf_film *film = mf_bundle_find(&b, argv[2]);
    if (!film) { fprintf(stderr, "no film %s\n", argv[2]); return 1; }
    static mf_table table;
    mf_table_from_film(film, &table);

    static const int sizes[][2] = { { 720, 480 }, { 1200, 800 } };
    mfb_header hd;
    memset(&hd, 0, sizeof hd);
    memcpy(hd.magic, MFB_MAGIC, 8);
    hd.ncases = 2;
    hd.table_bytes = sizeof table;
    strncpy(hd.film, argv[2], sizeof hd.film - 1);
    mfb_case cs[2];
    mf_develop_params p = { .grain_seed = 0x1234567890abcdefULL, .grain_scale = 1, .halation_scale = 1,
                            .softness_scale = 1, .exposure_ev = 0, .reference_width = 0 };
    for (unsigned i = 0; i < hd.ncases; i++)
    {
        int w = sizes[i][0], h = sizes[i][1];
        memset(&cs[i], 0, sizeof cs[i]);
        if (mf_fx_look_bake(film, &p, w, h, &cs[i].look) != MF_OK) { fprintf(stderr, "bake %dx%d refused\n", w, h); return 1; }
        cs[i].seed_lo = (uint32_t) p.grain_seed;
        cs[i].seed_hi = (uint32_t) (p.grain_seed >> 32);
        size_t mlen = mf_fx_ctx_size(w, h), sb = 3 * (size_t) w * MFB_STRIP * 2;
        void *mem = malloc(mlen);
        uint16_t *in = malloc(sb), *out = malloc(sb);
        uint8_t *hb = malloc(32 + sb);
        FILE *pv = NULL;
        if (i == 0 && argc > 4)
        {
            pv = fopen(argv[4], "wb");
            if (pv) fprintf(pv, "P6\n%d %d\n255\n", w, h);
        }
        mfb_times t;
        int rc = mfb_run(&cs[i], &table.v[0][0], mem, mlen, in, out, hb, cs[i].expect, host_clock, &t,
                         pv ? ppm_rows : 0, pv, 0);
        if (pv) fclose(pv);
        if (rc != MF_OK) { fprintf(stderr, "run %dx%d: %d\n", w, h, rc); return 1; }
        printf("%s %dx%d ctx %zu B, host ms scan %ld glow %ld render %ld hash %ld, out ", argv[2], w, h, mlen, t.scan,
               t.glow, t.render, t.hash);
        for (int k = 0; k < 32; k++) printf("%02x", cs[i].expect[k]);
        printf("\n");
        free(mem), free(in), free(out), free(hb);
    }
    FILE *o = fopen(argv[3], "wb");
    if (!o || fwrite(&hd, sizeof hd, 1, o) != 1 || fwrite(cs, sizeof cs[0], hd.ncases, o) != hd.ncases
        || fwrite(&table, sizeof table, 1, o) != 1 || fclose(o) != 0)
    {
        perror(argv[3]);
        return 1;
    }
    mf_bundle_free(&b);
    free(data);
    return 0;
}
