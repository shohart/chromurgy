/* SPDX-License-Identifier: GPL-2.0-only
 * The fixed-point streaming stage (mf_fx) against the float whole-frame
 * stage (mf_develop_frame) on the same quantised input, for every film:
 * 8-bit display codes within MAX_DIFF, mean within MEAN_DIFF; scanner EV
 * within EV_DIFF; rows rendered in any order give the same pixels; sizes
 * that need a spatial kernel are refused. */
#include "mf_core.h"
#include "common.h"
#include <math.h>
#include <string.h>

#define MAX_DIFF 2
#define MEAN_DIFF 0.25
#define EV_DIFF 0.01
#define STRIP 16

/* scene-linear test frame in Q15: a log ramp across (deep shadow to clipped
 * white), hue bands down, clipped highlight blocks for halation */
static void scene(uint16_t *q, int w, int h)
{
    for (int y = 0; y < h; y++)
        for (int x = 0; x < w; x++)
        {
            float t = (float) x / (float) (w - 1), u = (float) y / (float) (h - 1);
            float l = 0.0005f * powf(2.4f / 0.0005f, t);                /* 0.0005 .. 2.4, clips at 1 */
            float c[3] = { 0.6f + 0.4f * sinf(6.3f * u), 0.6f + 0.4f * sinf(6.3f * u + 2.1f),
                           0.6f + 0.4f * sinf(6.3f * u + 4.2f) };
            if ((x / (w / 8)) % 3 == 1 && (y / (h / 6)) % 2 == 0) { l = 1.5f; c[0] = c[1] = c[2] = 1; }
            for (int k = 0; k < 3; k++)
            {
                float v = l * c[k] * 32768 + 0.5f;
                q[3 * ((size_t) y * w + x) + k] = (uint16_t) (v > 65535 ? 65535 : v);
            }
        }
}

static double worst_mean, ev_worst;
static int worst_max, cases, refused;

