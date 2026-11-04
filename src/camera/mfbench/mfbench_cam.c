/* SPDX-License-Identifier: GPL-2.0-only
 * The measurements of MFBENCH.FLT (module glue in mfbench.c), which measures
 * what the offline developer needs on the camera, and checks that the film
 * core produces bit-identical output to the Linux host:
 *   - heap: CHDK combined/system meminfo, largest malloc block
 *   - mf_fx on the synthetic frame at each size in A/CHDK/DATA/MFBENCH.BIN:
 *     time per pass, output hash vs the host's
 *   - SHA-256 speed, SD write/read speed
 * Results go to A/MFBENCH.TXT (rewritten after every step, so a crash still
 * leaves what was measured) and a 720x480 preview to A/MFBENCH.PPM.
 * Read-only towards the camera: it only allocates heap and writes those files
 * (plus a temporary A/MFBTEST.TMP, removed again). */
#include "stdlib.h"
#include "string.h"
#include "stdio.h"
#include "clock.h"
#include "meminfo.h"
#include "mfbench.h"

#define LOG_PATH "A/MFBENCH.TXT"
#define DATA_PATH "A/CHDK/DATA/MFBENCH.BIN"
#define PPM_PATH "A/MFBENCH.PPM"
#define TMP_PATH "A/MFBTEST.TMP"

static char logbuf[6144];
static int loglen;

static void log_flush(void)
{
    FILE *f = fopen(LOG_PATH, "wb");
    if (f)
    {
        fwrite(logbuf, 1, loglen, f);
        fclose(f);
    }
}

static void say(const char *s)
{
    int n = strlen(s);
    if (loglen + n >= (int) sizeof logbuf) n = sizeof logbuf - 1 - loglen;
    memcpy(logbuf + loglen, s, n);
    loglen += n;
    logbuf[loglen] = 0;
}

static char line[160];

static void hex32(char *dst, const uint8_t *h)
{
    static const char d[] = "0123456789abcdef";
    for (int i = 0; i < 32; i++) { dst[2 * i] = d[h[i] >> 4]; dst[2 * i + 1] = d[h[i] & 15]; }
    dst[64] = 0;
}

static long tick(void) { return get_tick_count(); }

static void meminfo(const char *what, cam_meminfo *m)
{
    sprintf(line, "mem %s: free %d, largest free block %d, total %d, allocated %d\n", what, m->free_size,
            m->free_block_max_size, m->total_size, m->allocated_size);
    say(line);
}

static int largest_malloc(void)
{
    int lo = 0, hi = 64 << 20;                         /* binary search to 4 KB */
    while (hi - lo > 4096)
    {
        int mid = lo + (hi - lo) / 2;
        void *p = malloc(mid);
        if (p) { free(p); lo = mid; }
        else hi = mid;
    }
    return lo;
}

static FILE *ppm;
static uint8_t ppm_row[3 * 720];

static void ppm_rows(void *ctx, const uint16_t *rows, int y0, int n, int w)
{
    (void) ctx; (void) y0;
    if (!ppm || w > 720) return;
    for (int r = 0; r < n; r++)
    {
        const uint16_t *s = rows + 3 * (size_t) r * w;
        for (int i = 0; i < 3 * w; i++) ppm_row[i] = (uint8_t) ((s[i] * 255u + 32767u) / 65535u);
        fwrite(ppm_row, 1, 3 * w, ppm);
    }
}

