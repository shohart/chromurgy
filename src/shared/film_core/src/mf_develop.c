/* SPDX-License-Identifier: GPL-2.0-only
 *
 * The film stage for a whole frame, after M-Film fos_dev.c (stage_key,
 * stage_expose/expose_lin, stage_glow, stage_finish, finish_grain).
 *
 * Upstream works on a 720 x 480 print. Here every size is expressed in
 * "print pixels" of scale s = the frame fitted into 720 x 480, so the camera
 * print is reproduced at s = 1 and a 4000 x 3000 frame gets the same glow
 * radius, vignette and exposure relative to the frame. Deviations from the
 * camera (documented in docs/audit/P01-film-core.md):
 *  - float throughout instead of 1/4096 integers and an 8-bit table;
 *  - grain noise is coordinate-addressed (mf_noise), and above print size it
 *    gets the films.py clump size (grain_size) and the lab amplitude
 *    (the camera's 0.55 is the softening of its 7.2x downscale);
 *  - optical softness (films.py "soft") is applied above print size only.
 */
#include "mf_core.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define PRINT_W 720
#define PRINT_H 480
#define LAB_WIDTH 5184                  /* EOS M picture width: the lab's "full-resolution pixels" */
#define CAMERA_DOWNSCALE (5184.0f / 720.0f)
#define CAMERA_GRAIN_SOFTEN 0.55f

static const float LUMA_I[3] = { 871 / 4096.0f, 2929 / 4096.0f, 296 / 4096.0f };

static float print_scale(int w, int h)
{
    float sx = (float) w / PRINT_W, sy = (float) h / PRINT_H;
    return sx > sy ? sx : sy;
}

static float clamp01(float v) { return v < 0 ? 0 : v > 1 ? 1 : v; }

/* linear sRGB of a blackbody at t kelvin (fos_dev.c cct_rgb) */
static void cct_rgb(float t, float out[3])
{
    float x, y;
    if (t <= 4000) x = -0.2661239e9f / (t * t * t) - 0.2343589e6f / (t * t) + 0.8776956e3f / t + 0.179910f;
    else x = -3.0258469e9f / (t * t * t) + 2.1070379e6f / (t * t) + 0.2226347e3f / t + 0.240390f;
    if (t <= 2222) y = -1.1063814f * x * x * x - 1.34811020f * x * x + 2.18555832f * x - 0.20219683f;
    else if (t <= 4000) y = -0.9549476f * x * x * x - 1.37418593f * x * x + 2.09137015f * x - 0.16748867f;
    else y = 3.0817580f * x * x * x - 5.87338670f * x * x + 3.75112997f * x - 0.37001483f;
    float X = x / y, Y = 1, Z = (1 - x - y) / y;
    out[0] = 3.2406f * X - 1.5372f * Y - 0.4986f * Z;
    out[1] = -0.9689f * X + 1.8758f * Y + 0.0415f * Z;
    out[2] = 0.0557f * X - 0.2040f * Y + 1.0570f * Z;
}

/* the lab scanner: log-average luminance of every fourth print pixel to a
 * key of 0.11 (negatives); slides get what was exposed, +1 EV as upstream */
