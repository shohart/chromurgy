/* SPDX-License-Identifier: GPL-2.0-only
 * mfd: the camera's offline developer (docs/07 "Offline execution").
 * CHDK DNG -> quarter-resolution linear sRGB (LibRaw's daylight transform,
 * fitted) -> lens geometry (the server's table, fixed point) -> mf_fx film
 * passes -> baseline JPEG. Integer only, streamed, no float, no 64-bit
 * division; the same sources build for the host (tests) and as part of a
 * CHDK module. All I/O and memory goes through mfd_env so neither side
 * depends on the other's libc. */
#ifndef MFD_H
#define MFD_H
#include <stdint.h>
#include <stddef.h>
#include "mf_core.h"

#define MFD_OK 0
#define MFD_E_IO -20
#define MFD_E_DNG -21          /* not a DNG this developer understands */
#define MFD_E_MEM -22
#define MFD_E_DATA -23         /* bad MFDEV.BIN */
#define MFD_E_LENS -24
#define MFD_E_CANCEL -25

typedef struct mfd_env {
    void *(*open)(const char *path, int write);        /* 0 on failure */
    long (*read)(void *f, void *buf, long n);
    long (*write)(void *f, const void *buf, long n);
    int (*seek)(void *f, long off);                    /* absolute; 0 ok */
    void (*close)(void *f);
    int (*remove)(const char *path);
    void *(*alloc)(size_t n);
    void (*release)(void *p);
    long (*tick)(void);                                /* ms */
    void (*yield)(void);                               /* may be 0 */
} mfd_env;

/* streaming SHA-256 (the DNG is hashed while it is read) */
typedef struct mfd_sha {
    uint32_t h[8];
    uint8_t buf[64];
    uint32_t used;
    uint32_t len_lo, len_hi;
} mfd_sha;
void mfd_sha_init(mfd_sha *s);
void mfd_sha_update(mfd_sha *s, const void *data, size_t n);
void mfd_sha_final(mfd_sha *s, uint8_t out[32]);

/* what the developer needs from a CHDK DNG */
typedef struct mfd_dng {
    uint32_t raw_w, raw_h, strip_off, strip_bytes, row_bytes;
    uint32_t act_top, act_left, vis_w, vis_h;          /* ActiveArea */
    uint32_t black, white;
    uint32_t focal_num, focal_den;
    uint32_t orientation;      /* TIFF Orientation (1 normal, 6 = 90 CW, 8 = 90 CCW, 3 = 180) */
    uint8_t cfa[4];                                    /* 0 R 1 G 2 B, row-major 2x2 */
    char datetime[20];
    char model[32];
} mfd_dng;
/* parse the header bytes [0, len) (everything before the raw strip) */
int mfd_dng_parse(const uint8_t *hdr, size_t len, mfd_dng *d);

/* lens table entry (fixed point), see profiles/lenses/ (JSON) */
typedef struct mfd_lens {
    int32_t focal_q8;          /* mm * 256 */
    int32_t cx_q8, cy_q8;      /* raw visible px * 256 */
    int32_t s_q24, k1_q24, k2_q24, k3_q24;
} mfd_lens;

/* camera constants, baked on the host (tools: mfdev_gen) */
#define MFD_MAX_LENS 24
typedef struct mfd_camera {
    int32_t wb_q16[3];         /* lin = (raw - black) * wb_q16 >> 16, Q15 (32768 = white), before clip */
    int32_t m_q12[9];          /* camera RGB -> linear sRGB, rows */
    int32_t jpeg_w, jpeg_h;    /* the camera JPEG frame the lens table maps from (4000x3000) */
    int32_t nlens;
    mfd_lens lens[MFD_MAX_LENS];
} mfd_camera;

/* the camera develops at this size (4:3, the JPEG frame scaled); mf_fx needs no
 * spatial kernel there for any film. 800x600 (was 1024x768 in 0.4-0.5.3): the
 * camera's frames are for its 720x480 viewer; 39% fewer pixels to develop. */
