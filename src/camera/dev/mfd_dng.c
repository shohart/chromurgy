/* SPDX-License-Identifier: GPL-2.0-only
 * Streaming SHA-256 and the CHDK DNG header parser for the offline developer. */
#include <string.h>
#include "mfd.h"

/* ------------------------------------------------------------------ SHA-256 */

static const uint32_t K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void sha_block(uint32_t h[8], const uint8_t *p)
{
    uint32_t w[64], a, b, c, d, e, f, g, hh, t1, t2;
    for (int i = 0; i < 16; i++)
        w[i] = (uint32_t) p[4 * i] << 24 | (uint32_t) p[4 * i + 1] << 16 | (uint32_t) p[4 * i + 2] << 8 | p[4 * i + 3];
    for (int i = 16; i < 64; i++)
    {
        uint32_t s0 = ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3);
        uint32_t s1 = ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int i = 0; i < 64; i++)
    {
        t1 = hh + (ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
        t2 = (ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        hh = g, g = f, f = e, e = d + t1, d = c, c = b, b = a, a = t1 + t2;
    }
    h[0] += a, h[1] += b, h[2] += c, h[3] += d, h[4] += e, h[5] += f, h[6] += g, h[7] += hh;
}

void mfd_sha_init(mfd_sha *s)
{
    static const uint32_t iv[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                   0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    memcpy(s->h, iv, sizeof iv);
    s->used = 0;
    s->len_lo = s->len_hi = 0;
}

void mfd_sha_update(mfd_sha *s, const void *data, size_t n)
{
    const uint8_t *p = data;
    uint32_t lo = s->len_lo;
    s->len_lo += (uint32_t) n;
    if (s->len_lo < lo) s->len_hi++;
    if (s->used)
    {
        size_t take = 64 - s->used < n ? 64 - s->used : n;
        memcpy(s->buf + s->used, p, take);
        s->used += (uint32_t) take, p += take, n -= take;
        if (s->used < 64) return;
        sha_block(s->h, s->buf);
        s->used = 0;
    }
    for (; n >= 64; p += 64, n -= 64) sha_block(s->h, p);
    memcpy(s->buf, p, n);
    s->used = (uint32_t) n;
}

void mfd_sha_final(mfd_sha *s, uint8_t out[32])
{
    uint32_t hi = s->len_hi << 3 | s->len_lo >> 29, lo = s->len_lo << 3;
    uint8_t pad = 0x80, z = 0, len[8];
    mfd_sha_update(s, &pad, 1);
    while (s->used != 56) mfd_sha_update(s, &z, 1);
    for (int i = 0; i < 4; i++) len[i] = (uint8_t) (hi >> (24 - 8 * i)), len[4 + i] = (uint8_t) (lo >> (24 - 8 * i));
    memcpy(s->buf + 56, len, 8);
    sha_block(s->h, s->buf);
    for (int i = 0; i < 8; i++)
        for (int k = 0; k < 4; k++) out[4 * i + k] = (uint8_t) (s->h[i] >> (24 - 8 * k));
}

/* ------------------------------------------------------------------ DNG (little-endian TIFF) */

static uint32_t u16(const uint8_t *p) { return (uint32_t) p[0] | (uint32_t) p[1] << 8; }
static uint32_t u32(const uint8_t *p) { return u16(p) | u16(p + 2) << 16; }

typedef struct { const uint8_t *b; size_t len; } buf_t;

/* value of entry e: count values of type t; index i; returns 0 if outside the buffer */
static int entry_val(buf_t B, const uint8_t *e, uint32_t i, uint32_t *v)
{
    uint32_t t = u16(e + 2), cnt = u32(e + 4), sz = t == 3 ? 2 : (t == 4 || t == 9) ? 4 : (t == 1 || t == 2 || t == 7) ? 1 : 8;
    if (i >= cnt) return 0;
    const uint8_t *p;
    if (sz * cnt <= 4) p = e + 8;
    else
    {
        uint32_t off = u32(e + 8);
        if (off > B.len || B.len - off < sz * cnt) return 0;
        p = B.b + off;
    }
    p += (size_t) i * sz;
    *v = sz == 1 ? p[0] : sz == 2 ? u16(p) : u32(p);       /* rationals: numerator; i*2+1 for denominator */
    return 1;
}

static const uint8_t *find(buf_t B, uint32_t ifd, uint32_t tag)
{
    if (ifd + 2 > B.len) return 0;
    uint32_t n = u16(B.b + ifd);
    if (ifd + 2 + 12 * n > B.len) return 0;
    for (uint32_t i = 0; i < n; i++)
        if (u16(B.b + ifd + 2 + 12 * i) == tag) return B.b + ifd + 2 + 12 * i;
    return 0;
}

static int get(buf_t B, uint32_t ifd, uint32_t tag, uint32_t i, uint32_t *v)
{
    const uint8_t *e = find(B, ifd, tag);
    return e && entry_val(B, e, i, v);
}

/* rational: numerator/denominator are consecutive u32 at the value offset */
static int get_rational(buf_t B, uint32_t ifd, uint32_t tag, uint32_t *num, uint32_t *den)
{
    const uint8_t *e = find(B, ifd, tag);
    if (!e || (u16(e + 2) != 5 && u16(e + 2) != 10)) return 0;
    uint32_t off = u32(e + 8);
    if (off + 8 > B.len) return 0;
    *num = u32(B.b + off), *den = u32(B.b + off + 4);
    return *den != 0;
}

static void get_str(buf_t B, uint32_t ifd, uint32_t tag, char *dst, size_t cap)
{
    const uint8_t *e = find(B, ifd, tag);
    dst[0] = 0;
    if (!e || u16(e + 2) != 2) return;
    uint32_t cnt = u32(e + 4);
    const uint8_t *p = cnt <= 4 ? e + 8 : (u32(e + 8) + cnt <= B.len ? B.b + u32(e + 8) : 0);
    if (!p) return;
    size_t n = cnt < cap - 1 ? cnt : cap - 1;
    memcpy(dst, p, n);
    dst[n] = 0;
}

int mfd_dng_parse(const uint8_t *hdr, size_t len, mfd_dng *d)
{
    buf_t B = {hdr, len};
    memset(d, 0, sizeof *d);
    if (len < 8 || hdr[0] != 'I' || hdr[1] != 'I' || u16(hdr + 2) != 42) return MFD_E_DNG;
    uint32_t ifd0 = u32(hdr + 4), raw = 0, v, n, exif;
    if (!find(B, ifd0, 50706)) return MFD_E_DNG;                          /* DNGVersion */
    get_str(B, ifd0, 50708, d->model, sizeof d->model);
    /* raw IFD: IFD0 itself or a SubIFD with NewSubFileType 0 */
    if (get(B, ifd0, 254, 0, &v) && v == 0 && find(B, ifd0, 273)) raw = ifd0;
    const uint8_t *sub = find(B, ifd0, 330);
    if (!raw && sub)
        for (uint32_t i = 0; entry_val(B, sub, i, &v); i++)
        {
            uint32_t t;
            if (get(B, v, 254, 0, &t) && t == 0) { raw = v; break; }
        }
    if (!raw) return MFD_E_DNG;
    if (!get(B, raw, 256, 0, &d->raw_w) || !get(B, raw, 257, 0, &d->raw_h)) return MFD_E_DNG;
    if (!get(B, raw, 258, 0, &v) || v != 12) return MFD_E_DNG;              /* CHDK: 12-bit packed */
    if (!get(B, raw, 259, 0, &v) || v != 1) return MFD_E_DNG;               /* uncompressed */
    if (!get(B, raw, 262, 0, &v) || v != 32803) return MFD_E_DNG;           /* CFA */
    if (!get(B, raw, 273, 0, &d->strip_off) || !get(B, raw, 279, 0, &d->strip_bytes)) return MFD_E_DNG;
    if (get(B, raw, 273, 1, &v)) return MFD_E_DNG;                          /* one strip only */
    d->row_bytes = d->raw_w * 3 / 2;
    if (d->raw_w % 2 || d->strip_bytes != d->row_bytes * d->raw_h) return MFD_E_DNG;
    d->black = get(B, raw, 50714, 0, &v) ? v : 0;
    d->white = get(B, raw, 50717, 0, &v) ? v : 4095;
    d->act_top = 0, d->act_left = 0, d->vis_h = d->raw_h, d->vis_w = d->raw_w;
    if (get(B, raw, 50829, 0, &d->act_top) && get(B, raw, 50829, 1, &d->act_left) && get(B, raw, 50829, 2, &n)
        && get(B, raw, 50829, 3, &v))
    {
        if (n > d->raw_h || v > d->raw_w || n <= d->act_top || v <= d->act_left) return MFD_E_DNG;
        d->vis_h = n - d->act_top, d->vis_w = v - d->act_left;
    }
    for (int i = 0; i < 4; i++)
    {
        if (!get(B, raw, 33422, (uint32_t) i, &v) || v > 2) return MFD_E_DNG;
        d->cfa[i] = (uint8_t) v;
    }
    if ((d->act_top | d->act_left) & 1) return MFD_E_DNG;                  /* keep the CFA phase simple */
    if (get(B, ifd0, 34665, 0, &exif))
    {
        get_rational(B, exif, 37386, &d->focal_num, &d->focal_den);
        get_str(B, exif, 36867, d->datetime, sizeof d->datetime);
    }
    return MFD_OK;
}
