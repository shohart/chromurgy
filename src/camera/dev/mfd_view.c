/* SPDX-License-Identifier: GPL-2.0-only
 * The viewer frame, made while the developer streams its output rows: a
 * 720x480 UYVYYY MFV file (same format as mfilm_server/camera_view.py) for
 * the app's viewer, turned upright by the DNG's orientation.
 *
 * Landscape (orientation 1, 3): the 4:3 frame fills the buffer; rows are
 *   resampled as they arrive (bilinear), written in order (3: bottom up).
 * Portrait (6, 8): the frame is turned, so each developed row becomes a
 *   column of the 404x480 pillarbox. Columns (RGB565, 960 bytes) go to a
 *   temporary file next to the MFV (.MFT) as they arrive; at the end the file
 *   is read in bands of 80 rows and turned into MFV rows. Memory ~70 KB: the
 *   camera's heap had no 390 KB block to spare (0.4.3, "out of memory").
 *   Each target pixel averages a 2x2 block. */
#include <string.h>
#include "mfd.h"

#define VW MFD_VIEW_W
#define VH MFD_VIEW_H
#define VBW (VW * 6 / 4)
#define PW 404                 /* portrait width in buffer pixels: 480 * 3/4 * (720/640), whole blocks */
#define PX0 156                /* ((720 - 404) / 2) & ~3 */

struct mfd_view {
    const mfd_env *env;
    void *f;
    int w, h, orient;
    uint8_t *prev;             /* last row of the previous call (w * 3) */
    int have_prev;
    int next_y;                /* landscape: next MFV row to emit */
    uint8_t *line;             /* one MFV row */
    int portrait;
    void *cf;                  /* portrait: column file */
    char cpath[96];
    uint16_t *col;             /* one column, VH px */
    int ncols;
};

size_t mfd_view_size(void) { return sizeof(struct mfd_view); }

static void pack_row(const uint8_t *rgb, uint8_t *out, int npx)
{
    for (int x = 0; x < npx; x += 4, rgb += 12, out += 6)
    {
        int32_t y[4], us = 0, vs = 0;
        for (int k = 0; k < 4; k++)
        {
            int32_t r = rgb[3 * k], g = rgb[3 * k + 1], b = rgb[3 * k + 2];
            y[k] = (77 * r + 150 * g + 29 * b + 128) >> 8;
            us += -43 * r - 85 * g + 128 * b;
            vs += 128 * r - 107 * g - 21 * b;
        }
        int32_t u = us >= 0 ? (us + 512) >> 10 : -((-us + 512) >> 10);
        int32_t v = vs >= 0 ? (vs + 512) >> 10 : -((-vs + 512) >> 10);
        u = u > 127 ? 127 : u < -128 ? -128 : u;
        v = v > 127 ? 127 : v < -128 ? -128 : v;
        out[0] = (uint8_t) (int8_t) u, out[1] = (uint8_t) y[0], out[2] = (uint8_t) (int8_t) v;
        out[3] = (uint8_t) y[1], out[4] = (uint8_t) y[2], out[5] = (uint8_t) y[3];
    }
}

static const uint8_t mfv_header[12] = {'M', 'F', 'V', '1', VW & 255, VW >> 8, VH & 255, VH >> 8, VBW & 255, VBW >> 8, 0, 0};

int mfd_view_begin(mfd_view *V, const mfd_env *env, const char *path, int w, int h, int orient)
{
    memset(V, 0, sizeof *V);
    V->env = env, V->w = w, V->h = h, V->orient = orient;
    if (orient != 1 && orient != 3 && orient != 6 && orient != 8) V->orient = 1;
    if (!(V->f = env->open(path, 1))) return MFD_E_IO;
    V->prev = env->alloc((size_t) w * 3);
    V->line = env->alloc(VW * 3 + VBW);
    if (!V->prev || !V->line) return MFD_E_MEM;
    if (V->orient == 6 || V->orient == 8)
    {
        size_t n = strlen(path);
        if (n < 2 || n >= sizeof V->cpath) return MFD_E_IO;
        memcpy(V->cpath, path, n + 1);
        V->cpath[n - 1] = 'T';                            /* F01.MFV -> F01.MFT */
        V->portrait = 1;
        if (!(V->col = env->alloc(VH * 2))) return MFD_E_MEM;
        if (!(V->cf = env->open(V->cpath, 1))) return MFD_E_IO;
    }
    if (env->write(V->f, mfv_header, 12) != 12) return MFD_E_IO;
    if (V->orient == 3)                                   /* rows go bottom up: size the file first */
    {
        memset(V->line, 0, VBW);
        for (int y = 0; y < VH; y++)
            if (env->write(V->f, V->line, VBW) != VBW) return MFD_E_IO;
    }
    return MFD_OK;
}

