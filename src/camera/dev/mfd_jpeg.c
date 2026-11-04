/* SPDX-License-Identifier: GPL-2.0-only
 * Baseline JPEG encoder for the camera: integer only (no float, no 64-bit
 * division), 4:4:4 YCbCr, standard (ITU T.81 Annex K) quantisation and
 * Huffman tables with IJG quality scaling, streamed in 8-row bands.
 * The DCT is a direct separable product with a Q13 cosine table: simple to
 * verify, fast enough for the camera's 1024x768 renders. */
#include <string.h>
#include "mfd.h"

static const int16_t DCTC[8][8] = {
    {2896, 2896, 2896, 2896, 2896, 2896, 2896, 2896},
    {4017, 3406, 2276, 799, -799, -2276, -3406, -4017},
    {3784, 1567, -1567, -3784, -3784, -1567, 1567, 3784},
    {3406, -799, -4017, -2276, 2276, 4017, 799, -3406},
    {2896, -2896, -2896, 2896, 2896, -2896, -2896, 2896},
    {2276, -4017, 799, 3406, -3406, -799, 4017, -2276},
    {1567, -3784, 3784, -1567, -1567, 3784, -3784, 1567},
    {799, -2276, 3406, -4017, 4017, -3406, 2276, -799},
};

static const uint8_t ZZ[64] = {0,  1,  8,  16, 9,  2,  3,  10, 17, 24, 32, 25, 18, 11, 4,  5,
                               12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6,  7,  14, 21, 28,
                               35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
                               58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63};

static const uint8_t QL[64] = {16, 11, 10, 16, 24,  40,  51,  61,  12, 12, 14, 19, 26,  58,  60,  55,
                               14, 13, 16, 24, 40,  57,  69,  56,  14, 17, 22, 29, 51,  87,  80,  62,
                               18, 22, 37, 56, 68,  109, 103, 77,  24, 35, 55, 64, 81,  104, 113, 92,
                               49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99};
static const uint8_t QC[64] = {17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99,
                               24, 26, 56, 99, 99, 99, 99, 99, 47, 66, 99, 99, 99, 99, 99, 99,
                               99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
                               99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99};

static const uint8_t DC_L_BITS[16] = {0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0};
static const uint8_t DC_C_BITS[16] = {0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0};
static const uint8_t DC_VALS[12] = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11};
static const uint8_t AC_L_BITS[16] = {0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d};
static const uint8_t AC_L_VALS[162] = {
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07, 0x22, 0x71,
    0x14, 0x32, 0x81, 0x91, 0xa1, 0x08, 0x23, 0x42, 0xb1, 0xc1, 0x15, 0x52, 0xd1, 0xf0, 0x24, 0x33, 0x62, 0x72,
    0x82, 0x09, 0x0a, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x25, 0x26, 0x27, 0x28, 0x29, 0x2a, 0x34, 0x35, 0x36, 0x37,
    0x38, 0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
    0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x83,
    0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3,
    0xa4, 0xa5, 0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3,
    0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe1, 0xe2,
    0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea, 0xf1, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8, 0xf9, 0xfa};
static const uint8_t AC_C_BITS[16] = {0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77};
static const uint8_t AC_C_VALS[162] = {
    0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21, 0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61, 0x71, 0x13, 0x22,
    0x32, 0x81, 0x08, 0x14, 0x42, 0x91, 0xa1, 0xb1, 0xc1, 0x09, 0x23, 0x33, 0x52, 0xf0, 0x15, 0x62, 0x72, 0xd1,
    0x0a, 0x16, 0x24, 0x34, 0xe1, 0x25, 0xf1, 0x17, 0x18, 0x19, 0x1a, 0x26, 0x27, 0x28, 0x29, 0x2a, 0x35, 0x36,
    0x37, 0x38, 0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58,
    0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a,
    0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9a,
    0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba,
    0xc2, 0xc3, 0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda,
    0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8, 0xf9, 0xfa};

typedef struct { uint16_t code[256]; uint8_t size[256]; } huff_t;

struct mfd_jpeg {
    const mfd_env *env;
    void *f;
    int w, h, rows_done, err;
    uint8_t q[2][64];                  /* natural order */
    uint32_t recip[2][64];             /* (1 << 16) / q */
    huff_t dc[2], ac[2];
    int prev_dc[3];
    uint32_t bitbuf;
    int bitcnt;
    uint32_t total;
    uint8_t out[4096];
    int outlen;
};

size_t mfd_jpeg_size(void) { return sizeof(struct mfd_jpeg); }

