/* SPDX-License-Identifier: GPL-2.0-only
 * M-Film additions to CHDK's Lua (modules/luascript.c, release-1_6 r6355).
 * tools/build_chdk16.sh includes this file at the end of luascript.c's
 * helpers and registers the functions in chdk_funcs:
 *
 *   mf_viewport() -> addr, width, height, byte_width, yscale, image_offset, play
 *       The image buffer the screen shows (playback: the decoded photo,
 *       viewport_fb_d) and its geometry, for diagnostics.
 *   mf_show(path) -> true, ms | nil, error
 *       Copies an MFV file (src/server/mfilm_server/camera_view.py: "MFV1",
 *       u16 width, height, byte_width, 0, then UYVYYY rows) into that buffer.
 *       Playback mode only; the geometry must match the buffer exactly, so a
 *       wrong file can never write past it.
 *
 *   mf_overlay_clear() -> true | nil, error
 *       Makes both bitmap (overlay) buffers transparent, so Canon's playback
 *       icons do not cover the photo. The SX510 HS has two overlay buffers
 *       and CHDK draws only into the active one; their addresses are CHDK's
 *       own stubs for sx510hs 101a (bitmap_buffer[] at 0x413c), so the
 *       function refuses to run on any other platform build.
 *
 * Only RAM the camera already uses for the picture is written; nothing is
 * written to flash.
 */

#include "viewport.h"

#define MF_CHUNK (32 * 1024)

static int mf_u16(const unsigned char *p) { return p[0] | (p[1] << 8); }

static int luaCB_mf_viewport(lua_State *L)
{
    lua_pushnumber(L, (int)vid_get_viewport_active_buffer());
    lua_pushnumber(L, vid_get_viewport_width_proper());
    lua_pushnumber(L, vid_get_viewport_height_proper());
    lua_pushnumber(L, vid_get_viewport_byte_width());
    lua_pushnumber(L, vid_get_viewport_yscale());
    lua_pushnumber(L, vid_get_viewport_image_offset());
    lua_pushboolean(L, camera_info.state.mode_play);
    return 7;
}

static int mf_fail(lua_State *L, const char *msg)
{
    lua_pushnil(L);
    lua_pushstring(L, msg);
    return 2;
}

static int luaCB_mf_show(lua_State *L)
{
    const char *path = luaL_checkstring(L, 1);
    static char err[96];
    if (!camera_info.state.mode_play) return mf_fail(L, "not in playback mode");
    unsigned char *dst = vid_get_viewport_active_buffer();
    if (!dst) return mf_fail(L, "no image buffer");
    int w = vid_get_viewport_width_proper(), h = vid_get_viewport_height_proper();
    int bw = vid_get_viewport_byte_width();
    if (w <= 0 || h <= 0 || bw < w * 6 / 4 || bw > 4096) return mf_fail(L, "odd buffer geometry");

    int fd = open(path, O_RDONLY, 0777);
    if (fd < 0) return mf_fail(L, "cannot open file");
    unsigned char hd[12];
    if (read(fd, hd, 12) != 12 || hd[0] != 'M' || hd[1] != 'F' || hd[2] != 'V' || hd[3] != '1') {
        close(fd);
        return mf_fail(L, "not an MFV1 file");
    }
    if (mf_u16(hd + 4) != w || mf_u16(hd + 6) != h || mf_u16(hd + 8) != bw) {
        close(fd);
        sprintf(err, "file %dx%d/%d, screen %dx%d/%d", mf_u16(hd + 4), mf_u16(hd + 6), mf_u16(hd + 8), w, h, bw);
        return mf_fail(L, err);
    }
    unsigned char *buf = malloc(MF_CHUNK);
    if (!buf) { close(fd); return mf_fail(L, "out of memory"); }
    int t0 = get_tick_count();
    int total = h * bw, done = 0;
    while (done < total) {
        int n = total - done;
        if (n > MF_CHUNK) n = MF_CHUNK;
        int got = read(fd, buf, n);
        if (got <= 0) break;
        memcpy(dst + done, buf, got);
        done += got;
    }
    free(buf);
    close(fd);
    if (done != total) {
        sprintf(err, "short file: %d of %d bytes", done, total);
        return mf_fail(L, err);
    }
    lua_pushboolean(L, 1);
    lua_pushnumber(L, get_tick_count() - t0);
    return 2;
}

/* sx510hs 101a stubs_min.S: bitmap_buffer[] (two overlay buffers). Modules are
 * built platform independent, so the camera is checked at run time. */
#define MF_BITMAP_BUFFERS ((unsigned char **)0x413c)

static int luaCB_mf_overlay_clear(lua_State *L)
{
    if (strcmp(camera_info.platform, "sx510hs") != 0 || strcmp(camera_info.platformsub, "101a") != 0)
        return mf_fail(L, "not the SX510 HS 1.01A");
    int n = camera_screen.buffer_size;
    if (camera_screen.buffer_width != 960 || camera_screen.buffer_height != 270 || n != 960 * 270)
        return mf_fail(L, "unexpected bitmap size");
    unsigned char *b0 = MF_BITMAP_BUFFERS[0], *b1 = MF_BITMAP_BUFFERS[1];
    if (!b0 || !b1 || b0 == b1) return mf_fail(L, "bitmap buffers not found");
    memset(b0, COLOR_TRANSPARENT, n);
    memset(b1, COLOR_TRANSPARENT, n);
    lua_pushboolean(L, 1);
    return 1;
}
