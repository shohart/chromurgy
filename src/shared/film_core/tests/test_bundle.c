/* SPDX-License-Identifier: GPL-2.0-only
 * The bundle holds all 72 M-Film films; its 8 built-in looks equal
 * upstream fos_looks.c; damaged bundles are refused. */
#include "mf_core.h"
#include "common.h"
#include <string.h>

static int same_look(const struct mf_look *a, const struct mf_look *b)
{
    if (strcmp(a->key, b->key) || a->balance != b->balance || a->slide != b->slide || a->ev != b->ev ||
        a->sat != b->sat || a->nhues != b->nhues || a->halation != b->halation || a->hal_thr != b->hal_thr ||
        a->grain != b->grain || a->grain_size != b->grain_size || a->mono != b->mono) return 0;
    for (int c = 0; c < 3; c++)
        if (a->contrast[c] != b->contrast[c] || a->pivot[c] != b->pivot[c] || a->black[c] != b->black[c] ||
            a->white[c] != b->white[c] || a->hal_tint[c] != b->hal_tint[c] || a->mono_mix[c] != b->mono_mix[c]) return 0;
    for (int i = 0; i < a->nhues; i++)
        if (a->hues[i].from != b->hues[i].from || a->hues[i].to != b->hues[i].to ||
            a->hues[i].amount != b->hues[i].amount || a->hues[i].chroma != b->hues[i].chroma) return 0;
    return 1;
}

int main(int argc, char **argv)
{
    if (argc < 2) return 2;
    size_t len;
    uint8_t *data = read_file(argv[1], &len);
    mf_bundle b;
    CHECK(mf_bundle_parse(data, len, &b) == MF_OK);
    CHECK(b.nfilms == 72);
    int tables = 0;
    for (int i = 0; i < b.nfilms; i++) tables += b.films[i].table != NULL;
    CHECK(tables == 63);
    for (int i = 0; i < mf_builtin_nlooks; i++)
    {
        const struct mf_film *f = mf_bundle_find(&b, mf_builtin_looks[i].key);
        CHECK(f != NULL);
        if (!same_look(&f->look, &mf_builtin_looks[i])) { fprintf(stderr, "look %s differs\n", f->key); return 1; }
    }
    CHECK(mf_bundle_find(&b, "no-such-film") == NULL);
    const struct mf_film *k = mf_bundle_find(&b, "kodachrome64");
    CHECK(k && k->table && k->kind == MF_KIND_SLIDE && k->iso == 64 && !strcmp(k->name, "Kodak Kodachrome 64"));
    mf_bundle_free(&b);

    /* damaged copies */
    uint8_t *bad = malloc(len);
    memcpy(bad, data, len); bad[0] = 'X';
    CHECK(mf_bundle_parse(bad, len, &b) != MF_OK);
    CHECK(mf_bundle_parse(data, len - 1000, &b) != MF_OK);     /* a table cut short */
    CHECK(mf_bundle_parse(data, 100, &b) != MF_OK);
    memcpy(bad, data, len); memset(bad + 20, 'A', 24);           /* key without NUL */
    CHECK(mf_bundle_parse(bad, len, &b) != MF_OK);
    printf("bundle: %d films, %d LUT tables, builtin looks identical\n", 72, tables);
    free(bad);
    free(data);
    return 0;
}