static void bench_cases(void)
{
    mfb_header hd;
    FILE *f = fopen(DATA_PATH, "rb");
    if (!f) { say("FAIL: cannot open " DATA_PATH "\n"); return; }
    long t0 = tick();
    if (fread(&hd, sizeof hd, 1, f) != 1 || memcmp(hd.magic, MFB_MAGIC, 8) != 0 || hd.ncases > MFB_MAX_CASES
        || hd.table_bytes != MF_NGRID * 3 * 2)
    {
        say("FAIL: bad " DATA_PATH "\n");
        fclose(f);
        return;
    }
    static mfb_case cs[MFB_MAX_CASES];
    uint16_t *table = malloc(hd.table_bytes);
    if (!table) { say("FAIL: no memory for the film table\n"); fclose(f); return; }
    int ok = fread(cs, sizeof cs[0], hd.ncases, f) == (long) hd.ncases && fread(table, 1, hd.table_bytes, f) == (long) hd.table_bytes;
    fclose(f);
    sprintf(line, "data: film %s, %d case(s), table %d B, read in %d ms\n", hd.film, hd.ncases, hd.table_bytes,
            (int) (tick() - t0));
    say(line);
    if (!ok) { say("FAIL: short read\n"); free(table); return; }
    log_flush();
    for (unsigned i = 0; i < hd.ncases; i++)
    {
        int w = cs[i].look.width, h = cs[i].look.height;
        size_t mlen = mf_fx_ctx_size(w, h), sb = 3 * (size_t) w * MFB_STRIP * 2;
        void *mem = malloc(mlen);
        uint16_t *in = malloc(sb), *out = malloc(sb);
        uint8_t *hb = malloc(32 + sb);
        sprintf(line, "fx %dx%d: ctx %d B + strips %d B\n", w, h, (int) mlen, (int) (3 * sb + 32));
        say(line);
        if (!mem || !in || !out || !hb)
        {
            say("FAIL: malloc\n");
        }
        else
        {
            ppm = 0;
            if (i == 0 && w <= 720 && (ppm = fopen(PPM_PATH, "wb")) != 0)
            {
                sprintf(line, "P6\n%d %d\n255\n", w, h);
                fwrite(line, 1, strlen(line), ppm);
            }
            mfb_times t;
            uint8_t hash[32];
            long ta = tick();
            int rc = mfb_run(&cs[i], table, mem, mlen, in, out, hb, hash, tick, &t, ppm_rows, 0);
            long total = tick() - ta;
            if (ppm) fclose(ppm);
            ppm = 0;
            if (rc != MF_OK)
            {
                sprintf(line, "FAIL: mfb_run %d\n", rc);
                say(line);
            }
            else
            {
                char hx[65];
                hex32(hx, hash);
                sprintf(line, "  ms: scan %d, glow %d, render %d, hash %d, total incl. scene+io %d\n", (int) t.scan,
                        (int) t.glow, (int) t.render, (int) t.hash, (int) total);
                say(line);
                sprintf(line, "  out %s %s\n", hx, memcmp(hash, cs[i].expect, 32) == 0 ? "MATCHES host" : "DIFFERS from host");
                say(line);
                if (memcmp(hash, cs[i].expect, 32) != 0)
                {
                    hex32(hx, cs[i].expect);
                    sprintf(line, "  host %s\n", hx);
                    say(line);
                }
            }
        }
        free(hb), free(out), free(in), free(mem);
        log_flush();
    }
    free(table);
}

static void bench_sha_and_sd(void)
{
    int n = 1 << 20;
    uint8_t *buf = malloc(n);
    if (!buf) { n = 256 << 10; buf = malloc(n); }
    if (!buf) { say("FAIL: no buffer for sha/sd\n"); return; }
    for (int i = 0; i < n; i++) buf[i] = (uint8_t) (i * 131 + (i >> 9));
    uint8_t h[32];
    long t0 = tick();
    mf_sha256(buf, n, h);
    sprintf(line, "sha256 %d KB: %d ms\n", n >> 10, (int) (tick() - t0));
    say(line);
    log_flush();

    int total = 8 << 20, chunk = n < (256 << 10) ? n : (256 << 10), done = 0;
    FILE *f = fopen(TMP_PATH, "wb");
    if (!f) { say("FAIL: cannot create " TMP_PATH "\n"); free(buf); return; }
    t0 = tick();
    while (done < total && fwrite(buf, 1, chunk, f) == chunk) done += chunk;
    fclose(f);
    long tw = tick() - t0;
    sprintf(line, "sd write %d KB in %d KB chunks: %d ms\n", done >> 10, chunk >> 10, (int) tw);
    say(line);
    f = fopen(TMP_PATH, "rb");
    int got = 0;
    if (f)
    {
        t0 = tick();
        long r;
        while ((r = fread(buf, 1, chunk, f)) > 0) got += r;
        fclose(f);
        sprintf(line, "sd read %d KB: %d ms\n", got >> 10, (int) (tick() - t0));
        say(line);
    }
    remove(TMP_PATH);
    free(buf);
    log_flush();
}

/* called by the module glue; returns the message to show */
const char *mfb_camera_main(void)
{
    cam_meminfo m;
    loglen = 0;
    say("M-Film camera bench (MFBENCH.FLT)\n");
    sprintf(line, "ticks at start %d\n", (int) tick());
    say(line);
    GetCombinedMemInfo(&m);
    meminfo("combined", &m);
    GetMemInfo(&m);
    meminfo("system", &m);
    sprintf(line, "largest malloc %d\n", largest_malloc());
    say(line);
    log_flush();
    bench_cases();
    bench_sha_and_sd();
    GetCombinedMemInfo(&m);
    meminfo("combined after", &m);
    say("done\n");
    log_flush();
    return "Done: see A/MFBENCH.TXT";
}