static void flush_out(mfd_jpeg *j)
{
    if (j->outlen && !j->err)
    {
        if (j->env->write(j->f, j->out, j->outlen) != j->outlen) j->err = MFD_E_IO;
        j->total += (uint32_t) j->outlen;
    }
    j->outlen = 0;
}

static void put_byte(mfd_jpeg *j, uint8_t b)
{
    if (j->outlen == (int) sizeof j->out) flush_out(j);
    j->out[j->outlen++] = b;
}

static void put_bytes(mfd_jpeg *j, const uint8_t *p, int n) { while (n--) put_byte(j, *p++); }
static void put16(mfd_jpeg *j, int v) { put_byte(j, (uint8_t) (v >> 8)); put_byte(j, (uint8_t) v); }

static void put_bits(mfd_jpeg *j, uint32_t code, int size)
{
    j->bitbuf = j->bitbuf << size | (code & ((1u << size) - 1));
    j->bitcnt += size;
    while (j->bitcnt >= 8)
    {
        uint8_t b = (uint8_t) (j->bitbuf >> (j->bitcnt - 8));
        put_byte(j, b);
        if (b == 0xff) put_byte(j, 0);             /* byte stuffing */
        j->bitcnt -= 8;
    }
}

static void build_huff(huff_t *h, const uint8_t bits[16], const uint8_t *vals)
{
    uint16_t code = 0;
    int k = 0;
    memset(h, 0, sizeof *h);
    for (int len = 1; len <= 16; len++)
    {
        for (int i = 0; i < bits[len - 1]; i++)
        {
            h->code[vals[k]] = code++;
            h->size[vals[k]] = (uint8_t) len;
            k++;
        }
        code <<= 1;
    }
}

static void put_dht(mfd_jpeg *j, int cls_id, const uint8_t bits[16], const uint8_t *vals, int n)
{
    put_byte(j, (uint8_t) cls_id);
    put_bytes(j, bits, 16);
    put_bytes(j, vals, n);
}

int mfd_jpeg_begin(mfd_jpeg *j, const mfd_env *env, void *f, int w, int h, int quality)
{
    memset(j, 0, sizeof *j);
    j->env = env, j->f = f, j->w = w, j->h = h;
    if (w <= 0 || h <= 0 || w > 65535 || h > 65535) return MFD_E_DATA;
    if (quality < 1) quality = 1;
    if (quality > 100) quality = 100;
    int scale = quality < 50 ? 5000 / quality : 200 - quality * 2;
    for (int i = 0; i < 64; i++)
        for (int t = 0; t < 2; t++)
        {
            int v = ((t ? QC : QL)[i] * scale + 50) / 100;
            v = v < 1 ? 1 : v > 255 ? 255 : v;
            j->q[t][i] = (uint8_t) v;
            j->recip[t][i] = (1u << 16) / (uint32_t) v;
        }
    build_huff(&j->dc[0], DC_L_BITS, DC_VALS);
    build_huff(&j->dc[1], DC_C_BITS, DC_VALS);
    build_huff(&j->ac[0], AC_L_BITS, AC_L_VALS);
    build_huff(&j->ac[1], AC_C_BITS, AC_C_VALS);
    static const uint8_t soi_app0[] = {0xff, 0xd8, 0xff, 0xe0, 0, 16, 'J', 'F', 'I', 'F', 0, 1, 1, 0, 0, 1, 0, 1, 0, 0};
    put_bytes(j, soi_app0, sizeof soi_app0);
    put16(j, 0xffdb);
    put16(j, 2 + 2 * 65);
    for (int t = 0; t < 2; t++)
    {
        put_byte(j, (uint8_t) t);
        for (int i = 0; i < 64; i++) put_byte(j, j->q[t][ZZ[i]]);
    }
    put16(j, 0xffc0);                              /* SOF0 */
    put16(j, 8 + 3 * 3);
    put_byte(j, 8);
    put16(j, h);
    put16(j, w);
    put_byte(j, 3);
    for (int c = 0; c < 3; c++) { put_byte(j, (uint8_t) (c + 1)); put_byte(j, 0x11); put_byte(j, c ? 1 : 0); }
    put16(j, 0xffc4);
    put16(j, 2 + 4 * 17 + 12 + 12 + 162 + 162);
    put_dht(j, 0x00, DC_L_BITS, DC_VALS, 12);
    put_dht(j, 0x10, AC_L_BITS, AC_L_VALS, 162);
    put_dht(j, 0x01, DC_C_BITS, DC_VALS, 12);
    put_dht(j, 0x11, AC_C_BITS, AC_C_VALS, 162);
    put16(j, 0xffda);                              /* SOS */
    put16(j, 6 + 2 * 3);
    put_byte(j, 3);
    for (int c = 0; c < 3; c++) { put_byte(j, (uint8_t) (c + 1)); put_byte(j, c ? 0x11 : 0x00); }
    put_byte(j, 0);
    put_byte(j, 63);
    put_byte(j, 0);
    return j->err;
}