/* source pixel row r (absolute), from the current rows [y0, y0+n) or the kept previous row */
static const uint8_t *src_row(mfd_view *V, const uint8_t *rgb, int y0, int r)
{
    if (r >= y0) return rgb + (size_t) (r - y0) * V->w * 3;
    return V->prev;
}

static int landscape(mfd_view *V, const uint8_t *rgb, int y0, int n)
{
    int last = y0 + n - 1;
    uint8_t *px = V->line, *out = V->line + VW * 3;
    while (V->next_y < VH)
    {
        /* source row centre of MFV row y: (y + 0.5) * h / VH - 0.5, Q8 */
        int32_t sy = (int32_t) (((2 * V->next_y + 1) * V->h * 128) / VH) - 128;
        if (sy < 0) sy = 0;
        int r0 = sy >> 8, fy = sy & 255;
        int r1 = r0 + 1 < V->h ? r0 + 1 : r0;
        if (r1 > last) break;                              /* wait for more rows */
        if (r0 < y0 - 1 || (r0 == y0 - 1 && !V->have_prev)) r0 = r1;
        const uint8_t *a = src_row(V, rgb, y0, r0), *b = src_row(V, rgb, y0, r1);
        for (int x = 0; x < VW; x++)
        {
            int32_t sx = (int32_t) (((2 * x + 1) * V->w * 128) / VW) - 128;
            if (sx < 0) sx = 0;
            int c0 = sx >> 8, fx = sx & 255, c1 = c0 + 1 < V->w ? c0 + 1 : c0;
            int tx = V->orient == 3 ? VW - 1 - x : x;
            for (int c = 0; c < 3; c++)
            {
                int32_t top = a[3 * c0 + c] * (256 - fx) + a[3 * c1 + c] * fx;
                int32_t bot = b[3 * c0 + c] * (256 - fx) + b[3 * c1 + c] * fx;
                px[3 * tx + c] = (uint8_t) ((top * (256 - fy) + bot * fy + 32768) >> 16);
            }
        }
        pack_row(px, out, VW);
        if (V->orient == 3 && V->env->seek(V->f, 12 + (long) (VH - 1 - V->next_y) * VBW)) return MFD_E_IO;
        if (V->env->write(V->f, out, VBW) != VBW) return MFD_E_IO;
        V->next_y++;
    }
    return MFD_OK;
}

/* portrait: developed row r is upright column uc = r (orientation 8, turned
 * counter-clockwise) or h-1-r (6, clockwise); upright row ur is source
 * column w-1-ur (8) or ur (6). Target (tx, ty) <- upright (ur, uc). */
static int col_of(const mfd_view *V, int tx) { return ((2 * tx + 1) * V->h) / (2 * PW); }