static int run_case(const struct mf_film *film, int w, int h, float grain_scale, float soft_scale)
{
    mf_develop_params p = { .grain_seed = 0x1234567890abcdefULL, .grain_scale = grain_scale,
                            .halation_scale = 1, .softness_scale = soft_scale, .exposure_ev = 0,
                            .reference_width = 0 };
    mf_fx_look look;
    mf_develop_sizes sz;
    int k = mf_develop_kernels(film, &p, w, &sz);
    int rc = mf_fx_look_bake(film, &p, w, h, &look);
    if (k) { CHECK(rc == MF_E_UNSUPPORTED); refused++; return 0; }
    CHECK(rc == MF_OK);

    size_t n = (size_t) w * h;
    uint16_t *in = malloc(n * 3 * sizeof *in), *out = malloc(n * 3 * sizeof *out),
             *out2 = malloc(n * 3 * sizeof *out2);
    float *ref = malloc(n * 3 * sizeof *ref);
    static mf_table table;
    CHECK(in && out && out2 && ref);
    scene(in, w, h);
    for (size_t i = 0; i < 3 * n; i++) ref[i] = in[i] / 32768.0f;
    mf_table_from_film(film, &table);
    float ev_ref = mf_scanner_ev(film, ref, w, h);
    CHECK(mf_develop_frame(film, &table, ref, w, h, &p) == MF_OK);

    size_t need = mf_fx_ctx_size(w, h);
    uint64_t *mem = malloc(need);
    mf_fx *fx;
    CHECK(mem && mf_fx_begin(mem, need, &look, &table.v[0][0], p.grain_seed, &fx) == MF_OK);
    CHECK(mf_fx_render_rows(fx, in, 3 * (size_t) w, 0, 1, out, 3 * (size_t) w) == MF_E_INVALID_ARG);  /* passes in order */
    for (int y = 0; y < h; y += STRIP)
        CHECK(mf_fx_scan_rows(fx, in + 3 * (size_t) y * w, 3 * (size_t) w, y, y + STRIP > h ? h - y : STRIP) == MF_OK);
    double ev = mf_fx_scanner_ev_q16(fx) / 65536.0;
    for (int y = 0; y < h; y += STRIP)
        CHECK(mf_fx_glow_rows(fx, in + 3 * (size_t) y * w, 3 * (size_t) w, y, y + STRIP > h ? h - y : STRIP) == MF_OK);
    for (int y = 0; y < h; y += STRIP)                                  /* forwards */
    {
        int m = y + STRIP > h ? h - y : STRIP;
        CHECK(mf_fx_render_rows(fx, in + 3 * (size_t) y * w, 3 * (size_t) w, y, m, out + 3 * (size_t) y * w,
                                3 * (size_t) w) == MF_OK);
    }
    for (int y = (h - 1) / 7 * 7; y >= 0; y -= 7)                       /* other strips, backwards */
    {
        int m = y + 7 > h ? h - y : 7;
        CHECK(mf_fx_render_rows(fx, in + 3 * (size_t) y * w, 3 * (size_t) w, y, m, out2 + 3 * (size_t) y * w,
                                3 * (size_t) w) == MF_OK);
    }
    CHECK(memcmp(out, out2, n * 3 * sizeof *out) == 0);

    long sum = 0;
    int mx = 0;
    size_t at = 0;
    for (size_t i = 0; i < 3 * n; i++)
    {
        int a = (int) lrintf(ref[i] * 255), b = (int) ((out[i] * 255u + 32767u) / 65535u);
        int d = abs(a - b);
        sum += d;
        if (d > mx) { mx = d; at = i; }
    }
    double mean = (double) sum / (3.0 * n);
    double evd = fabs(ev - (double) ev_ref);
    if (mx > MAX_DIFF || mean > MEAN_DIFF || evd > EV_DIFF)
        fprintf(stderr, "%-16s %4dx%-4d grain %.0f: max %d at px %zu (x %zu y %zu c %zu), mean %.3f, ev %.4f vs %.4f\n",
                film->key, w, h, (double) grain_scale, mx, at / 3, at / 3 % (size_t) w, at / 3 / (size_t) w, at % 3, mean,
                ev, (double) ev_ref);
    CHECK(mx <= MAX_DIFF && mean <= MEAN_DIFF && evd <= EV_DIFF);
    if (mx > worst_max) worst_max = mx;
    if (mean > worst_mean) worst_mean = mean;
    if (evd > ev_worst) ev_worst = evd;
    cases++;
    free(mem);
    free(in);
    free(out);
    free(out2);
    free(ref);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 2) return 2;
    /* integer helpers */
    for (uint32_t x = 1; x < 2000000000u; x = x * 3 + 7)
        CHECK(fabs(mf_fx_log2_q16(x) / 65536.0 - log2((double) x)) < 2e-5);
    for (int32_t qv = -20 * 65536; qv < 14 * 65536; qv += 4099)
    {
        double want = exp2(qv / 65536.0) * 65536;
        CHECK(fabs(mf_fx_exp2_q16(qv) - want) <= 1 + want * 2e-5);
    }

    size_t len;
    uint8_t *bundle = read_file(argv[1], &len);
    mf_bundle bb;
    CHECK(mf_bundle_parse(bundle, len, &bb) == MF_OK);
    for (int i = 0; i < bb.nfilms; i++)
    {
        const struct mf_film *f = &bb.films[i];
        if (run_case(f, 720, 480, 1, 1)) return 1;
        if (run_case(f, 1200, 800, 1, 1)) return 1;
        if (i % 6 == 0)
        {
            if (run_case(f, 720, 480, 0, 1)) return 1;
            if (run_case(f, 1760, 1173, 1, 1)) return 1;
            if (run_case(f, 600, 900, 1, 1)) return 1;                               /* portrait */
        }
    }
    /* outputs that need a spatial kernel are refused, not approximated */
    int before = refused;
    if (run_case(mf_bundle_find(&bb, "cinestill800t"), 1760, 1173, 1, 3)) return 1;   /* softness x3 */
    if (run_case(mf_bundle_find(&bb, "portra400"), 3000, 2000, 1, 1)) return 1;
    CHECK(refused == before + 2);
    printf("fx: %d cases, worst max %d, worst mean %.3f (8-bit), worst ev %.4f stop, %d refused\n",
           cases, worst_max, worst_mean, ev_worst, refused);
    mf_bundle_free(&bb);
    free(bundle);
    return 0;
}
