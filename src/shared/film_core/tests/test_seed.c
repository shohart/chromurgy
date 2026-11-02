/* SPDX-License-Identifier: GPL-2.0-only
 * SHA-256 against FIPS vectors; seed derivation against Python hashlib. */
#include "mf_core.h"
#include <stdio.h>
#include <string.h>

static int hex_eq(const uint8_t *h, const char *want)
{
    char s[65];
    for (int i = 0; i < 32; i++) sprintf(s + 2 * i, "%02x", h[i]);
    if (strcmp(s, want)) { fprintf(stderr, "got %s want %s\n", s, want); return 0; }
    return 1;
}

int main(void)
{
    uint8_t h[32];
    static char big[1000];
    int ok = 1;
    mf_sha256("abc", 3, h);
    ok &= hex_eq(h, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
    mf_sha256("", 0, h);
    ok &= hex_eq(h, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    memset(big, 'a', sizeof big);
    mf_sha256(big, sizeof big, h);
    ok &= hex_eq(h, "41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3");

    /* python: sha256(b'mfilm-seed-v1\0sx510hs-demo-001\0r1\0r1-0001\0portra400\0recipe-v1\0' b'0')[:8] */
    uint64_t s = 0;
    ok &= mf_frame_seed("sx510hs-demo-001", "r1", "r1-0001", "portra400", "recipe-v1", 0, &s) == MF_OK;
    if (s != 0xe64520a3e9d1b46cULL) { fprintf(stderr, "seed %016llx\n", (unsigned long long) s); ok = 0; }
    uint64_t s2 = 0;
    mf_frame_seed("sx510hs-demo-001", "r1", "r1-0002", "portra400", "recipe-v1", 0, &s2);
    if (s2 == s) { fprintf(stderr, "frames must get different seeds\n"); ok = 0; }
    ok &= mf_frame_seed(NULL, "r", "f", "p", "v", 0, &s) == MF_E_INVALID_ARG;
    puts(ok ? "seed: ok" : "seed: FAIL");
    return ok ? 0 : 1;
}
