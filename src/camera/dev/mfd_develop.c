/* SPDX-License-Identifier: GPL-2.0-only
 * The camera's offline developer, one frame:
 *
 *   A  read the DNG once, in order, hashing every byte; bin each 4x4 raw
 *      block into one "quarter" pixel (sums of the Bayer samples), apply the
 *      fitted LibRaw daylight transform (black, white balance, clip, camera
 *      -> sRGB matrix, clip) and keep the quarter rows in a ring; resample
 *      the output rows through the lens table (bilinear) into scene-linear
 *      Q15, write them to a temp file and run the mf_fx scan pass on them
 *   B  mf_fx glow pass over the temp file
 *   C  mf_fx render pass over the temp file -> 8-bit -> baseline JPEG
 *
 * The output frame is the camera JPEG's framing (cam->jpeg_w x jpeg_h)
 * scaled to out_w x out_h; the lens table maps that frame to the raw.
 * Memory: ring of quarter rows (the widest span the lens needs per strip)
 * + strips + the mf_fx context: ~0.7 MB at 1024x768 at the wide end. */
#include <string.h>
#include "mfd.h"

#define STRIP 8
#define R2_SHIFT 40

static int32_t clampi(int32_t v, int32_t lo, int32_t hi) { return v < lo ? lo : v > hi ? hi : v; }

/* ------------------------------------------------------------------ lens */

static void lens_eval(const mfd_lens *L, uint32_t r2inv, int32_t dx, int32_t dy, int32_t *rx, int32_t *ry)
{
    int64_t d2 = (int64_t) dx * dx + (int64_t) dy * dy;                   /* Q16 px^2 */
    int32_t r2 = (int32_t) (((uint64_t) (d2 >> 8) * r2inv) >> (R2_SHIFT - 8 - 8));   /* Q16 */
    int64_t t = L->k3_q24;
    t = L->k2_q24 + ((t * r2) >> 16);
    t = L->k1_q24 + ((t * r2) >> 16);
    t = (1 << 24) + ((t * r2) >> 16);
    int64_t f = ((int64_t) L->s_q24 * t) >> 24;                           /* Q24 */
    *rx = L->cx_q8 + (int32_t) (((int64_t) dx * f) >> 24);
    *ry = L->cy_q8 + (int32_t) (((int64_t) dy * f) >> 24);
}

typedef struct { const mfd_lens *a, *b; int32_t t_q16; uint32_t r2inv; int32_t j0x, j0y; } lens_sel;

static int lens_select(const mfd_camera *cam, int32_t focal_q8, lens_sel *s)
{
    if (cam->nlens < 1 || cam->nlens > MFD_MAX_LENS) return MFD_E_LENS;
    uint32_t n2 = (uint32_t) (cam->jpeg_w / 2) * (uint32_t) (cam->jpeg_w / 2)
                + (uint32_t) (cam->jpeg_h / 2) * (uint32_t) (cam->jpeg_h / 2);   /* |J0|^2, px^2 */
    /* r2inv = 2^40 / (|J0|^2 * 2^16): r2 (Q16) = d2 (Q16 px^2) / |J0|^2. 32-bit divides only. */
    uint32_t q = 0, rem = 0;
    for (int bit = 63; bit >= 0; bit--)             /* long division of 2^(40-16) by n2 */
    {
        rem = rem << 1 | (bit == R2_SHIFT - 16 ? 1u : 0u);
        q <<= 1;
        if (rem >= n2) { rem -= n2; q |= 1; }
        if (bit < R2_SHIFT - 16 - 24) break;        /* keep 24 fractional bits */
    }
    s->r2inv = q;                                   /* = 2^48 / n2, used with >> 32 below */
    s->j0x = cam->jpeg_w * 128, s->j0y = cam->jpeg_h * 128;
    const mfd_lens *L = cam->lens;
    int n = cam->nlens;
    if (focal_q8 <= L[0].focal_q8) { s->a = s->b = &L[0]; s->t_q16 = 0; return MFD_OK; }
    if (focal_q8 >= L[n - 1].focal_q8) { s->a = s->b = &L[n - 1]; s->t_q16 = 0; return MFD_OK; }
    for (int i = 1; i < n; i++)
        if (L[i].focal_q8 >= focal_q8)
        {
            s->a = &L[i - 1], s->b = &L[i];
            uint32_t span = (uint32_t) (L[i].focal_q8 - L[i - 1].focal_q8);
            s->t_q16 = span ? (int32_t) (((uint32_t) (focal_q8 - L[i - 1].focal_q8) << 16) / span) : 0;
            return MFD_OK;
        }
    return MFD_E_LENS;
}

