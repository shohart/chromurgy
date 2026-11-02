/* SPDX-License-Identifier: GPL-2.0-only
 *
 * The film colour model, ported from M-Film ml-dev/filmos/fos_dev.c
 * (fos_film_color, curve, shift_hues, hue_angle, wrap; pinned commit in
 * LOCKFILE). Copyright (c) the M-Film authors, GPL-2.0.
 * Changes: renamed fos_ -> mf_, exact-match lookup without fallback,
 * hue angles computed without a lazily-initialised static (thread-safe).
 * The arithmetic is unchanged: tests/golden_film_color.txt is produced by
 * the upstream function itself (tools/gen_golden_film_color.sh).
 */
#include "mf_core.h"

#include <math.h>
#include <string.h>

static const float LUMA[3] = { 0.2126f, 0.7152f, 0.0722f };
static const float REF[7][3] = {        /* red orange yellow green cyan blue magenta */
    { 1, 0, 0 }, { 1, 0.5f, 0 }, { 1, 1, 0 }, { 0, 1, 0 }, { 0, 1, 1 }, { 0, 0, 1 }, { 1, 0, 1 } };
#define PI_F 3.14159265f

static float dot3(const float a[3], const float b[3])
{
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

static float hue_angle(int i)
{
    float y = dot3(REF[i], LUMA);
    return atan2f((REF[i][0] - y) / 1.5748f, (REF[i][2] - y) / 1.8556f);
}

static float wrap(float a)
{
    a = fmodf(a + PI_F, 2 * PI_F);
    if (a < 0) a += 2 * PI_F;
    return a - PI_F;
}

/* the characteristic curve: logistic in log2 exposure around mid grey */
static float curve(float x, float slope, float pivot, float black, float white)
{
    float xx = log2f((x > 1e-6f ? x : 1e-6f) / 0.18f) - pivot;
    float k = 4 * slope / (white - black);
    return black + (white - black) / (1 + expf(-k * xx));
}

static void shift_hues(const struct mf_look *f, float rgb[3])
{
    float y = dot3(rgb, LUMA);
    float cb = (rgb[2] - y) / 1.8556f, cr = (rgb[0] - y) / 1.5748f;
    float h = atan2f(cr, cb), c = sqrtf(cb * cb + cr * cr);
    float gate = c / 0.04f > 1 ? 1 : c / 0.04f;
    float dh = 0, cm = 1;
    const float sigma = 35 * PI_F / 180;
    for (int i = 0; i < f->nhues; i++)
    {
        const struct mf_hue_shift *s = &f->hues[i];
        float hs = hue_angle(s->from);
        float d = wrap(h - hs) / sigma;
        float w = expf(-0.5f * d * d) * gate;
        if (s->from != s->to) dh += w * s->amount * wrap(hue_angle(s->to) - hs);
        cm *= 1 + w * (s->chroma - 1);
    }
    h += dh;
    c *= cm;
    cb = c * cosf(h); cr = c * sinf(h);
    rgb[0] = y + 1.5748f * cr;
    rgb[2] = y + 1.8556f * cb;
    rgb[1] = (y - LUMA[0] * rgb[0] - LUMA[2] * rgb[2]) / LUMA[1];
}

void mf_film_color(const struct mf_look *f, const float in[3], float out[3])
{
    if (f->mono)
    {
        float v = curve(dot3(in, f->mono_mix), f->contrast[0], f->pivot[0], f->black[0], f->white[0]);
        out[0] = out[1] = out[2] = v;
        return;
    }
    float y = dot3(in, LUMA), lin[3];
    for (int c = 0; c < 3; c++)
    {
        lin[c] = y + (in[c] - y) * f->sat;
        if (lin[c] < 0) lin[c] = 0;
        out[c] = curve(lin[c], f->contrast[c], f->pivot[c], f->black[c], f->white[c]);
    }
    if (f->nhues) shift_hues(f, out);
}

const struct mf_look *mf_look_find(const char *key)
{
    if (!key) return NULL;
    for (int i = 0; i < mf_builtin_nlooks; i++)
        if (!strcmp(mf_builtin_looks[i].key, key)) return &mf_builtin_looks[i];
    return NULL;
}

int mf_core_process_tile(const struct mf_look *look, const mf_linear_tile *in,
                         const mf_tile_context *ctx, mf_output_tile *out)
{
    (void) look; (void) in; (void) ctx; (void) out;
    return MF_E_UNSUPPORTED;    /* P01: staging of halation/grain not ported yet */
}
