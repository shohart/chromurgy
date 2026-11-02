/* SPDX-License-Identifier: GPL-2.0-only
 * mf_film_color() must reproduce upstream fos_film_color() on the golden grid. */
#include "mf_core.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "usage: %s golden.txt\n", argv[0]); return 2; }
    FILE *f = fopen(argv[1], "r");
    if (!f) { perror(argv[1]); return 2; }
    char line[512], key[64];
    long n = 0, exact = 0, bad = 0;
    float maxd = 0;
    while (fgets(line, sizeof line, f))
    {
        if (line[0] == '#') continue;
        float in[3], want[3], got[3];
        if (sscanf(line, "%63s %a %a %a %a %a %a", key, &in[0], &in[1], &in[2],
                   &want[0], &want[1], &want[2]) != 7) { fprintf(stderr, "bad line: %s", line); return 2; }
        const struct mf_look *L = mf_look_find(key);
        if (!L) { fprintf(stderr, "unknown look %s\n", key); return 1; }
        mf_film_color(L, in, got);
        int same = 1;
        for (int c = 0; c < 3; c++)
        {
            float d = fabsf(got[c] - want[c]);
            if (d > maxd) maxd = d;
            if (got[c] != want[c]) same = 0;
            if (d > 1e-6f) bad++;
        }
        exact += same;
        n++;
    }
    fclose(f);
    if (mf_look_find("no-such-film") != NULL) { fprintf(stderr, "unknown film must not resolve\n"); return 1; }
    printf("%ld vectors, %ld bit-exact, max |diff| %g, %ld channels over 1e-6\n", n, exact, (double) maxd, bad);
    return (n > 0 && bad == 0) ? 0 : 1;
}