static void lens_map(const lens_sel *s, int32_t jx, int32_t jy, int32_t *rx, int32_t *ry)
{
    int32_t ax, ay, bx, by;
    lens_eval(s->a, s->r2inv, jx - s->j0x, jy - s->j0y, &ax, &ay);
    if (s->b == s->a || !s->t_q16) { *rx = ax, *ry = ay; return; }
    lens_eval(s->b, s->r2inv, jx - s->j0x, jy - s->j0y, &bx, &by);
    *rx = ax + (int32_t) (((int64_t) (bx - ax) * s->t_q16) >> 16);
    *ry = ay + (int32_t) (((int64_t) (by - ay) * s->t_q16) >> 16);
}

int mfd_lens_at(const mfd_camera *cam, int32_t focal_q8, int32_t jx_q8, int32_t jy_q8, int32_t *rx_q8,
                int32_t *ry_q8)
{
    lens_sel s;
    int rc = lens_select(cam, focal_q8, &s);
    if (rc) return rc;
    lens_map(&s, jx_q8, jy_q8, rx_q8, ry_q8);
    return MFD_OK;
}

/* ------------------------------------------------------------------ the frame */

typedef struct dev {
    const mfd_env *env;
    const mfd_job *job;
    mfd_dng d;
    lens_sel lens;
    void *f;
    mfd_sha sha;
    uint32_t raw_row;           /* next raw row to read */
    uint8_t *rawbuf;            /* 4 raw rows */
    int qw, qh;                 /* quarter image */
    uint16_t *ring;             /* R quarter rows, linear sRGB Q15 x3 */
    int ring_n, q_next;         /* q rows produced: 0 .. q_next-1 */
    int16_t *rmin, *rmax;       /* per output row: quarter rows needed */
    int32_t *jx;                /* per output column: JPEG-frame x (Q8) */
    int32_t *acc;               /* qw x 3 sums while binning */
    int32_t *gq;                /* lens grid for one output row: (qx, qy) Q8 every GRID columns */
    uint32_t mem;
    mfd_result *res;
    long last_yield;
} dev;

#define GRID 16                 /* the lens map is evaluated every GRID output columns, linear between */

/* let the camera's other tasks run about every 100 ms of work (msleep sleeps a
 * whole 10 ms tick: yielding after every 8-row strip cost ~3 s a frame) */
static void maybe_yield(dev *D)
{
    const mfd_env *env = D->env;
    if (!env->yield) return;
    long now = env->tick();
    if (now - D->last_yield < 100) return;
    env->yield();
    D->res->yields++;
    long after = env->tick();
    D->res->ms_yield += after - now;
    D->last_yield = after;
}

static void *xalloc(dev *D, size_t n)
{
    void *p = D->env->alloc(n);
    if (p) D->mem += (uint32_t) n;
    return p;
}

static int read_hash(dev *D, void *buf, long n)
{
    long t = D->env->tick();
    long got = D->env->read(D->f, buf, n);
    D->res->ms_dng_io += D->env->tick() - t;
    if (got != n) return MFD_E_IO;
    if (D->job->hash) mfd_sha_update(&D->sha, buf, (size_t) n);
    return MFD_OK;
}

