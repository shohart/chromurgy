/* SPDX-License-Identifier: GPL-2.0-only */
#include <string.h>
#include "mfbench.h"

static int32_t tri(int32_t p)       /* triangle wave of period 65536, 0..65536 */
{
    p &= 65535;
    return p < 32768 ? 2 * p : 2 * (65536 - p);
}

void mfb_scene_rows(uint16_t *rgb, int w, int h, int y0, int n)
{
    for (int y = y0; y < y0 + n; y++)
    {
        int32_t u = (int32_t) (((uint32_t) y << 16) / (uint32_t) (h > 1 ? h - 1 : 1));   /* 32-bit divides only */
        int32_t c[3];
        for (int k = 0; k < 3; k++)                       /* 0.2 .. 1.0 in Q16, phase-shifted per channel */
            c[k] = 13107 + (int32_t) (((int64_t) tri(u + k * 21845) * 52429) >> 16);
        int band = (y / (h / 6 > 0 ? h / 6 : 1)) % 2 == 0;
        for (int x = 0; x < w; x++)
        {
            /* exposure: 2^-11 .. 2^1.25 of white */
            int32_t v = -11 * 65536 + (int32_t) (((uint32_t) x * 802816u) / (uint32_t) (w > 1 ? w - 1 : 1));   /* 12.25 stops, w <= 5000 */
            uint32_t l = (uint32_t) mf_fx_exp2_q16(v);    /* Q16 */
            uint16_t *p = rgb + 3 * ((size_t) (y - y0) * w + x);
            int block = band && (x / (w / 8 > 0 ? w / 8 : 1)) % 3 == 1;
            for (int k = 0; k < 3; k++)
            {
                uint32_t q = block ? 49152u : (uint32_t) (((uint64_t) l * (uint32_t) c[k]) >> 17);   /* Q15 */
                p[k] = (uint16_t) (q > 65535 ? 65535 : q);
            }
        }
    }
}

int mfb_run(const mfb_case *c, const uint16_t *table, void *mem, size_t mem_len, uint16_t *in, uint16_t *out,
            uint8_t *hbuf, uint8_t hash[32], mfb_clock clk, mfb_times *t,
            void (*rows_cb)(void *ctx, const uint16_t *rows, int y0, int n, int w), void *cb_ctx)
{
    int w = c->look.width, h = c->look.height, rc;
    size_t stride = 3 * (size_t) w;
    uint64_t seed = ((uint64_t) c->seed_hi << 32) | c->seed_lo;
    mf_fx *fx;
    long t0;
    memset(t, 0, sizeof *t);
    if ((rc = mf_fx_begin(mem, mem_len, &c->look, table, seed, &fx)) != MF_OK) return rc;
    for (int y = 0; y < h; y += MFB_STRIP)
    {
        int n = y + MFB_STRIP > h ? h - y : MFB_STRIP;
        mfb_scene_rows(in, w, h, y, n);
        t0 = clk();
        if ((rc = mf_fx_scan_rows(fx, in, stride, y, n)) != MF_OK) return rc;
        t->scan += clk() - t0;
    }
    for (int y = 0; y < h; y += MFB_STRIP)
    {
        int n = y + MFB_STRIP > h ? h - y : MFB_STRIP;
        mfb_scene_rows(in, w, h, y, n);
        t0 = clk();
        if ((rc = mf_fx_glow_rows(fx, in, stride, y, n)) != MF_OK) return rc;
        t->glow += clk() - t0;
    }
    memset(hash, 0, 32);
    for (int y = 0; y < h; y += MFB_STRIP)
    {
        int n = y + MFB_STRIP > h ? h - y : MFB_STRIP;
        mfb_scene_rows(in, w, h, y, n);
        t0 = clk();
        if ((rc = mf_fx_render_rows(fx, in, stride, y, n, out, stride)) != MF_OK) return rc;
        t->render += clk() - t0;
        t0 = clk();
        memcpy(hbuf, hash, 32);
        memcpy(hbuf + 32, out, (size_t) n * stride * 2);
        mf_sha256(hbuf, 32 + (size_t) n * stride * 2, hash);
        t->hash += clk() - t0;
        if (rows_cb) rows_cb(cb_ctx, out, y, n, w);
    }
    return MF_OK;
}
