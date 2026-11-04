/* SPDX-License-Identifier: GPL-2.0-only
 * M-Film camera benchmark: shared by the CHDK module (mfbench.c) and the
 * host generator (mfbench_gen.c), so both develop the same synthetic frame
 * through the same code and their output hashes must be equal. */
#ifndef MFBENCH_H
#define MFBENCH_H
#include <stdint.h>
#include <stddef.h>
#include "mf_core.h"

#define MFB_MAGIC "MFBENCH1"
#define MFB_MAX_CASES 4
#define MFB_STRIP 8                 /* rows per call */

typedef struct mfb_header {         /* file layout, little-endian, all fields 4-byte aligned */
    char magic[8];
    uint32_t ncases;
    uint32_t table_bytes;           /* MF_NGRID * 3 * 2 */
    char film[32];
} mfb_header;

typedef struct mfb_case {
    mf_fx_look look;                /* baked on the host for look.width x look.height */
    uint32_t seed_lo, seed_hi;
    uint8_t expect[32];             /* chained output hash computed on the host */
} mfb_case;

typedef struct mfb_times { long scan, glow, render, hash; } mfb_times;
typedef long (*mfb_clock)(void);

/* Develop the synthetic w x h frame with the given look: scan, glow, render
 * in MFB_STRIP-row strips. hash = sha256 chain over the output strips
 * (h = sha256(h || strip bytes)). mem holds the mf_fx context
 * (mf_fx_ctx_size), in/out hold MFB_STRIP rows each, hbuf 32 + strip bytes.
 * rows_cb (may be 0) sees each output strip, e.g. to write a preview;
 * yield (may be 0) runs between strips, outside the timed calls, so a
 * camera task can let other tasks run. */
int mfb_run(const mfb_case *c, const uint16_t *table, void *mem, size_t mem_len, uint16_t *in, uint16_t *out,
            uint8_t *hbuf, uint8_t hash[32], mfb_clock clk, mfb_times *t,
            void (*rows_cb)(void *ctx, const uint16_t *rows, int y0, int n, int w), void *cb_ctx,
            void (*yield)(void));

/* the synthetic scene, integer only: a log exposure ramp across (deep
 * shadow to clipped white), hue bands down, clipped blocks for halation */
void mfb_scene_rows(uint16_t *rgb, int w, int h, int y0, int n);
#endif
