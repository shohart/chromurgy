/* SPDX-License-Identifier: GPL-2.0-only
 *
 * Host side of the fixed-point stage: turn a film + recipe + output size into
 * the integer constants mf_fx.c runs on. Float is fine here; this never runs
 * on the camera (a camera bundle carries the baked mf_fx_look).
 */
#include "mf_core.h"

#include <math.h>

static int32_t q(float v, float scale)
{
    float r = v * scale;
    r += r < 0 ? -0.5f : 0.5f;
    return (int32_t) r;
}

int mf_fx_look_bake(const struct mf_film *film, const mf_develop_params *p, int w, int h, mf_fx_look *out)
{
    if (!film || !p || !out || w < 2 || h < 2 || !mf_fx_ctx_size(w, h)) return MF_E_INVALID_ARG;
    mf_develop_sizes sz;
    if (mf_develop_kernels(film, p, w, &sz)) return MF_E_UNSUPPORTED;     /* needs a spatial kernel */
    const struct mf_look *L = &film->look;
    float bal[3];
    mf_film_balance(film, bal);
    out->width = w;
    out->height = h;
    out->slide = L->slide != 0;
    out->ev_q16 = q(L->ev + p->exposure_ev, 65536);
    for (int c = 0; c < 3; c++)
    {
        out->bal_q16[c] = q(bal[c], 65536);
        out->hal_q16[c] = q(L->halation * p->halation_scale > 0 ? L->halation * p->halation_scale * L->hal_tint[c] : 0,
                            65536);
    }
    out->hal_thr_q15 = q(L->hal_thr, 32768);
    out->grain_amp_q16 = L->grain * p->grain_scale > 0 ? q(sz.grain_amp, 65536) : 0;
    out->mono = L->mono != 0;
    return MF_OK;
}
