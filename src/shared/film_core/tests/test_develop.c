/* SPDX-License-Identifier: GPL-2.0-only
 * Whole-frame film stage: deterministic, seed-dependent grain, bounded
 * output, mono films stay neutral, unknown films refused. */
#include "mf_core.h"
#include "common.h"
#include <math.h>
#include <string.h>

#define W 400
#define H 300

static void scene(float *rgb)
{
    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++)
        {
            float *p = rgb + 3 * (y * W + x);
            float t = (float) x / (W - 1);
            p[0] = 0.18f * t * 2; p[1] = 0.18f; p[2] = 0.18f * (1 - t) * 2;
            if (x > 300 && y < 60) p[0] = p[1] = p[2] = 1.0f;          /* a highlight for halation */
        }
}

static int develop(const uint8_t *bundle, size_t len, const char *key, uint64_t seed, float *out)
{
    scene(out);
    char err[128] = "";
    float ev;
    int rc = mf_develop_simple(bundle, len, key, out, W, H, seed, 1, 1, 1, 0, 0, &ev, err, sizeof err);
    if (rc) fprintf(stderr, "%s: %s\n", key, err);
    return rc;
}

int main(int argc, char **argv)
{
    if (argc < 2) return 2;
    size_t len;
    uint8_t *bundle = read_file(argv[1], &len);
    static float a[W * H * 3], b[W * H * 3], c[W * H * 3];
    CHECK(develop(bundle, len, "portra400", 42, a) == MF_OK);
    CHECK(develop(bundle, len, "portra400", 42, b) == MF_OK);
    CHECK(memcmp(a, b, sizeof a) == 0);
    CHECK(develop(bundle, len, "portra400", 43, c) == MF_OK);
    CHECK(memcmp(a, c, sizeof a) != 0);
    for (size_t i = 0; i < W * H * 3; i++) CHECK(a[i] >= 0 && a[i] <= 1);
    /* halation: just outside the highlight the red channel glows more than blue */
    float *nr = a + 3 * (70 * W + 340);
    CHECK(nr[0] > nr[2]);
    CHECK(develop(bundle, len, "trix400", 7, a) == MF_OK);
    for (size_t i = 0; i < W * H; i++) CHECK(a[3 * i] == a[3 * i + 1] && a[3 * i + 1] == a[3 * i + 2]);
    /* every film in the bundle develops */
    mf_bundle bb;
    CHECK(mf_bundle_parse(bundle, len, &bb) == MF_OK);
    for (int i = 0; i < bb.nfilms; i++) CHECK(develop(bundle, len, bb.films[i].key, 1, a) == MF_OK);
    mf_bundle_free(&bb);
    CHECK(develop(bundle, len, "no-such-film", 1, a) == MF_E_UNSUPPORTED);
    puts("develop: ok");
    free(bundle);
    return 0;
}
