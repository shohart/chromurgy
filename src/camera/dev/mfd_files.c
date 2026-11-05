/* SPDX-License-Identifier: GPL-2.0-only
 * MFDEV.BIN (films) and MFCAM.BIN (camera constants) readers, through mfd_env. */
#include <string.h>
#include "mfd.h"

int mfd_film_load(const mfd_env *env, const char *path, const char *key, mf_fx_look *look, uint16_t *table)
{
    void *f = env->open(path, 0);
    if (!f) return MFD_E_IO;
    int rc = MFD_E_DATA;
    mfd_devfile_header hd;
    mfd_devfile_entry e;
    if (env->read(f, &hd, sizeof hd) != (long) sizeof hd || memcmp(hd.magic, MFD_DEVFILE_MAGIC, 8)
        || hd.block_bytes != sizeof(mf_fx_look) + sizeof(mf_table) || hd.nfilms > 4096)
        goto out;
    for (uint32_t i = 0; i < hd.nfilms; i++)
    {
        if (env->read(f, &e, sizeof e) != (long) sizeof e) goto out;
        e.key[sizeof e.key - 1] = 0;
        if (strcmp(e.key, key) != 0) continue;
        if (env->seek(f, (long) e.offset)) { rc = MFD_E_IO; goto out; }
        if (env->read(f, look, sizeof *look) != (long) sizeof *look
            || env->read(f, table, (long) sizeof(mf_table)) != (long) sizeof(mf_table)) { rc = MFD_E_IO; goto out; }
        rc = (look->width == (int32_t) hd.width && look->height == (int32_t) hd.height) ? MFD_OK : MFD_E_DATA;
        goto out;
    }
    rc = MFD_E_DATA;                                /* film not in the file */
out:
    env->close(f);
    return rc;
}

int mfd_camera_load(const mfd_env *env, const char *path, mfd_camera *cam)
{
    void *f = env->open(path, 0);
    if (!f) return MFD_E_IO;
    char magic[8];
    int rc = MFD_OK;
    if (env->read(f, magic, 8) != 8 || memcmp(magic, MFD_CAMFILE_MAGIC, 8)
        || env->read(f, cam, sizeof *cam) != (long) sizeof *cam || cam->nlens < 1 || cam->nlens > MFD_MAX_LENS)
        rc = MFD_E_DATA;
    env->close(f);
    return rc;
}
