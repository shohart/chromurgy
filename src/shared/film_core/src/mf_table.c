/* SPDX-License-Identifier: GPL-2.0-only
 * The film's colour table over Cineon code, after M-Film fos_dev.c
 * (cineon_encode/decode, lut_build, lut_apply). Float/uint16 instead of the
 * camera's uint8; same grid, same axis order, same tetrahedral split. */
#include "mf_core.h"

#include <math.h>

#define CIN_BLACK 0.0108f               /* 10^((95 - 685) * 0.002 / 0.6), as upstream */

float mf_cineon_decode(float v)
{
    float x = powf(10, (v * 1023 - 685) / 300);
    return (x - CIN_BLACK) / (1 - CIN_BLACK);
}

float mf_cineon_encode(float lin)
{
    float x = (lin > 0 ? lin : 0) * (1 - CIN_BLACK) + CIN_BLACK;
    float v = (685 + 300 * log10f(x)) / 1023;
    return v < 0 ? 0 : v > 1 ? 1 : v;
}

void mf_table_from_film(const struct mf_film *film, mf_table *t)
{
    if (film->table)
    {
        for (int i = 0; i < MF_NGRID; i++)
            for (int c = 0; c < 3; c++) t->v[i][c] = film->table[3 * i + c];
        return;
    }
    for (int i = 0; i < MF_NGRID; i++)
    {
        int r = i % MF_GRID, g = (i / MF_GRID) % MF_GRID, b = i / (MF_GRID * MF_GRID);
        float lin[3] = { mf_cineon_decode(r / (float) (MF_GRID - 1)), mf_cineon_decode(g / (float) (MF_GRID - 1)),
                         mf_cineon_decode(b / (float) (MF_GRID - 1)) }, out[3];
        mf_film_color(&film->look, lin, out);
        for (int c = 0; c < 3; c++)
        {
            float v = out[c] * 65535 + 0.5f;
            t->v[i][c] = (uint16_t) (v < 0 ? 0 : v > 65535 ? 65535 : v);
        }
    }
}

void mf_table_apply(const mf_table *t, const float lin[3], float out[3])
{
    float p[3];
    int i[3];
    for (int c = 0; c < 3; c++)
    {
        p[c] = mf_cineon_encode(lin[c]) * (MF_GRID - 1);
        i[c] = (int) p[c];
        if (i[c] > MF_GRID - 2) i[c] = MF_GRID - 2;
        p[c] -= (float) i[c];
    }
    float fr = p[0], fg = p[1], fb = p[2];
    const int R = 1, G = MF_GRID, B = MF_GRID * MF_GRID;
    const int base = (i[2] * MF_GRID + i[1]) * MF_GRID + i[0];
    int o1, o2;
    float w0, w1, w2, w3;
    if (fr >= fg)
    {
        if (fg >= fb)      { o1 = R; o2 = R + G; w0 = 1 - fr; w1 = fr - fg; w2 = fg - fb; w3 = fb; }
        else if (fr >= fb) { o1 = R; o2 = R + B; w0 = 1 - fr; w1 = fr - fb; w2 = fb - fg; w3 = fg; }
        else               { o1 = B; o2 = R + B; w0 = 1 - fb; w1 = fb - fr; w2 = fr - fg; w3 = fg; }
    }
    else
    {
        if (fb >= fg)      { o1 = B; o2 = G + B; w0 = 1 - fb; w1 = fb - fg; w2 = fg - fr; w3 = fr; }
        else if (fb >= fr) { o1 = G; o2 = G + B; w0 = 1 - fg; w1 = fg - fb; w2 = fb - fr; w3 = fr; }
        else               { o1 = G; o2 = R + G; w0 = 1 - fg; w1 = fg - fr; w2 = fr - fb; w3 = fb; }
    }
    const uint16_t *a = t->v[base], *b = t->v[base + o1], *c = t->v[base + o2], *d = t->v[base + R + G + B];
    for (int k = 0; k < 3; k++)
        out[k] = (w0 * a[k] + w1 * b[k] + w2 * c[k] + w3 * d[k]) * (1.0f / 65535);
}
