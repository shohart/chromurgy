/* SPDX-License-Identifier: GPL-2.0-only
 * The camera side of the developer, linked into CHDK's Lua module (see
 * src/camera/chdk/mfilm_lua.c for the Lua functions, tools/build_chdk16.sh).
 *
 * One frame at a time, in its own low-priority task: a long computation in
 * the script (GUI) task starved the camera and it powered off (first
 * MFBENCH run, 2026-11-04). The task yields after every strip.
 * Plain int/char interface so the Lua glue needs none of these headers. */
#include "stdlib.h"
#include "stdio.h"
#include "string.h"
#include "mfd.h"

extern int CreateTask(const char *name, int prio, int stack_size, void *entry);
extern void ExitTask(void);
extern void msleep(long msec);
extern int get_tick_count(void);

enum { ST_IDLE = 0, ST_RUNNING = 1, ST_DONE = 2, ST_ERROR = 3 };

static struct {
    volatile int state, progress, cancel;
    int rc, ms, focal_q8;
    char camf[64], devf[64], film[32], dng[64], jpg[64], mfv[64], tmp[64];
    uint32_t seed_hi, seed_lo;
} S;

/* ------------------------------------------------------------ env: CHDK file API */

static void *c_open(const char *p, int w)
{
    int fd = w ? open(p, O_WRONLY | O_CREAT | O_TRUNC, 0777) : open(p, O_RDONLY, 0777);
    return fd < 0 ? 0 : (void *) (long) (fd + 1);
}
static long c_read(void *f, void *b, long n) { return read((int) (long) f - 1, b, n); }
static long c_write(void *f, const void *b, long n) { return write((int) (long) f - 1, b, n); }
static int c_seek(void *f, long o) { return lseek((int) (long) f - 1, o, SEEK_SET) == o ? 0 : -1; }
static void c_close(void *f) { close((int) (long) f - 1); }
static int c_remove(const char *p) { return remove(p); }
static void *c_alloc(size_t n) { return malloc(n); }
static void c_release(void *p) { free(p); }
static long c_tick(void) { return get_tick_count(); }
static void c_yield(void) { msleep(10); }

static const mfd_env ENV = {c_open, c_read, c_write, c_seek, c_close, c_remove, c_alloc, c_release, c_tick, c_yield};

static void dev_task(void)
{
    int t0 = get_tick_count(), rc;
    mfd_camera *cam = malloc(sizeof *cam);
    uint16_t *table = malloc(sizeof(mf_table));
    mf_fx_look look;
    if (!cam || !table) rc = MFD_E_MEM;
    else if ((rc = mfd_camera_load(&ENV, S.camf, cam)) == MFD_OK && (rc = mfd_film_load(&ENV, S.devf, S.film, &look, table)) == MFD_OK)
    {
        mfd_job job;
        mfd_result res;
        memset(&job, 0, sizeof job);
        job.dng_path = S.dng, job.jpeg_path = S.jpg[0] ? S.jpg : 0, job.mfv_path = S.mfv[0] ? S.mfv : 0;
        job.tmp_path = S.tmp, job.cam = cam, job.look = &look, job.table = table;
        job.seed = (uint64_t) S.seed_hi << 32 | S.seed_lo;
        job.out_w = look.width, job.out_h = look.height, job.quality = 90, job.hash = 0;
        job.progress = &S.progress, job.cancel = &S.cancel;
        rc = mfd_develop(&ENV, &job, &res);
        S.focal_q8 = res.focal_q8;
    }
    if (cam) free(cam);
    if (table) free(table);
    S.rc = rc;
    S.ms = get_tick_count() - t0;
    S.state = rc == MFD_OK ? ST_DONE : ST_ERROR;
    ExitTask();
}

static void copy(char *dst, const char *src, int cap)
{
    int n = src ? (int) strlen(src) : 0;
    if (n > cap - 1) n = cap - 1;
    if (n) memcpy(dst, src, n);
    dst[n] = 0;
}

/* 0 started; -1 busy; -2 bad arguments */
int mfdc_start(const char *camf, const char *devf, const char *film, const char *dng, const char *jpg,
               const char *mfv, const char *tmp, unsigned seed_hi, unsigned seed_lo)
{
    if (S.state == ST_RUNNING) return -1;
    if (!camf || !devf || !film || !dng || !tmp || (!jpg && !mfv)) return -2;
    copy(S.camf, camf, sizeof S.camf), copy(S.devf, devf, sizeof S.devf), copy(S.film, film, sizeof S.film);
    copy(S.dng, dng, sizeof S.dng), copy(S.jpg, jpg, sizeof S.jpg), copy(S.mfv, mfv, sizeof S.mfv);
    copy(S.tmp, tmp, sizeof S.tmp);
    S.seed_hi = seed_hi, S.seed_lo = seed_lo;
    S.progress = 0, S.cancel = 0, S.rc = 0, S.ms = 0, S.focal_q8 = 0;
    S.state = ST_RUNNING;
    CreateTask("MFDevelop", 0x1A, 0x4000, (void *) dev_task);   /* below spytask, as CHDK's DNG reverser */
    return 0;
}

void mfdc_status(int *state, int *permille, int *rc, int *ms)
{
    *state = S.state, *permille = S.progress, *rc = S.rc, *ms = S.ms;
}

void mfdc_cancel(void) { if (S.state == ST_RUNNING) S.cancel = 1; }

int mfdc_busy(void) { return S.state == ST_RUNNING; }
