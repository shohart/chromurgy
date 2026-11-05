/* SPDX-License-Identifier: GPL-2.0-only
 * The camera developer on the host, for tests and validation against the
 * server: the same code and data files the camera uses.
 *
 *     mfdev_host MFCAM.BIN MFDEV.BIN FILM SEED_HEX IN.DNG OUT.JPG [OUT.MFV]
 * prints: rc, timings, focal, orientation-independent stats as key=value */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "mfd.h"

static void *h_open(const char *p, int w) { return fopen(p, w ? "w+b" : "rb"); }
static long h_read(void *f, void *b, long n) { return (long) fread(b, 1, (size_t) n, f); }
static long h_write(void *f, const void *b, long n) { return (long) fwrite(b, 1, (size_t) n, f); }
static int h_seek(void *f, long o) { return fseek(f, o, SEEK_SET); }
static void h_close(void *f) { fclose(f); }
static int h_remove(const char *p) { return remove(p); }
static long peak, cur;
/* camera-like heap limits (tests): MFDEV_HEAP=total,largest in bytes */
static long heap_total = -1, heap_largest = -1;
static void *h_alloc(size_t n)
{
    if (heap_largest >= 0 && ((long) n > heap_largest || cur + (long) n > heap_total)) return 0;
    size_t *p = malloc(n + sizeof(size_t));
    if (!p) return 0;
    *p = n, cur += (long) n;
    memset(p + 1, 0xA5, n);
    if (getenv("MFDEV_ALLOC_LOG")) fprintf(stderr, "alloc %zu (now %ld)\n", n, cur);                       /* like the camera: fresh heap is not zeroed */
    if (cur > peak) peak = cur;
    return p + 1;
}
static void h_release(void *q) { size_t *p = (size_t *) q - 1; cur -= (long) *p; free(p); }
/* with MFDEV_CANCEL_AT the clock runs fast (40 ms a call), so the developer
 * yields often and the stop lands where the test asks (it yields by time) */
static int fast_clock;
static long fake_ms;
static long h_tick(void)
{
    if (fast_clock) return fake_ms += 40;
    return (long) (clock() * 1000.0 / CLOCKS_PER_SEC);
}
static int cancel_limit = -1;
static volatile int *cancel_flag, *progress_seen;
static void h_yield(void) { if (cancel_flag && *progress_seen >= cancel_limit) *cancel_flag = 1; }

int main(int argc, char **argv)
{
    if (argc < 7) { fprintf(stderr, "usage: mfdev_host MFCAM.BIN MFDEV.BIN FILM SEED_HEX IN.DNG OUT.JPG [OUT.MFV]\n"); return 2; }
    const char *hl = getenv("MFDEV_HEAP");
    if (hl && sscanf(hl, "%ld,%ld", &heap_total, &heap_largest) != 2) heap_total = heap_largest = -1;
    mfd_env env = {h_open, h_read, h_write, h_seek, h_close, h_remove, h_alloc, h_release, h_tick, h_yield};
    static mfd_camera cam;
    static mf_table table;
    mf_fx_look look;
    int rc = mfd_camera_load(&env, argv[1], &cam);
    if (rc) { printf("rc=%d stage=camera\n", rc); return 1; }
    rc = mfd_film_load(&env, argv[2], argv[3], &look, &table.v[0][0]);
    if (rc) { printf("rc=%d stage=film\n", rc); return 1; }
    char tmp[4096];
    snprintf(tmp, sizeof tmp, "%s.tmp", argv[6]);
    volatile int prog = 0, cancel = 0;
    const char *cancel_at = getenv("MFDEV_CANCEL_AT");   /* permille: stop there (tests) */
    mfd_job job = {.dng_path = argv[5], .jpeg_path = argv[6], .tmp_path = tmp, .mfv_path = argc > 7 ? argv[7] : 0,
                   .cam = &cam, .look = &look, .table = &table.v[0][0], .seed = strtoull(argv[4], 0, 16),
                   .out_w = look.width, .out_h = look.height, .quality = 90, .hash = 1, .progress = &prog,
                   .cancel = &cancel};
    mfd_result res;
    if (cancel_at) { cancel_limit = atoi(cancel_at); cancel_flag = &cancel; progress_seen = &prog; fast_clock = 1; }
    rc = mfd_develop(&env, &job, &res);
    printf("rc=%d progress=%d w=%d h=%d focal_q8=%d scanner_ev_q16=%d ms_total=%ld mem_peak=%ld ring_rows=%u "
           "jpeg_bytes=%u ms_dng_io=%ld ms_bin=%ld ms_lens=%ld ms_scan=%ld ms_glow=%ld ms_render=%ld ms_tmp_io=%ld "
           "ms_jpeg=%ld ms_view=%ld sha256=", rc, prog, job.out_w, job.out_h, res.focal_q8, res.scanner_ev_q16,
           res.ms_total, peak, res.ring_rows, res.jpeg_bytes, res.ms_dng_io, res.ms_bin, res.ms_lens, res.ms_scan,
           res.ms_glow, res.ms_render, res.ms_tmp_io, res.ms_jpeg, res.ms_view);
    for (int i = 0; i < 32; i++) printf("%02x", res.dng_sha256[i]);
    printf("\n");
    return rc ? 1 : 0;
}
