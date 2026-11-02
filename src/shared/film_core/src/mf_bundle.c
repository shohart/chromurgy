/* SPDX-License-Identifier: GPL-2.0-only
 * Film profile bundle reader (format: tools/build_bundle.py). Bounds-checked:
 * a damaged bundle is refused, never half-read. */
#include "mf_core.h"

#include <stdlib.h>
#include <string.h>

#define HEADER_SIZE 20
#define RECORD_SIZE 308                 /* must equal build_bundle.RECORD.size */

static uint32_t u32(const uint8_t *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t) p[3] << 24; }
static int32_t i32(const uint8_t *p) { return (int32_t) u32(p); }
static float f32(const uint8_t *p) { uint32_t v = u32(p); float f; memcpy(&f, &v, 4); return f; }

static int str_field(char *dst, const uint8_t *src, size_t n)
{
    if (!memchr(src, 0, n)) return 0;        /* must be NUL-terminated inside the field */
    memcpy(dst, src, n);
    return 1;
}

static int little_endian(void) { const uint16_t x = 1; return *(const uint8_t *) &x == 1; }

int mf_bundle_parse(const uint8_t *data, size_t len, mf_bundle *out)
{
    memset(out, 0, sizeof(*out));
    if (!data || len < HEADER_SIZE || memcmp(data, "MFB1", 4)) return MF_E_INVALID_ARG;
    if (u32(data + 4) != 1 || u32(data + 12) != MF_GRID || u32(data + 16) != RECORD_SIZE) return MF_E_UNSUPPORTED;
    if (!little_endian()) return MF_E_UNSUPPORTED;     /* tables are used in place */
    uint32_t n = u32(data + 8);
    if (n == 0 || n > 1024 || len < HEADER_SIZE + (size_t) n * RECORD_SIZE) return MF_E_INVALID_ARG;
    struct mf_film *films = calloc(n, sizeof(*films));
    if (!films) return MF_E_INVALID_ARG;
    const size_t table_bytes = (size_t) MF_NGRID * 3 * 2;
    for (uint32_t i = 0; i < n; i++)
    {
        const uint8_t *r = data + HEADER_SIZE + (size_t) i * RECORD_SIZE;
        struct mf_film *f = &films[i];
        struct mf_look *L = &f->look;
        if (!str_field(f->key, r, 24) || !str_field(f->name, r + 24, 48) ||
            !str_field(f->short_name, r + 72, 24) || !str_field(f->brand, r + 96, 16)) goto bad;
        const uint8_t *p = r + 112;
        f->iso = i32(p); f->kind = i32(p + 4);
        uint32_t flags = u32(p + 8);
        p += 12;
        L->key = f->key;
        L->balance = i32(p); L->slide = i32(p + 4); L->ev = f32(p + 8); L->sat = f32(p + 12);
        p += 16;
        for (int c = 0; c < 3; c++) L->contrast[c] = f32(p + 4 * c);
        for (int c = 0; c < 3; c++) L->pivot[c] = f32(p + 12 + 4 * c);
        for (int c = 0; c < 3; c++) L->black[c] = f32(p + 24 + 4 * c);
        for (int c = 0; c < 3; c++) L->white[c] = f32(p + 36 + 4 * c);
        p += 48;
        L->nhues = i32(p);
        p += 4;
        if (L->nhues < 0 || L->nhues > 4 || f->kind < 0 || f->kind > MF_KIND_PRINT) goto bad;
        for (int k = 0; k < 4; k++, p += 16)
        {
            int32_t from = i32(p), to = i32(p + 4);
            if (from < 0 || from > 6 || to < 0 || to > 6) goto bad;
            L->hues[k].from = (int8_t) from; L->hues[k].to = (int8_t) to;
            L->hues[k].amount = f32(p + 8); L->hues[k].chroma = f32(p + 12);
        }
        L->halation = f32(p); L->hal_thr = f32(p + 4);
        for (int c = 0; c < 3; c++) L->hal_tint[c] = f32(p + 8 + 4 * c);
        L->grain = f32(p + 20); L->grain_size = f32(p + 24); f->soft = f32(p + 28);
        L->mono = i32(p + 32);
        for (int c = 0; c < 3; c++) L->mono_mix[c] = f32(p + 36 + 4 * c);
        uint32_t toff = u32(p + 48);
        if (p + 52 != r + RECORD_SIZE) goto bad;
        if (flags & 1)
        {
            if (toff < HEADER_SIZE + n * RECORD_SIZE || toff % 2 || toff > len || len - toff < table_bytes) goto bad;
            f->table = (const uint16_t *) (data + toff);
        }
        for (uint32_t j = 0; j < i; j++)
            if (!strcmp(films[j].key, f->key)) goto bad;
    }
    out->nfilms = (int) n;
    out->films = films;
    mf_sha256(data, len, out->sha256);
    return MF_OK;
bad:
    free(films);
    return MF_E_INVALID_ARG;
}

void mf_bundle_free(mf_bundle *b)
{
    if (!b) return;
    free(b->films);
    memset(b, 0, sizeof(*b));
}

const struct mf_film *mf_bundle_find(const mf_bundle *b, const char *key)
{
    if (!b || !key) return NULL;
    for (int i = 0; i < b->nfilms; i++)
        if (!strcmp(b->films[i].key, key)) return &b->films[i];
    return NULL;
}