static void progress(const mfd_job *job, int permille)
{
    if (job->progress) *job->progress = permille;
}

static int cancelled(const mfd_job *job) { return job->cancel && *job->cancel; }

/* quarter row qi from raw visible rows 4qi..4qi+3. Four pixels are 6 packed
 * bytes; ActiveArea left is even, so in each raw row the 4-pixel group of a
 * quarter pixel starts on a byte boundary and its colours are fixed: even
 * columns cfa[2 * (row & 1)], odd ones cfa[2 * (row & 1) + 1]. */
static int produce_q(dev *D)
{
    const mfd_dng *d = &D->d;
    uint32_t want = d->act_top + 4u * (uint32_t) D->q_next;
    uint8_t *rows = D->rawbuf;
    int rc;
    while (D->raw_row < want)                       /* margin rows: hash only */
    {
        if ((rc = read_hash(D, rows, (long) d->row_bytes))) return rc;
        D->raw_row++;
    }
    if ((rc = read_hash(D, rows, (long) (4 * d->row_bytes)))) return rc;
    D->raw_row += 4;
    long t = D->env->tick();
    const mfd_camera *cam = D->job->cam;
    uint16_t *out = D->ring + (size_t) ((uint32_t) D->q_next % (uint32_t) D->ring_n) * D->qw * 3;
    int32_t *acc = D->acc;
    int qw = D->qw;
    memset(acc, 0, sizeof(int32_t) * 3 * (size_t) qw);
    for (int k = 0; k < 4; k++)
    {
        uint32_t ry = d->act_top + 4u * (uint32_t) D->q_next + (uint32_t) k;
        int ce = d->cfa[(ry & 1) * 2], co = d->cfa[(ry & 1) * 2 + 1];
        const uint8_t *p = rows + (size_t) k * d->row_bytes + (d->act_left >> 1) * 3;
        int32_t *a = acc;
        for (int qx = 0; qx < qw; qx++, p += 6, a += 3)
        {
            int32_t v0 = p[0] << 4 | p[1] >> 4, v1 = (p[1] & 15) << 8 | p[2];
            int32_t v2 = p[3] << 4 | p[4] >> 4, v3 = (p[4] & 15) << 8 | p[5];
            a[ce] += v0 + v2;
            a[co] += v1 + v3;
        }
    }
    /* samples per colour in a 4x4 block: 4 x (its count in the 2x2 pattern) */
    int cnt[3] = {0, 0, 0}, sh[3];
    for (int i = 0; i < 4; i++) cnt[d->cfa[i]] += 4;
    for (int c = 0; c < 3; c++) sh[c] = cnt[c] == 8 ? 3 : cnt[c] == 4 ? 2 : cnt[c] == 16 ? 4 : 0;
    int32_t black = (int32_t) d->black;
    for (int qx = 0; qx < qw; qx++)
    {
        int32_t lin[3];
        for (int ch = 0; ch < 3; ch++)
        {
            int64_t v = ((int64_t) (acc[3 * qx + ch] - cnt[ch] * black) * cam->wb_q16[ch]) >> (16 + sh[ch]);
            lin[ch] = clampi((int32_t) v, 0, 32768);
        }
        for (int ch = 0; ch < 3; ch++)
        {
            int32_t v = (cam->m_q12[3 * ch] * lin[0] + cam->m_q12[3 * ch + 1] * lin[1] + cam->m_q12[3 * ch + 2] * lin[2]
                         + 2048) >> 12;
            out[3 * qx + ch] = (uint16_t) clampi(v, 0, 32768);
        }
    }
    D->q_next++;
    D->res->ms_bin += D->env->tick() - t;
    return MFD_OK;
}

static int32_t jy_of(dev *D, int v) { return (int32_t) (((uint32_t) (2 * v + 1) * (uint32_t) D->job->cam->jpeg_h * 128u) / (uint32_t) D->job->out_h); }

