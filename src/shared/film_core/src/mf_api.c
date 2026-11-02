/* SPDX-License-Identifier: GPL-2.0-only
 * Flat entry points for FFI callers (the Linux worker loads libmf_core.so
 * through ctypes). Only plain types cross this boundary. */
#include "mf_core.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef MF_CORE_SOURCE_HASH
#define MF_CORE_SOURCE_HASH "unknown"
#endif

int mf_abi_version(void) { return MF_CORE_ABI_VERSION; }
const char *mf_core_version(void) { return MF_CORE_SOURCE_HASH; }

static void set_err(char *err, size_t n, const char *msg)
{
    if (err && n) snprintf(err, n, "%s", msg);
}

int mf_bundle_info(const uint8_t *data, size_t len, int *nfilms, uint8_t sha256_out[MF_SHA256_LEN])
{
    mf_bundle b;
    int rc = mf_bundle_parse(data, len, &b);
    if (rc) return rc;
    if (nfilms) *nfilms = b.nfilms;
    if (sha256_out) memcpy(sha256_out, b.sha256, MF_SHA256_LEN);
    mf_bundle_free(&b);
    return MF_OK;
}

/* key of film i (0-based) into buf; MF_E_INVALID_ARG past the end */
int mf_bundle_key(const uint8_t *data, size_t len, int i, char *buf, size_t n)
{
    mf_bundle b;
    int rc = mf_bundle_parse(data, len, &b);
    if (rc) return rc;
    rc = MF_E_INVALID_ARG;
    if (i >= 0 && i < b.nfilms && buf && n) { snprintf(buf, n, "%s", b.films[i].key); rc = MF_OK; }
    mf_bundle_free(&b);
    return rc;
}

int mf_develop_simple(const uint8_t *bundle, size_t len, const char *key, float *rgb, int w, int h,
                      uint64_t grain_seed, float grain_scale, float halation_scale, float softness_scale,
                      float exposure_ev, int reference_width, float *scanner_ev_out, char *err, size_t errlen)
{
    mf_bundle b;
    int rc = mf_bundle_parse(bundle, len, &b);
    if (rc) { set_err(err, errlen, "invalid profile bundle"); return rc; }
    const struct mf_film *f = mf_bundle_find(&b, key);
    if (!f)
    {
        set_err(err, errlen, "UNSUPPORTED_PROFILE: film not in bundle");
        mf_bundle_free(&b);
        return MF_E_UNSUPPORTED;
    }
    mf_table *t = malloc(sizeof(*t));
    if (!t) { mf_bundle_free(&b); set_err(err, errlen, "out of memory"); return MF_E_INVALID_ARG; }
    mf_table_from_film(f, t);
    if (scanner_ev_out) *scanner_ev_out = mf_scanner_ev(f, rgb, w, h);
    mf_develop_params p = { grain_seed, grain_scale, halation_scale, softness_scale, exposure_ev, reference_width };
    rc = mf_develop_frame(f, t, rgb, w, h, &p);
    if (rc) set_err(err, errlen, "develop failed");
    free(t);
    mf_bundle_free(&b);
    return rc;
}
