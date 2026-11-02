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
 * display sRGB 0..1. Same arithmetic as upstream fos_film_color(); results
 * are bit-exact only with the same libm (expf/log2f/atan2f) and FP flags.
 * Cross-libm (camera) parity is tolerance-based, see docs/05. */
void mf_film_color(const struct mf_look *f, const float lin[3], float out[3]);

/* ------------------------------------------------------------ profile bundle
 * IMPLEMENTED. profiles/mfilm-films.bin (tools/build_bundle.py): every film
 * of M-Film films.py with its look and, for LUT films, a baked 33^3 table. */
#define MF_GRID 33
#define MF_NGRID (MF_GRID * MF_GRID * MF_GRID)

enum mf_kind { MF_KIND_NEG, MF_KIND_SLIDE, MF_KIND_XPRO, MF_KIND_BW, MF_KIND_CINE, MF_KIND_PRINT };

struct mf_film {
    char key[24], name[48], short_name[24], brand[16];
    int iso;
    int kind;                   /* enum mf_kind */
    float soft;                 /* optical softness, gaussian sigma in reference px (films.py) */
    struct mf_look look;        /* look.key points at key[] */
    const uint16_t *table;      /* [MF_NGRID][3] display 0..65535, red fastest; NULL: model colour */
};

typedef struct mf_bundle {
    int nfilms;
    struct mf_film *films;      /* owned */
    uint8_t sha256[32];
} mf_bundle;

/* Parse a bundle image kept in memory by the caller (tables point into it).
 * Returns MF_OK or an error; on error *out is left empty. */
int mf_bundle_parse(const uint8_t *data, size_t len, mf_bundle *out);
void mf_bundle_free(mf_bundle *b);
/* exact key match; NULL when the film is not in the bundle */
const struct mf_film *mf_bundle_find(const mf_bundle *b, const char *key);

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

/* ------------------------------------------------------------ film colour table
 * IMPLEMENTED. The film's colour as a 3D table over Cineon log code, as
 * upstream fos_dev.c: model films are tabulated from mf_film_color, LUT
 * films use the bundle's baked table. Lookup is tetrahedral. */
typedef struct mf_table { uint16_t v[MF_NGRID][3]; } mf_table;
void mf_table_from_film(const struct mf_film *film, mf_table *t);
float mf_cineon_encode(float lin);           /* linear -> Cineon code 0..1 */
float mf_cineon_decode(float code);
void mf_table_apply(const mf_table *t, const float lin[3], float out[3]);   /* display 0..1 */

/* ------------------------------------------------------------ whole-frame film stage
 * IMPLEMENTED (reference, float, in memory). Mirrors the camera's
 * fos_dev.c order: scanner exposure + film balance -> softness ->
 * halation (glow grid) + vignette -> film table -> grain. */
typedef struct mf_develop_params {
    uint64_t grain_seed;
    float grain_scale, halation_scale, softness_scale;  /* recipe look_controls, 1.0 = film */
    float exposure_ev;                                   /* recipe exposure compensation */
    int reference_width;        /* width the film's px sizes refer to; 0 = 5184 (M-Film lab) */
} mf_develop_params;

/* rgb: interleaved scene-linear sRGB (1.0 = sensor white after WB), w*h*3,
 * replaced in place by display-referred sRGB 0..1 (not yet gamma-quantised:
 * values are the film table's output, already display encoded). */
int mf_develop_frame(const struct mf_film *film, const mf_table *table, float *rgb, int w, int h,
                     const mf_develop_params *p);

/* scanner exposure (stops) the frame gets before the film's own ev */
float mf_scanner_ev(const struct mf_film *film, const float *rgb, int w, int h);

/* ------------------------------------------------------------ flat FFI (mf_api.c)
 * For ctypes callers: plain types only. */
int mf_abi_version(void);
/* SHA-256 over the core sources this library was built from */
const char *mf_core_version(void);
int mf_bundle_info(const uint8_t *data, size_t len, int *nfilms, uint8_t sha256_out[MF_SHA256_LEN]);
int mf_bundle_key(const uint8_t *data, size_t len, int i, char *buf, size_t n);
int mf_develop_simple(const uint8_t *bundle, size_t len, const char *key, float *rgb, int w, int h,
                      uint64_t grain_seed, float grain_scale, float halation_scale, float softness_scale,
                      float exposure_ev, int reference_width, float *scanner_ev_out, char *err, size_t errlen);

/* ------------------------------------------------------------ tiles
 * PROPOSED, NOT IMPLEMENTED: streaming/tiled variant for the camera (P05). */
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
