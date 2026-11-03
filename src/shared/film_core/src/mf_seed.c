/* SPDX-License-Identifier: GPL-2.0-only
 * Deterministic per-frame seeds and coordinate-addressed grain noise.
 *
 * Upstream M-Film seeds an LCG with 12345 + frame * 7919 and walks it in
 * pixel order (fos_dev.c rnd/finish_grain). That makes grain depend on
 * visit order, which docs/05 forbids for tiled rendering, so this core
 * replaces the *noise source* (not the grain model) with a stateless hash
 * of (seed, x, y, channel) of the same range. DEVIATION, documented in
 * docs/audit/P00-source-audit.md. */
#include "mf_core.h"

#include <string.h>

#define SEED_MAX_INPUT 1024

static int put(uint8_t *buf, size_t *at, const char *s)
{
    size_t n = strlen(s) + 1;              /* include the NUL separator */
    if (*at + n > SEED_MAX_INPUT) return 0;
    memcpy(buf + *at, s, n);
    *at += n;
    return 1;
}

/* decimal digits of v; no printf and no 64-bit divide helper (neither is
 * available to a CHDK module): long division by 10, bit by bit */
static size_t u64_decimal(uint64_t v, char *out)
{
    char tmp[20];
    size_t n = 0;
    do
    {
        uint64_t q = 0;
        uint32_t r = 0;
        for (int i = 63; i >= 0; i--)
        {
            r = (r << 1) | (uint32_t) ((v >> i) & 1);
            q <<= 1;
            if (r >= 10) { r -= 10; q |= 1; }
        }
        tmp[n++] = (char) ('0' + r);
        v = q;
    } while (v);
    for (size_t i = 0; i < n; i++) out[i] = tmp[n - 1 - i];
    out[n] = 0;
    return n;
}

int mf_frame_seed(const char *device_id, const char *roll_id, const char *frame_id,
                  const char *profile_id, const char *recipe_version,
                  uint64_t user_seed, uint64_t *seed_out)
{
    if (!device_id || !roll_id || !frame_id || !profile_id || !recipe_version || !seed_out)
        return MF_E_INVALID_ARG;
    uint8_t buf[SEED_MAX_INPUT];
    size_t at = 0;
    char us[24];
    u64_decimal(user_seed, us);
    if (!put(buf, &at, "mfilm-seed-v1") || !put(buf, &at, device_id) || !put(buf, &at, roll_id) ||
        !put(buf, &at, frame_id) || !put(buf, &at, profile_id) || !put(buf, &at, recipe_version))
        return MF_E_INVALID_ARG;
    /* the last field carries no trailing NUL */
    size_t n = strlen(us);
    if (at + n > SEED_MAX_INPUT) return MF_E_INVALID_ARG;
    memcpy(buf + at, us, n);
    at += n;
    uint8_t h[MF_SHA256_LEN];
    mf_sha256(buf, at, h);
    uint64_t s = 0;
    for (int i = 0; i < 8; i++) s = s << 8 | h[i];
    *seed_out = s;
    return MF_OK;
}

/* splitmix64 finaliser: full avalanche, cheap on 32-bit ARM too */
static uint64_t mix64(uint64_t z)
{
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31);
}

int32_t mf_noise(uint64_t seed, uint32_t x, uint32_t y, uint32_t channel)
{
    uint64_t k = mix64(seed ^ 0x9e3779b97f4a7c15ULL);
    k = mix64(k ^ ((uint64_t) y << 32 | x));
    k = mix64(k + channel);
    return (int32_t) (k >> 48 & 0xFFFF) - 32768;
}