/* sample the ring bilinearly at quarter coordinates (Q8) */
static void sample(dev *D, int32_t qx, int32_t qy, uint16_t *px)
{
    int32_t x0 = qx >> 8, y0 = qy >> 8, fx = qx & 255, fy = qy & 255;
    if (x0 < 0) x0 = 0, fx = 0;
    if (x0 > D->qw - 2) { fx = x0 >= D->qw - 1 ? 255 : fx; x0 = D->qw - 2; }
    if (y0 < 0) y0 = 0, fy = 0;
    if (y0 > D->qh - 2) { fy = y0 >= D->qh - 1 ? 255 : fy; y0 = D->qh - 2; }
    const uint16_t *a = D->ring + (size_t) ((uint32_t) y0 % (uint32_t) D->ring_n) * D->qw * 3 + 3 * x0;
    const uint16_t *b = D->ring + (size_t) ((uint32_t) (y0 + 1) % (uint32_t) D->ring_n) * D->qw * 3 + 3 * x0;
    for (int c = 0; c < 3; c++)
    {
        int32_t top = a[c] * (256 - fx) + a[3 + c] * fx;
        int32_t bot = b[c] * (256 - fx) + b[3 + c] * fx;
        px[c] = (uint16_t) ((top * (256 - fy) + bot * fy + 32768) >> 16);
    }
}

static void quarter_of(dev *D, int u, int v, int32_t *qx, int32_t *qy)
{
    int32_t rx, ry;
    lens_map(&D->lens, D->jx[u], jy_of(D, v), &rx, &ry);
    *qx = (rx - 512) >> 2;                          /* quarter pixel i is centred on raw 4i + 2 */
    *qy = (ry - 512) >> 2;
}