/* columns arrive in order of tx: increasing for 8, decreasing for 6 */
static int portrait(mfd_view *V, const uint8_t *rgb, int y0, int n)
{
    for (int r = y0; r < y0 + n; r++)
    {
        int uc = V->orient == 8 ? r : V->h - 1 - r;
        int t0 = (uc * PW) / V->h, tx = -1;
        for (int t = t0 - 1; t <= t0 + 1; t++)
            if (t >= 0 && t < PW && col_of(V, t) == uc) tx = t;
        if (tx < 0) continue;
        /* 2x2 block: this row and the one before it (or itself at the top) */
        const uint8_t *b = src_row(V, rgb, y0, r);
        const uint8_t *a = r > y0 ? src_row(V, rgb, y0, r - 1) : (V->have_prev ? V->prev : b);
        for (int ty = 0; ty < VH; ty++)
        {
            int ur = ((2 * ty + 1) * V->w) / (2 * VH);
            int c = V->orient == 8 ? V->w - 1 - ur : ur;
            int c2 = c + 1 < V->w ? c + 1 : c;
            int v[3];
            for (int k = 0; k < 3; k++) v[k] = (a[3 * c + k] + a[3 * c2 + k] + b[3 * c + k] + b[3 * c2 + k] + 2) >> 2;
            V->col[ty] = (uint16_t) ((v[0] >> 3) << 11 | (v[1] >> 2) << 5 | (v[2] >> 3));
        }
        if (V->env->write(V->cf, V->col, VH * 2) != VH * 2) return MFD_E_IO;
        V->ncols++;
    }
    return MFD_OK;
}

int mfd_view_rows(mfd_view *V, const uint8_t *rgb, int y0, int n)
{
    int rc = MFD_OK;
    if (V->portrait) rc = portrait(V, rgb, y0, n);
    else rc = landscape(V, rgb, y0, n);
    memcpy(V->prev, rgb + (size_t) (n - 1) * V->w * 3, (size_t) V->w * 3);
    V->have_prev = 1;
    return rc;
}

#define BAND 80

static void rgb565(uint16_t q, uint8_t *d)
{
    d[0] = (uint8_t) ((q >> 11) << 3 | (q >> 13));
    d[1] = (uint8_t) (((q >> 5) & 63) << 2 | ((q >> 9) & 3));
    d[2] = (uint8_t) ((q & 31) << 3 | ((q >> 2) & 7));
}

/* column file -> MFV rows, BAND rows at a time (one read of the file per band) */
static int portrait_finish(mfd_view *V)
{
    const mfd_env *env = V->env;
    if (V->ncols != PW) return MFD_E_IO;
    env->close(V->cf);
    if (!(V->cf = env->open(V->cpath, 0))) return MFD_E_IO;
    uint16_t *band = env->alloc((size_t) BAND * PW * 2);
    if (!band) return MFD_E_MEM;
    int rc = MFD_OK;
    uint8_t *px = V->line, *out = V->line + VW * 3;
    for (int y0 = 0; y0 < VH && !rc; y0 += BAND)
    {
        if (env->seek(V->cf, 0)) { rc = MFD_E_IO; break; }
        for (int k = 0; k < PW; k++)                      /* k-th column written */
        {
            if (env->read(V->cf, V->col, VH * 2) != VH * 2) { rc = MFD_E_IO; break; }
            int tx = V->orient == 8 ? k : PW - 1 - k;
            for (int y = 0; y < BAND; y++) band[(size_t) y * PW + (size_t) tx] = V->col[y0 + y];
        }
        for (int y = 0; y < BAND && !rc; y++)
        {
            memset(px, 0, VW * 3);
            for (int x = 0; x < PW; x++) rgb565(band[(size_t) y * PW + (size_t) x], px + (size_t) (PX0 + x) * 3);
            pack_row(px, out, VW);
            if (env->write(V->f, out, VBW) != VBW) rc = MFD_E_IO;
        }
        if (env->yield) env->yield();
    }
    env->release(band);
    return rc;
}

int mfd_view_end(mfd_view *V)
{
    int rc = MFD_OK;
    if (!V->env) return MFD_OK;                           /* never begun */
    if (V->portrait && V->f && V->cf) rc = portrait_finish(V);
    else if (!V->portrait && V->next_y != VH) rc = MFD_E_IO;
    if (V->cf) V->env->close(V->cf);
    if (V->portrait && V->cpath[0]) V->env->remove(V->cpath);
    if (V->f) V->env->close(V->f);
    if (V->prev) V->env->release(V->prev);
    if (V->line) V->env->release(V->line);
    if (V->col) V->env->release(V->col);
    memset(V, 0, sizeof *V);
    return rc;
}