float mf_scanner_ev(const struct mf_film *film, const float *rgb, int w, int h)
{
    if (film->look.slide) return 1.0f;
    float s = print_scale(w, h);
    int pw = (int) (w / s + 0.5f), ph = (int) (h / s + 0.5f);
    double acc = 0;
    long n = 0;
    for (int py = 0; py < ph; py += 4)
        for (int px = 0; px < pw; px += 4)
        {
            /* the print pixel is the mean of the frame pixels under it */
            int x0 = (int) (px * s), x1 = (int) ((px + 1) * s), y0 = (int) (py * s), y1 = (int) ((py + 1) * s);
            if (x1 <= x0) x1 = x0 + 1;
            if (y1 <= y0) y1 = y0 + 1;
            if (x1 > w) x1 = w;
            if (y1 > h) y1 = h;
            float m[3] = { 0, 0, 0 };
            for (int y = y0; y < y1; y++)
                for (int x = x0; x < x1; x++)
                    for (int c = 0; c < 3; c++) m[c] += clamp01(rgb[3 * ((size_t) y * w + x) + c]);
            float k = 1.0f / (float) ((x1 - x0) * (y1 - y0));
            float l = (m[0] * LUMA_I[0] + m[1] * LUMA_I[1] + m[2] * LUMA_I[2]) * k;
            int v = (int) (l * 4096);                       /* upstream's histogram bins */
            v = v < 0 ? 0 : v > 4096 ? 4096 : v;
            acc += (double) logf(v / 4096.0f + 1e-4f);
            n++;
        }
    float key = n ? expf((float) (acc / (double) n)) : 0.11f;
    float ev = log2f(0.11f / key);
    return ev < -2 ? -2 : ev > 3.5f ? 3.5f : ev;
}

/* separable gaussian, edges clamped; tmp: max(w, h) floats; one channel of stride 1 or 3 */
static void kernel(float sigma, float *k, int *radius)
{
    int r = (int) ceilf(3 * sigma);
    if (r < 1) r = 1;
    if (r > 64) r = 64;
    float sum = 0;
    for (int i = -r; i <= r; i++) sum += k[i + r] = expf(-0.5f * (float) (i * i) / (sigma * sigma));
    for (int i = 0; i <= 2 * r; i++) k[i] /= sum;
    *radius = r;
}

static void blur_plane(float *p, int w, int h, int stride, float sigma, float *tmp)
{
    float k[129];
    int r;
    kernel(sigma, k, &r);
    for (int y = 0; y < h; y++)
    {
        float *row = p + (size_t) y * w * stride;
        for (int x = 0; x < w; x++)
        {
            float a = 0;
            for (int i = -r; i <= r; i++)
            {
                int xx = x + i < 0 ? 0 : x + i >= w ? w - 1 : x + i;
                a += k[i + r] * row[(size_t) xx * stride];
            }
            tmp[x] = a;
        }
        for (int x = 0; x < w; x++) row[(size_t) x * stride] = tmp[x];
    }
    for (int x = 0; x < w; x++)
    {
        for (int y = 0; y < h; y++)
        {
            float a = 0;
            for (int i = -r; i <= r; i++)
            {
                int yy = y + i < 0 ? 0 : y + i >= h ? h - 1 : y + i;
                a += k[i + r] * p[((size_t) yy * w + x) * stride];
            }
            tmp[y] = a;
        }
        for (int y = 0; y < h; y++) p[((size_t) y * w + x) * stride] = tmp[y];
    }
}

/* halation: highlights over hal_thr, averaged in cells of 4 x 4 print
 * pixels, [1 2 1] twice each way, read back bilinearly between cell centres */
static float *glow_grid(const float *lin, int w, int h, float s, float thr, int *gw_out, int *gh_out)
{
    float cell = 4 * s;
    int gw = (int) ceilf(w / cell), gh = (int) ceilf(h / cell);
    if (gw < 2) gw = 2;
    if (gh < 2) gh = 2;
    float *g = calloc((size_t) gw * gh, sizeof(float));
    int *cnt = calloc((size_t) gw * gh, sizeof(int));
    float *tmp = malloc(sizeof(float) * (size_t) (gw > gh ? gw : gh));
    if (!g || !cnt || !tmp) { free(g); free(cnt); free(tmp); return NULL; }
    for (int y = 0; y < h; y++)
    {
        int cy = (int) (y / cell);
        if (cy >= gh) cy = gh - 1;
        for (int x = 0; x < w; x++)
        {
            int cx = (int) (x / cell);
            if (cx >= gw) cx = gw - 1;
            const float *p = lin + 3 * ((size_t) y * w + x);
            float l = p[0] * LUMA_I[0] + p[1] * LUMA_I[1] + p[2] * LUMA_I[2];
            if (l > thr) g[cy * gw + cx] += l - thr;
            cnt[cy * gw + cx]++;
        }
    }
    for (int i = 0; i < gw * gh; i++) if (cnt[i]) g[i] /= (float) cnt[i];
    for (int pass = 0; pass < 2; pass++)
    {
        for (int y = 0; y < gh; y++)
        {
            float *r = g + y * gw;
            for (int x = 0; x < gw; x++)
                tmp[x] = (r[x > 0 ? x - 1 : 0] + 2 * r[x] + r[x < gw - 1 ? x + 1 : gw - 1]) * 0.25f;
            memcpy(r, tmp, sizeof(float) * (size_t) gw);
        }
        for (int x = 0; x < gw; x++)
        {
            for (int y = 0; y < gh; y++)
                tmp[y] = (g[(y > 0 ? y - 1 : 0) * gw + x] + 2 * g[y * gw + x] + g[(y < gh - 1 ? y + 1 : gh - 1) * gw + x]) * 0.25f;
            for (int y = 0; y < gh; y++) g[y * gw + x] = tmp[y];
        }
    }
    free(cnt);
    free(tmp);
    *gw_out = gw;
    *gh_out = gh;
    return g;
}