int mfd_develop(const mfd_env *env, const mfd_job *job, mfd_result *res)
{
    dev D;
    int rc = MFD_OK;
    long t0 = env->tick(), t1;
    memset(&D, 0, sizeof D);
    memset(res, 0, sizeof *res);
    D.env = env, D.job = job, D.res = res, D.last_yield = t0;
    int W = job->out_w, H = job->out_h;
    size_t row_px = 3 * (size_t) W;
    uint16_t *lin = 0, *disp = 0;
    uint8_t *rgb8 = 0, *hdr = 0;
    void *ctx = 0, *tmp = 0, *jf = 0;
    mfd_jpeg *jp = 0;
    mfd_view *vw = 0;
    mf_fx *fx = 0;

    if (!(D.f = env->open(job->dng_path, 0))) return MFD_E_IO;
    mfd_sha_init(&D.sha);
    /* header: everything before the raw strip (the IFDs and the thumbnail) */
    uint8_t head[8];
    if (env->read(D.f, head, 8) != 8) { rc = MFD_E_IO; goto out; }
    {
        /* the strip offset is not known yet: read a generous header, then re-read in order */
        size_t hl = 65536;
        if (!(hdr = xalloc(&D, hl))) { rc = MFD_E_MEM; goto out; }
        memcpy(hdr, head, 8);
        long got = env->read(D.f, hdr + 8, (long) hl - 8);
        if (got < 0) { rc = MFD_E_IO; goto out; }
        if ((rc = mfd_dng_parse(hdr, (size_t) got + 8, &D.d))) goto out;
        if (D.d.strip_off > hl || D.d.vis_w < 16 || D.d.vis_h < 16) { rc = MFD_E_DNG; goto out; }
        if (job->hash) mfd_sha_update(&D.sha, hdr, D.d.strip_off);
        if (env->seek(D.f, (long) D.d.strip_off)) { rc = MFD_E_IO; goto out; }
        env->release(hdr), hdr = 0, D.mem -= (uint32_t) hl;
    }
    if (!D.d.focal_den) { rc = MFD_E_LENS; goto out; }
    res->focal_q8 = (int32_t) ((D.d.focal_num * 256u + D.d.focal_den / 2) / D.d.focal_den);
    if ((rc = lens_select(job->cam, res->focal_q8, &D.lens))) goto out;
    D.qw = (int) (D.d.vis_w / 4), D.qh = (int) (D.d.vis_h / 4);

    /* geometry tables: JPEG-frame x per output column, quarter rows needed per output row */
    D.jx = xalloc(&D, sizeof(int32_t) * (size_t) W);
    D.rmin = xalloc(&D, sizeof(int16_t) * (size_t) H);
    D.rmax = xalloc(&D, sizeof(int16_t) * (size_t) H);
    if (!D.jx || !D.rmin || !D.rmax) { rc = MFD_E_MEM; goto out; }
    for (int u = 0; u < W; u++)
        D.jx[u] = (int32_t) (((uint32_t) (2 * u + 1) * (uint32_t) job->cam->jpeg_w * 128u) / (uint32_t) W);
    for (int v = 0; v < H; v++)
    {
        int32_t lo = 1 << 30, hi = -(1 << 30), qx, qy;
        for (int u = 0;; u += 16)
        {
            if (u >= W) u = W - 1;
            quarter_of(&D, u, v, &qx, &qy);
            if (qy < lo) lo = qy;
            if (qy > hi) hi = qy;
            if (u == W - 1) break;
        }
        D.rmin[v] = (int16_t) clampi((lo >> 8) - 2, 0, D.qh - 1);
        D.rmax[v] = (int16_t) clampi((hi >> 8) + 3, 0, D.qh - 1);
    }
    int span = 0;
    for (int v0 = 0; v0 < H; v0 += STRIP)
    {
        int lo = D.qh, hi = 0;
        for (int v = v0; v < v0 + STRIP && v < H; v++)
        {
            if (D.rmin[v] < lo) lo = D.rmin[v];
            if (D.rmax[v] > hi) hi = D.rmax[v];
        }
        /* rows below an earlier strip's low bound are still kept until passed */
        if (hi - lo + 1 > span) span = hi - lo + 1;
    }
    D.ring_n = span + 2;
    if (D.ring_n > D.qh) D.ring_n = D.qh;
    res->ring_rows = (uint32_t) D.ring_n;
    res->ring_bytes = (uint32_t) D.ring_n * (uint32_t) D.qw * 6u;
    D.ring = xalloc(&D, res->ring_bytes);
    D.rawbuf = xalloc(&D, 4 * (size_t) D.d.row_bytes);
    D.acc = xalloc(&D, sizeof(int32_t) * 3 * (size_t) D.qw);
    D.gq = xalloc(&D, sizeof(int32_t) * 2 * (size_t) (W / GRID + 2));
    if (!D.acc || !D.gq) { rc = MFD_E_MEM; goto out; }
    lin = xalloc(&D, row_px * STRIP * 2);
    disp = xalloc(&D, row_px * STRIP * 2);
    rgb8 = xalloc(&D, row_px * STRIP);
    size_t ctx_len = mf_fx_ctx_size(W, H);
    ctx = xalloc(&D, ctx_len);
    jp = job->jpeg_path ? xalloc(&D, mfd_jpeg_size()) : 0;
    vw = job->mfv_path ? xalloc(&D, mfd_view_size()) : 0;
    /* zeroed: the clean-up below ends the view even when mfd_view_begin never
     * ran (stop or error before the render pass). Camera heap is not zeroed:
     * 0.4.2 closed and freed garbage there and the camera died on "stop". */
    if (vw) memset(vw, 0, mfd_view_size());
    if (jp) memset(jp, 0, mfd_jpeg_size());
    if (!D.ring || !D.rawbuf || !lin || !disp || !rgb8 || !ctx || (job->jpeg_path && !jp) || (job->mfv_path && !vw))
    { rc = MFD_E_MEM; goto out; }
    res->mem_peak = D.mem;
    if ((rc = mf_fx_begin(ctx, ctx_len, job->look, job->table, job->seed, &fx)) != MF_OK) goto out;
    if (!(tmp = env->open(job->tmp_path, 1))) { rc = MFD_E_IO; goto out; }

    /* A: raw -> quarter ring -> lens -> linear rows (temp file) + scan pass */
    long ms_scan = 0;
    for (int v0 = 0; v0 < H; v0 += STRIP)
    {
        int n = v0 + STRIP > H ? H - v0 : STRIP, need = 0;
        for (int v = v0; v < v0 + n; v++)
            if (D.rmax[v] > need) need = D.rmax[v];
        while (D.q_next <= need && D.q_next < D.qh)
            if ((rc = produce_q(&D))) goto out;
        for (int v = v0; v < v0 + n; v++)
        {
            /* ring holds q_next - ring_n .. q_next - 1 */
            if (D.rmin[v] < D.q_next - D.ring_n) { rc = MFD_E_MEM; goto out; }
            uint16_t *row = lin + (size_t) (v - v0) * row_px;
            long tl = env->tick();
            /* the lens map at every GRID-th column (and the last), linear in
             * between: the distortion is smooth, the error stays far below a
             * quarter pixel, and it saves ~15 of 16 polynomial evaluations */
            int ng = 0;
            for (int u = 0;; u += GRID)
            {
                if (u > W - 1) u = W - 1;
                quarter_of(&D, u, v, &D.gq[2 * ng], &D.gq[2 * ng + 1]);
                ng++;
                if (u == W - 1) break;
            }
            for (int g = 0; g < ng - 1; g++)
            {
                int u0 = g * GRID, u1 = g + 1 == ng - 1 ? W - 1 : u0 + GRID, span = u1 - u0;
                int32_t x0 = D.gq[2 * g], y0 = D.gq[2 * g + 1], x1 = D.gq[2 * g + 2], y1 = D.gq[2 * g + 3];
                for (int u = u0; u < u1 || (u == u1 && u1 == W - 1); u++)
                {
                    int32_t f = u - u0;
                    sample(&D, x0 + (x1 - x0) * f / span, y0 + (y1 - y0) * f / span, row + 3 * u);
                }
            }
            res->ms_lens += env->tick() - tl;
        }
        long tw = env->tick();
        if (env->write(tmp, lin, (long) (row_px * 2 * (size_t) n)) != (long) (row_px * 2 * (size_t) n)) { rc = MFD_E_IO; goto out; }
        res->ms_tmp_io += env->tick() - tw;
        t1 = env->tick();
        if ((rc = mf_fx_scan_rows(fx, lin, row_px, v0, n)) != MF_OK) goto out;
        ms_scan += env->tick() - t1;
        progress(job, (int) (600L * (v0 + n) / H));
        if (cancelled(job)) { rc = MFD_E_CANCEL; goto out; }
        maybe_yield(&D);
    }
    /* rest of the DNG: hash only */
    if (job->hash)
    {
        long got;
        while ((got = env->read(D.f, D.rawbuf, (long) (4 * D.d.row_bytes))) > 0) mfd_sha_update(&D.sha, D.rawbuf, (size_t) got);
        mfd_sha_final(&D.sha, res->dng_sha256);
    }
    env->close(D.f), D.f = 0;
    env->close(tmp), tmp = 0;
    res->ms_read = env->tick() - t0 - ms_scan;
    res->ms_scan = ms_scan;
    res->scanner_ev_q16 = mf_fx_scanner_ev_q16(fx);

    /* B: glow pass */
    t1 = env->tick();
    if (!(tmp = env->open(job->tmp_path, 0))) { rc = MFD_E_IO; goto out; }
    for (int v0 = 0; v0 < H; v0 += STRIP)
    {
        int n = v0 + STRIP > H ? H - v0 : STRIP;
        long tr = env->tick();
        if (env->read(tmp, lin, (long) (row_px * 2 * (size_t) n)) != (long) (row_px * 2 * (size_t) n)) { rc = MFD_E_IO; goto out; }
        res->ms_tmp_io += env->tick() - tr;
        if ((rc = mf_fx_glow_rows(fx, lin, row_px, v0, n)) != MF_OK) goto out;
        progress(job, 600 + (int) (100L * (v0 + n) / H));
        if (cancelled(job)) { rc = MFD_E_CANCEL; goto out; }
        maybe_yield(&D);
    }
    res->ms_glow = env->tick() - t1;

    /* C: render pass -> JPEG */
    t1 = env->tick();
    if (env->seek(tmp, 0)) { rc = MFD_E_IO; goto out; }
    if (jp)
    {
        if (!(jf = env->open(job->jpeg_path, 1))) { rc = MFD_E_IO; goto out; }
        if ((rc = mfd_jpeg_begin(jp, env, jf, W, H, job->quality))) goto out;
    }
    if (vw && (rc = mfd_view_begin(vw, env, job->mfv_path, W, H, (int) D.d.orientation))) goto out;
    for (int v0 = 0; v0 < H; v0 += STRIP)
    {
        int n = v0 + STRIP > H ? H - v0 : STRIP;
        long tr = env->tick();
        if (env->read(tmp, lin, (long) (row_px * 2 * (size_t) n)) != (long) (row_px * 2 * (size_t) n)) { rc = MFD_E_IO; goto out; }
        res->ms_tmp_io += env->tick() - tr;
        if ((rc = mf_fx_render_rows(fx, lin, row_px, v0, n, disp, row_px)) != MF_OK) goto out;
        /* 16-bit display -> 8-bit, round(x * 255 / 65535) without a division: n / 65535 ==
         * (n + (n >> 16)) >> 16 for these n (checked for every 16-bit x) */
        for (size_t i = 0; i < row_px * (size_t) n; i++)
        {
            uint32_t x = disp[i];
            rgb8[i] = (uint8_t) ((x * 255u + 32767u + ((x * 255u + 32767u) >> 16)) >> 16);
        }
        long tj = env->tick();
        if (jp && (rc = mfd_jpeg_rows(jp, rgb8, n))) goto out;
        long tv = env->tick();
        res->ms_jpeg += tv - tj;
        if (vw && (rc = mfd_view_rows(vw, rgb8, v0, n))) goto out;
        res->ms_view += env->tick() - tv;
        progress(job, 700 + (int) (300L * (v0 + n) / H));
        if (cancelled(job)) { rc = MFD_E_CANCEL; goto out; }
        maybe_yield(&D);
    }
    if (jp) rc = mfd_jpeg_end(jp, &res->jpeg_bytes);
    if (vw)
    {
        long tv = env->tick();
        int rv = mfd_view_end(vw);
        res->ms_view += env->tick() - tv;
        env->release(vw), vw = 0;
        if (!rc) rc = rv;
    }
    res->ms_render = env->tick() - t1;

out:
    if (D.f) env->close(D.f);
    if (tmp) env->close(tmp);
    if (jf) env->close(jf);
    env->remove(job->tmp_path);
    if (vw) { mfd_view_end(vw); env->release(vw); }
    if (rc && job->jpeg_path) env->remove(job->jpeg_path);
    if (rc && job->mfv_path) env->remove(job->mfv_path);
    if (hdr) env->release(hdr);
    if (D.jx) env->release(D.jx);
    if (D.rmin) env->release(D.rmin);
    if (D.rmax) env->release(D.rmax);
    if (D.acc) env->release(D.acc);
    if (D.gq) env->release(D.gq);
    if (D.ring) env->release(D.ring);
    if (D.rawbuf) env->release(D.rawbuf);
    if (lin) env->release(lin);
    if (disp) env->release(disp);
    if (rgb8) env->release(rgb8);
    if (ctx) env->release(ctx);
    if (jp) env->release(jp);
    res->ms_total = env->tick() - t0;
    return rc;
}
