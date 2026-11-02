/* SPDX-License-Identifier: GPL-2.0-only
 * Grain noise: same value whatever order/tiling visits a pixel; sane stats. */
#include "mf_core.h"
#include <math.h>
#include <stdio.h>

#define W 257
#define H 131

static int32_t ref[H][W][3];

int main(void)
{
    const uint64_t seed = 0xe64520a3e9d1b46cULL;
    double sum = 0, sq = 0;
    for (uint32_t y = 0; y < H; y++)
        for (uint32_t x = 0; x < W; x++)
            for (uint32_t c = 0; c < 3; c++)
            {
                int32_t v = ref[y][x][c] = mf_noise(seed, x, y, c);
                if (v < -32768 || v > 32767) { puts("range FAIL"); return 1; }
                sum += v; sq += (double) v * v;
            }
    /* revisit in 64x32 tiles, bottom-right first */
    for (int ty = (H - 1) / 32; ty >= 0; ty--)
        for (int tx = (W - 1) / 64; tx >= 0; tx--)
            for (int y = ty * 32; y < ty * 32 + 32 && y < H; y++)
                for (int x = tx * 64 + 63; x >= tx * 64; x--)
                    if (x < W)
                        for (int c = 2; c >= 0; c--)
                            if (mf_noise(seed, (uint32_t) x, (uint32_t) y, (uint32_t) c) != ref[y][x][c])
                            { puts("tile order FAIL"); return 1; }
    double n = (double) W * H * 3, mean = sum / n, sd = sqrt(sq / n - mean * mean);
    /* uniform on [-32768, 32767]: mean ~ -0.5, sd ~ 18918 */
    printf("noise: mean %.1f sd %.1f\n", mean, sd);
    if (fabs(mean) > 300 || fabs(sd - 18918) > 300) { puts("stats FAIL"); return 1; }
    if (mf_noise(seed, 0, 0, 0) == mf_noise(seed + 1, 0, 0, 0) &&
        mf_noise(seed, 1, 0, 0) == mf_noise(seed + 1, 1, 0, 0)) { puts("seed FAIL"); return 1; }
    puts("noise: ok");
    return 0;
}