/* cell and weight of the next for frame coordinate x (centres at cell*(j+0.5)) */
static void glow_pos(int x, float cell, int n, int *j, float *f)
{
    float u = (x + 0.5f) / cell - 0.5f;
    if (u <= 0) { *j = 0; *f = 0; return; }
    int k = (int) u;
    if (k >= n - 1) { *j = n - 2; *f = 1; return; }
    *j = k;
    *f = u - (float) k;
}

static float noise_unit(uint64_t seed, int x, int y, int ch)
{
    return (float) mf_noise(seed, (uint32_t) x, (uint32_t) y, (uint32_t) ch) * (1.0f / 32768);
}

/* one grain field, clumped by a gaussian of sigma output px and rescaled to
 * the white noise's spread, or plain white noise when sigma < 0.5 */
static int grain_field(float *f, int w, int h, uint64_t seed, int ch, float sigma, float *tmp)
{
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++) f[(size_t) y * w + x] = noise_unit(seed, x, y, ch);
    if (sigma < 0.5f) return 0;
    float k[129];
    int r;
    kernel(sigma, k, &r);
    float s2 = 0;
    for (int i = 0; i <= 2 * r; i++) s2 += k[i] * k[i];
    blur_plane(f, w, h, 1, sigma, tmp);
    float norm = 1 / s2;                    /* 2-D std of the sum = std * sum(k^2) per axis */
    for (size_t i = 0; i < (size_t) w * h; i++) f[i] *= norm;
    return 0;
}

