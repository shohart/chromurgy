/* SPDX-License-Identifier: GPL-2.0-only
 *
 * mf_core: the shared M-Film film core (Linux + CHDK builds).
 *
 * STATUS: PROPOSED ABI (docs/05-shared-film-engine.md). Only the parts
 * marked IMPLEMENTED below exist; everything else returns MF_E_UNSUPPORTED.
 *
 * Rules (do not break):
 *  - no file I/O, no CHDK/Magic Lantern globals, no heap in hot paths;
 *  - deterministic for the same input, look, seed and pixel coordinates;
 *  - grain depends on global pixel coordinates, never on tile/visit order.
 */
#ifndef MF_CORE_H
#define MF_CORE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MF_CORE_ABI_VERSION 1

enum mf_status {
    MF_OK = 0,
    MF_E_INVALID_ARG = -1,
    MF_E_UNSUPPORTED = -2,      /* e.g. unknown film profile: never substitute */
    MF_E_PROFILE_MISMATCH = -3,
};

/* ------------------------------------------------------------ film look
 * IMPLEMENTED. Field-for-field port of `struct fos_look`
 * (M-Film ml-dev/filmos/fos_dev.h, see LOCKFILE for the pinned commit). */
struct mf_hue_shift { int8_t from, to; float amount, chroma; };

struct mf_look {
    const char *key;            /* film profile id, e.g. "portra400" */
    int balance;                /* K the film is balanced for */
    int slide;                  /* reversal film: no scanner exposure */
    float ev, sat;
    float contrast[3], pivot[3], black[3], white[3];
    int nhues;
    struct mf_hue_shift hues[4];
    float halation, hal_thr, hal_tint[3];
    float grain, grain_size;
    int mono;
    float mono_mix[3];
};

/* built-in looks (the 8 M-Film builds into the camera binary) */
extern const struct mf_look mf_builtin_looks[];
extern const int mf_builtin_nlooks;

/* exact lookup; NULL if unknown (callers must report MF_E_UNSUPPORTED,
 * unlike upstream fos_look_of() which silently falls back to look 0) */
const struct mf_look *mf_look_find(const char *key);

/* The film's colour for one scene-linear sRGB value (0.18 = mid grey):
 * display sRGB 0..1. Bit-for-bit the upstream fos_film_color() model. */
void mf_film_color(const struct mf_look *f, const float lin[3], float out[3]);

/* ------------------------------------------------------------ hashing / seeds
 * IMPLEMENTED. */
#define MF_SHA256_LEN 32
void mf_sha256(const void *data, size_t len, uint8_t out[MF_SHA256_LEN]);

/* Per-frame grain seed (docs/05): first 8 bytes (big-endian) of
 * SHA-256("mfilm-seed-v1" NUL device_id NUL roll_id NUL frame_id NUL
 *          profile_id NUL recipe_version NUL decimal(user_seed)).
 * Returns MF_E_INVALID_ARG on NULL strings. */
int mf_frame_seed(const char *device_id, const char *roll_id, const char *frame_id,
                  const char *profile_id, const char *recipe_version,
                  uint64_t user_seed, uint64_t *seed_out);

/* Coordinate-addressed noise in [-32768, 32767] (same range as upstream
 * rnd()). Pure function of (seed, x, y, channel): tile order independent. */
int32_t mf_noise(uint64_t seed, uint32_t x, uint32_t y, uint32_t channel);

/* ------------------------------------------------------------ tiles
 * PROPOSED, NOT IMPLEMENTED (grain/halation/vignette staging, P01). */
typedef struct mf_linear_tile {
    const float *rgb;           /* interleaved linear sRGB, 0.18 = mid grey */
    uint32_t x0, y0;            /* global coordinates of the first pixel */
    uint32_t width, height;
    size_t stride;              /* floats per row */
} mf_linear_tile;

typedef struct mf_output_tile {
    uint16_t *rgb;              /* interleaved display-referred 16-bit */
    size_t stride;              /* uint16 per row */
} mf_output_tile;

typedef struct mf_tile_context {
    uint32_t image_width, image_height;
    uint64_t grain_seed;
} mf_tile_context;

int mf_core_process_tile(const struct mf_look *look, const mf_linear_tile *in,
                         const mf_tile_context *ctx, mf_output_tile *out);

#ifdef __cplusplus
}
#endif
#endif