#define MFD_OUT_W 800
#define MFD_OUT_H 600

/* MFDEV.BIN: every film baked for MFD_OUT_W x MFD_OUT_H (host: mfdev_gen) */
#define MFD_DEVFILE_MAGIC "MFDEV001"
typedef struct mfd_devfile_header {
    char magic[8];
    uint32_t nfilms, width, height, block_bytes;    /* block = mf_fx_look + mf_table */
} mfd_devfile_header;
typedef struct mfd_devfile_entry {
    char key[28];
    uint32_t offset;
} mfd_devfile_entry;

/* MFCAM.BIN: "MFCAM001" + mfd_camera (host: mfilm_server.camera_dev) */
#define MFD_CAMFILE_MAGIC "MFCAM001"

/* the viewer frame (src/server/mfilm_server/camera_view.py): 720x480 UYVYYY */
#define MFD_VIEW_W 720
#define MFD_VIEW_H 480

typedef struct mfd_job {
    const char *dng_path, *jpeg_path, *tmp_path;
    const char *mfv_path;      /* viewer frame, or 0 */
    const mfd_camera *cam;
    const mf_fx_look *look;    /* baked for out_w x out_h */
    const uint16_t *table;     /* the film's 33^3 table */
    uint64_t seed;
    int out_w, out_h, quality;
    int hash;                  /* 1: SHA-256 of the DNG in res (adds ~10 s on the camera) */
    volatile int *progress;    /* 0..1000 while running, or 0 */
    volatile int *cancel;      /* set non-zero to stop, or 0 */
} mfd_job;

typedef struct mfd_result {
    uint8_t dng_sha256[32];
    int32_t scanner_ev_q16;
    long ms_read, ms_scan, ms_glow, ms_render, ms_total;
    /* finer split (camera profiling, DEV timings in APP.LOG) */
    long ms_dng_io, ms_bin, ms_lens, ms_tmp_io, ms_jpeg, ms_view, ms_yield;
    uint32_t yields;
    uint32_t ring_rows, ring_bytes, mem_peak;
    uint32_t jpeg_bytes;
    int32_t focal_q8;
} mfd_result;

int mfd_develop(const mfd_env *env, const mfd_job *job, mfd_result *res);

/* viewer frame writer (mfd_view.c), fed with the developed 8-bit rows */
typedef struct mfd_view mfd_view;
size_t mfd_view_size(void);
int mfd_view_begin(mfd_view *v, const mfd_env *env, const char *path, int w, int h, int orientation);
int mfd_view_rows(mfd_view *v, const uint8_t *rgb, int y0, int n);
int mfd_view_end(mfd_view *v);

/* load one film's look + table from MFDEV.BIN into caller memory (table: MF_NGRID*3 uint16) */
int mfd_film_load(const mfd_env *env, const char *path, const char *key, mf_fx_look *look, uint16_t *table);
/* load MFCAM.BIN */
int mfd_camera_load(const mfd_env *env, const char *path, mfd_camera *cam);

/* lens: output pixel centre (Q8, JPEG-frame coordinates) -> raw visible (Q8) */
int mfd_lens_at(const mfd_camera *cam, int32_t focal_q8, int32_t jx_q8, int32_t jy_q8, int32_t *rx_q8,
                int32_t *ry_q8);

/* baseline JPEG, 4:4:4, streamed in 8-row bands */
typedef struct mfd_jpeg mfd_jpeg;
size_t mfd_jpeg_size(void);
int mfd_jpeg_begin(mfd_jpeg *j, const mfd_env *env, void *f, int w, int h, int quality);
int mfd_jpeg_rows(mfd_jpeg *j, const uint8_t *rgb, int n);    /* n = 8 except the last band */
int mfd_jpeg_end(mfd_jpeg *j, uint32_t *bytes);
#endif