int mf_develop_frame(const struct mf_film *film, const mf_table *table, float *rgb, int w, int h,
                     const mf_develop_params *p)
{
    if (!film || !table || !rgb || w < 2 || h < 2 || !p) return MF_E_INVALID_ARG;
    const struct mf_look *L = &film->look;
    const size_t n = (size_t) w * h;
    const float s = print_scale(w, h);
    const float ref = (float) (p->reference_width > 0 ? p->reference_width : LAB_WIDTH);
    const float lab_px = ref / (float) w;          /* lab pixels per output pixel */
    float *tmp = malloc(sizeof(float) * (size_t) (w > h ? w : h));
    if (!tmp) return MF_E_INVALID_ARG;

    /* 1. scanner exposure and the film's balance (stage_key, expose_lin) */
    float ev = mf_scanner_ev(film, rgb, w, h);
    float k = exp2f(ev + L->ev + p->exposure_ev);
    float bal[3] = { 1, 1, 1 };
    if (L->balance != 5500)
    {
        float a[3], b[3];
        cct_rgb(5500, a);
        cct_rgb((float) L->balance, b);
        for (int c = 0; c < 3; c++) bal[c] = a[c] / b[c];
        float g = a[1] / b[1];
        for (int c = 0; c < 3; c++) bal[c] /= g;
    }
    for (size_t i = 0; i < n; i++)
        for (int c = 0; c < 3; c++)
        {
            float v = clamp01(rgb[3 * i + c]) * k * bal[c];
            rgb[3 * i + c] = v > 16 ? 16 : v;
        }

    /* 2. optical softness, above print size only */
    float soft = film->soft * p->softness_scale / lab_px;
    if (soft >= 0.3f && lab_px < CAMERA_DOWNSCALE)
        for (int c = 0; c < 3; c++) blur_plane(rgb + c, w, h, 3, soft, tmp);

    /* 3. halation glow and vignette, then the film's table (stage_finish) */
    int gw = 0, gh = 0;
    float *glow = NULL;
    float hal = L->halation * p->halation_scale;
    if (hal > 0)
    {
        glow = glow_grid(rgb, w, h, s, L->hal_thr, &gw, &gh);
        if (!glow) { free(tmp); return MF_E_INVALID_ARG; }
    }
    const float cell = 4 * s;
    for (int y = 0; y < h; y++)
    {
        float ty = 2.0f * y / (h - 1) - 1;
        int gy = 0;
        float fy = 0;
        if (glow) glow_pos(y, cell, gh, &gy, &fy);
        for (int x = 0; x < w; x++)
        {
            float tx = 2.0f * x / (w - 1) - 1;
            float vig = 1 - 0.06f * tx * tx - 0.06f * ty * ty;
            float *px = rgb + 3 * ((size_t) y * w + x);
            float lin[3] = { px[0] * vig, px[1] * vig, px[2] * vig };
            if (glow)
            {
                int gx;
                float fx;
                glow_pos(x, cell, gw, &gx, &fx);
                const float *g0 = glow + gy * gw + gx, *g1 = g0 + gw;
                float gv = (g0[0] * (1 - fx) + g0[1] * fx) * (1 - fy) + (g1[0] * (1 - fx) + g1[1] * fx) * fy;
                for (int c = 0; c < 3; c++) lin[c] += gv * hal * L->hal_tint[c];
            }
            mf_table_apply(table, lin, px);
        }
    }
    free(glow);

    /* 4. grain, strongest in the mid tones (finish_grain) */
    float amount = L->grain * p->grain_scale;
    if (amount > 0)
    {
        float lp = lab_px < 1 ? 1 : lab_px;
        float soften = powf(CAMERA_GRAIN_SOFTEN, logf(lp) / logf(CAMERA_DOWNSCALE));
        float sigma = L->grain_size / lab_px;
        float amp = amount * soften * (65025.0f * 256 / (64.0f * 65536));   /* upstream's fixed-point scale */
        float *shared = malloc(sizeof(float) * n), *own = L->mono ? NULL : malloc(sizeof(float) * n);
        if (!shared || (!L->mono && !own)) { free(shared); free(own); free(tmp); return MF_E_INVALID_ARG; }
        grain_field(shared, w, h, p->grain_seed, 0, sigma, tmp);
        float *wgt = malloc(sizeof(float) * n);
        if (!wgt) { free(shared); free(own); free(tmp); return MF_E_INVALID_ARG; }
        for (size_t i = 0; i < n; i++)
        {
            const float *o = rgb + 3 * i;
            float l = clamp01(o[0] * (54 / 256.0f) + o[1] * (183 / 256.0f) + o[2] * (19 / 256.0f));
            wgt[i] = l * (1 - l) * amp;
        }
        for (int c = 0; c < 3; c++)
        {
            if (!L->mono) grain_field(own, w, h, p->grain_seed, 1 + c, sigma, tmp);
            for (size_t i = 0; i < n; i++)
            {
                float nz = L->mono ? shared[i] : (shared[i] * 3 + own[i] * 2) * 0.25f;
                rgb[3 * i + c] = clamp01(rgb[3 * i + c] + nz * wgt[i]);
            }
        }
        free(wgt);
        free(shared);
        free(own);
    }
    else
        for (size_t i = 0; i < 3 * n; i++) rgb[i] = clamp01(rgb[i]);
    free(tmp);
    return MF_OK;
}
