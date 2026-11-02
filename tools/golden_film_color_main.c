/* SPDX-License-Identifier: GPL-2.0-only
 * Golden-vector generator: runs the UPSTREAM fos_film_color() over a fixed
 * grid of inputs for every built-in look. Built against vendor/m-film by
 * tools/gen_golden_film_color.sh; output goes to
 * src/shared/film_core/tests/golden_film_color.txt. */
#include "fos_dev.h"
#include <stdio.h>

static const float V[] = { 0.0f, 0.002f, 0.01f, 0.045f, 0.09f, 0.18f, 0.36f, 0.72f, 1.0f, 1.6f, 4.0f };
#define NV (int) (sizeof(V) / sizeof(V[0]))

int main(void)
{
    printf("# key r g b -> R G B (upstream fos_film_color, %%a hex floats)\n");
    for (int l = 0; l < fos_nlooks; l++)
        for (int i = 0; i < NV; i++)
            for (int j = 0; j < NV; j++)
                for (int k = 0; k < NV; k++)
                {
                    float in[3] = { V[i], V[j], V[k] }, out[3];
                    fos_film_color(&fos_looks[l], in, out);
                    printf("%s %a %a %a %a %a %a\n", fos_looks[l].key,
                           (double) in[0], (double) in[1], (double) in[2],
                           (double) out[0], (double) out[1], (double) out[2]);
                }
    return 0;
}
