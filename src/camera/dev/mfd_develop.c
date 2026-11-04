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
    uint32_t mem;
} dev;

static void *xalloc(dev *D, size_t n)
{
    void *p = D->env->alloc(n);
    if (p) D->mem += (uint32_t) n;
    return p;
}

static int read_hash(dev *D, void *buf, long n)
{
    if (D->env->read(D->f, buf, n) != n) return MFD_E_IO;
    mfd_sha_update(&D->sha, buf, (size_t) n);
    return MFD_OK;
}

/* quarter row qi from raw visible rows 4qi..4qi+3 */
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
    for (int k = 0; k < 4; k++)
    {
        if ((rc = read_hash(D, rows + (size_t) k * d->row_bytes, (long) d->row_bytes))) return rc;
        D->raw_row++;
    }
    const mfd_camera *cam = D->job->cam;
    uint16_t *out = D->ring + (size_t) ((uint32_t) D->q_next % (uint32_t) D->ring_n) * D->qw * 3;
    int32_t black = (int32_t) d->black;
    for (int qx = 0; qx < D->qw; qx++)
    {
        int32_t sum[3] = {0, 0, 0}, cnt[3] = {0, 0, 0};
        for (int k = 0; k < 4; k++)
        {
            const uint8_t *r = rows + (size_t) k * d->row_bytes;
            uint32_t ry = d->act_top + 4u * (uint32_t) D->q_next + (uint32_t) k;
            for (int i = 0; i < 4; i++)
            {
                uint32_t c = d->act_left + 4u * (uint32_t) qx + (uint32_t) i;
                const uint8_t *p = r + (c >> 1) * 3;
                int32_t v = (c & 1) ? ((p[1] & 15) << 8 | p[2]) : (p[0] << 4 | p[1] >> 4);
                int col = d->cfa[(ry & 1) * 2 + (c & 1)];
                sum[col] += v - black;
                cnt[col]++;
            }
        }
        int32_t lin[3];
        for (int ch = 0; ch < 3; ch++)
        {
            /* mean (sum / cnt) times wb: cnt is 4 or 8 for a Bayer 4x4 block */
            int sh = cnt[ch] == 8 ? 3 : cnt[ch] == 4 ? 2 : 0;
            int64_t v = ((int64_t) sum[ch] * cam->wb_q16[ch]) >> (16 + sh);
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
    D.env = env, D.job = job;
    int W = job->out_w, H = job->out_h;
    size_t row_px = 3 * (size_t) W;
    uint16_t *lin = 0, *disp = 0;
    uint8_t *rgb8 = 0, *hdr = 0;
    void *ctx = 0, *tmp = 0, *jf = 0;
    mfd_jpeg *jp = 0;
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
        mfd_sha_update(&D.sha, hdr, D.d.strip_off);
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
    lin = xalloc(&D, row_px * STRIP * 2);
    disp = xalloc(&D, row_px * STRIP * 2);
    rgb8 = xalloc(&D, row_px * STRIP);
    size_t ctx_len = mf_fx_ctx_size(W, H);
    ctx = xalloc(&D, ctx_len);
    jp = xalloc(&D, mfd_jpeg_size());
    if (!D.ring || !D.rawbuf || !lin || !disp || !rgb8 || !ctx || !jp) { rc = MFD_E_MEM; goto out; }
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
            for (int u = 0; u < W; u++)
            {
                int32_t qx, qy;
                quarter_of(&D, u, v, &qx, &qy);
                sample(&D, qx, qy, row + 3 * u);
            }
        }
        if (env->write(tmp, lin, (long) (row_px * 2 * (size_t) n)) != (long) (row_px * 2 * (size_t) n)) { rc = MFD_E_IO; goto out; }
        t1 = env->tick();
        if ((rc = mf_fx_scan_rows(fx, lin, row_px, v0, n)) != MF_OK) goto out;
        ms_scan += env->tick() - t1;
        if (env->yield) env->yield();
    }
    /* rest of the DNG: hash only */
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
        if (env->read(tmp, lin, (long) (row_px * 2 * (size_t) n)) != (long) (row_px * 2 * (size_t) n)) { rc = MFD_E_IO; goto out; }
        if ((rc = mf_fx_glow_rows(fx, lin, row_px, v0, n)) != MF_OK) goto out;
        if (env->yield) env->yield();
    }
    res->ms_glow = env->tick() - t1;

    /* C: render pass -> JPEG */
    t1 = env->tick();
    if (env->seek(tmp, 0)) { rc = MFD_E_IO; goto out; }
    if (!(jf = env->open(job->jpeg_path, 1))) { rc = MFD_E_IO; goto out; }
    if ((rc = mfd_jpeg_begin(jp, env, jf, W, H, job->quality))) goto out;
    for (int v0 = 0; v0 < H; v0 += STRIP)
    {
        int n = v0 + STRIP > H ? H - v0 : STRIP;
        if (env->read(tmp, lin, (long) (row_px * 2 * (size_t) n)) != (long) (row_px * 2 * (size_t) n)) { rc = MFD_E_IO; goto out; }
        if ((rc = mf_fx_render_rows(fx, lin, row_px, v0, n, disp, row_px)) != MF_OK) goto out;
        for (size_t i = 0; i < row_px * (size_t) n; i++) rgb8[i] = (uint8_t) (((uint32_t) disp[i] * 255u + 32767u) / 65535u);
        if ((rc = mfd_jpeg_rows(jp, rgb8, n))) goto out;
        if (env->yield) env->yield();
    }
    rc = mfd_jpeg_end(jp, &res->jpeg_bytes);
    res->ms_render = env->tick() - t1;

out:
    if (D.f) env->close(D.f);
    if (tmp) env->close(tmp);
    if (jf) env->close(jf);
    env->remove(job->tmp_path);
    if (rc && job->jpeg_path) env->remove(job->jpeg_path);
    if (hdr) env->release(hdr);
    if (D.jx) env->release(D.jx);
    if (D.rmin) env->release(D.rmin);
    if (D.rmax) env->release(D.rmax);
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