static int nbits(int v)
{
    int n = 0;
    if (v < 0) v = -v;
    while (v) { n++; v >>= 1; }
    return n;
}

static void block(mfd_jpeg *j, const int16_t s[64], int comp)
{
    int32_t tmp[64], coef[64];
    for (int y = 0; y < 8; y++)                    /* rows: Q13 -> keep 2 fractional bits */
        for (int u = 0; u < 8; u++)
        {
            int32_t a = 0;
            for (int x = 0; x < 8; x++) a += DCTC[u][x] * s[y * 8 + x];
            tmp[y * 8 + u] = (a + (1 << 10)) >> 11;
        }
    for (int u = 0; u < 8; u++)                    /* columns */
        for (int v = 0; v < 8; v++)
        {
            int32_t a = 0;
            for (int y = 0; y < 8; y++) a += DCTC[v][y] * tmp[y * 8 + u];
            coef[v * 8 + u] = a;                   /* Q15 */
        }
    int t = comp ? 1 : 0;
    int16_t zz[64];
    for (int i = 0; i < 64; i++)
    {
        int k = ZZ[i];
        int32_t a = coef[k];
        uint32_t m = (uint32_t) (a < 0 ? -a : a);
        /* |F| / q with rounding: F is Q15, recip is Q16 of 1/q -> Q31 product, take >>31 */
        uint32_t qv = (uint32_t) (((uint64_t) m * j->recip[t][k] + (1u << 30)) >> 31);
        zz[i] = (int16_t) (a < 0 ? -(int32_t) qv : (int32_t) qv);
    }
    int diff = zz[0] - j->prev_dc[comp];
    j->prev_dc[comp] = zz[0];
    int n = nbits(diff);
    put_bits(j, j->dc[t].code[n], j->dc[t].size[n]);
    if (n) put_bits(j, (uint32_t) (diff < 0 ? diff - 1 : diff), n);
    int run = 0;
    for (int i = 1; i < 64; i++)
    {
        if (!zz[i]) { run++; continue; }
        while (run > 15) { put_bits(j, j->ac[t].code[0xf0], j->ac[t].size[0xf0]); run -= 16; }
        n = nbits(zz[i]);
        int sym = run << 4 | n;
        put_bits(j, j->ac[t].code[sym], j->ac[t].size[sym]);
        put_bits(j, (uint32_t) (zz[i] < 0 ? zz[i] - 1 : zz[i]), n);
        run = 0;
    }
    if (run) put_bits(j, j->ac[t].code[0], j->ac[t].size[0]);
}

int mfd_jpeg_rows(mfd_jpeg *j, const uint8_t *rgb, int n)
{
    int16_t blk[3][64];
    if (n <= 0 || n > 8 || j->rows_done + n > j->h) return MFD_E_DATA;
    for (int bx = 0; bx < j->w; bx += 8)
    {
        for (int y = 0; y < 8; y++)
        {
            int sy = y < n ? y : n - 1;            /* pad the last band / column by replication */
            for (int x = 0; x < 8; x++)
            {
                int sx = bx + x < j->w ? bx + x : j->w - 1;
                const uint8_t *p = rgb + 3 * ((size_t) sy * j->w + sx);
                int32_t r = p[0], g = p[1], b = p[2];
                int32_t Y = (19595 * r + 38470 * g + 7471 * b + 32768) >> 16;
                int32_t cb = ((-11059 * r - 21709 * g + 32768 * b + 32768) >> 16) + 128;
                int32_t cr = ((32768 * r - 27439 * g - 5329 * b + 32768) >> 16) + 128;
                blk[0][y * 8 + x] = (int16_t) (Y - 128);
                blk[1][y * 8 + x] = (int16_t) ((cb > 255 ? 255 : cb < 0 ? 0 : cb) - 128);
                blk[2][y * 8 + x] = (int16_t) ((cr > 255 ? 255 : cr < 0 ? 0 : cr) - 128);
            }
        }
        for (int c = 0; c < 3; c++) block(j, blk[c], c);
    }
    j->rows_done += n;
    return j->err;
}

int mfd_jpeg_end(mfd_jpeg *j, uint32_t *bytes)
{
    if (j->rows_done != j->h) return MFD_E_DATA;
    if (j->bitcnt) put_bits(j, 0x7f, 8 - j->bitcnt);   /* pad the last byte with 1 bits */
    put16(j, 0xffd9);
    flush_out(j);
    if (bytes) *bytes = j->total;
    return j->err;
}
