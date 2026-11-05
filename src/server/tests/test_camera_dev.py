# SPDX-License-Identifier: GPL-2.0-only
"""The camera's own developer (src/camera/dev) on the host, with the data files
the camera gets (MFCAM.BIN from camera_dev.py, MFDEV.BIN from mfdev_gen), on a
synthetic DNG laid out like CHDK's (12-bit packed, one strip, ActiveArea)."""
import struct
import subprocess

import numpy as np
import pytest
from PIL import Image

from mfilm_server import core
from mfilm_server.camera_dev import REPO, camera_blob, films_blob
from mfilm_server.camera_view import HEIGHT, WIDTH, unpack_uyvyyy

HOST = REPO / "build" / "src" / "shared" / "film_core" / "mfdev_host"
pytestmark = pytest.mark.skipif(not HOST.is_file(), reason="cmake --build build --target mfdev_gen mfdev_host")

RAW_W, RAW_H, TOP, LEFT, VIS_W, VIS_H = 4168, 3062, 18, 96, 4072, 3044


def chdk_like_dng(path, orientation=1, focal=(43, 10)):
    """Grey card lit from the left: a horizontal ramp, RGGB, black 127, white 4095."""
    x = np.arange(RAW_W)
    ramp = (127 + 300 + 2500 * x / RAW_W).astype(np.uint16)
    raw = np.tile(ramp, (RAW_H, 1))
    raw[0::2, 0::2] = (raw[0::2, 0::2] - 127) / 1.5452 + 127      # R and B so that daylight WB makes it grey
    raw[1::2, 1::2] = (raw[1::2, 1::2] - 127) / 1.7791 + 127
    a, b = raw[:, 0::2].astype(np.uint32), raw[:, 1::2].astype(np.uint32)
    packed = np.stack([a >> 4, ((a & 15) << 4) | (b >> 8), b & 255], -1).astype(np.uint8).tobytes()

    entries0, entries_raw, entries_exif, blobs = [], [], [], []
    data_off = 8

    def ent(lst, tag, typ, count, value):
        lst.append((tag, typ, count, value))

    # layout: header, IFD0, raw IFD, EXIF IFD, value blobs, strip
    ifd0_n, raw_n, exif_n = 6, 13, 2
    ifd0_off = data_off
    raw_off = ifd0_off + 2 + 12 * ifd0_n + 4
    exif_off = raw_off + 2 + 12 * raw_n + 4
    blob_off = exif_off + 2 + 12 * exif_n + 4
    model = b"Canon PowerShot SX510 HS\0"
    cur = blob_off

    def blob(data):
        nonlocal cur
        off = cur
        blobs.append(data)
        cur += len(data) + (len(data) & 1)
        if len(data) & 1:
            blobs.append(b"\0")
        return off

    model_off = blob(model)
    act_off = blob(struct.pack("<4I", TOP, LEFT, TOP + VIS_H, LEFT + VIS_W))
    focal_off = blob(struct.pack("<2I", *focal))
    strip_off = (cur + 4095) // 4096 * 4096
    ent(entries0, 254, 4, 1, 0)
    ent(entries0, 274, 3, 1, orientation)
    ent(entries0, 330, 4, 1, raw_off)
    ent(entries0, 34665, 4, 1, exif_off)
    ent(entries0, 50706, 1, 4, int.from_bytes(bytes([1, 3, 0, 0]), "little"))
    ent(entries0, 50708, 2, len(model), model_off)
    ent(entries_raw, 254, 4, 1, 0)
    ent(entries_raw, 256, 4, 1, RAW_W)
    ent(entries_raw, 257, 4, 1, RAW_H)
    ent(entries_raw, 258, 3, 1, 12)
    ent(entries_raw, 259, 3, 1, 1)
    ent(entries_raw, 262, 3, 1, 32803)
    ent(entries_raw, 273, 4, 1, strip_off)
    ent(entries_raw, 279, 4, 1, len(packed))
    ent(entries_raw, 33421, 3, 2, 2 | 2 << 16)
    ent(entries_raw, 33422, 1, 4, int.from_bytes(bytes([0, 1, 1, 2]), "little"))
    ent(entries_raw, 50714, 4, 1, 127)
    ent(entries_raw, 50717, 4, 1, 4095)
    ent(entries_raw, 50829, 4, 4, act_off)
    ent(entries_exif, 37386, 5, 1, focal_off)
    ent(entries_exif, 36867, 2, 4, int.from_bytes(b"x\0\0\0", "little"))

    def ifd(lst):
        lst = sorted(lst)
        out = struct.pack("<H", len(lst))
        for tag, typ, count, value in lst:
            out += struct.pack("<HHII", tag, typ, count, value)
        return out + struct.pack("<I", 0)

    head = b"II*\0" + struct.pack("<I", ifd0_off) + ifd(entries0) + ifd(entries_raw) + ifd(entries_exif)
    assert len(head) == blob_off
    body = head + b"".join(blobs)
    path.write_bytes(body + bytes(strip_off - len(body)) + packed)


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("mfdev")
    (d / "MFCAM.BIN").write_bytes(camera_blob())
    films_blob(core.Bundle().path, d / "MFDEV.BIN")
    return d


def develop(files, dng, film="portra400"):
    jpg, mfv = dng.with_suffix(".jpg"), dng.with_suffix(".mfv")
    p = subprocess.run([str(HOST), str(files / "MFCAM.BIN"), str(files / "MFDEV.BIN"), film, "0123456789abcdef",
                        str(dng), str(jpg), str(mfv)], capture_output=True, text=True, check=False)
    kv = dict(x.split("=", 1) for x in p.stdout.split())
    return p.returncode, kv, jpg, mfv


def test_every_film_is_baked(files):
    head = (files / "MFDEV.BIN").read_bytes()[:24]
    magic, n, w, h, block = head[:8], *struct.unpack("<4I", head[8:24])
    assert magic == b"MFDEV001" and (w, h) == (1024, 768) and n == 72 and block > 200_000
    assert len((files / "MFDEV.BIN").read_bytes()) == 24 + 32 * n + n * block


def test_landscape_frame(files, tmp_path):
    dng = tmp_path / "CRW_0001.DNG"
    chdk_like_dng(dng)
    rc, kv, jpg, mfv = develop(files, dng)
    assert rc == 0 and kv["rc"] == "0" and kv["progress"] == "1000", kv
    assert kv["sha256"] == __import__("hashlib").sha256(dng.read_bytes()).hexdigest()
    assert int(kv["focal_q8"]) == round(4.3 * 256)
    im = np.asarray(Image.open(jpg).convert("RGB")).astype(float)
    assert im.shape == (768, 1024, 3)
    mid = im[300:460, 200:820]
    assert abs(mid[..., 0].mean() - mid[..., 2].mean()) < 25         # daylight WB: a grey card stays near grey
    cols = mid.mean(axis=(0, 2))
    assert cols[-1] > cols[0] + 20                                     # the ramp survives, left to right
    view = unpack_uyvyyy(mfv.read_bytes()[12:])
    assert mfv.read_bytes()[:4] == b"MFV1" and view.shape == (HEIGHT, WIDTH, 3)
    assert view[:, :40].mean() < view[:, -40:].mean()


@pytest.mark.parametrize("orientation", [6, 8])
def test_portrait_frames_are_upright_and_pillarboxed(files, tmp_path, orientation):
    dng = tmp_path / f"CRW_{orientation}.DNG"
    chdk_like_dng(dng, orientation=orientation, focal=(19054, 1000))
    rc, kv, _, mfv = develop(files, dng)
    assert rc == 0, kv
    view = unpack_uyvyyy(mfv.read_bytes()[12:]).astype(float)
    assert view[:, :150].max() < 12 and view[:, -150:].max() < 12      # black pillars
    rows = view[20:460, 200:520].mean(axis=(1, 2))
    # turned counter-clockwise (8, LibRaw flip 5) the sensor's bright right edge is at the top;
    # clockwise (6) at the bottom (checked against the server's upright renders of real frames)
    assert (rows[0] > rows[-1] + 15) if orientation == 8 else (rows[-1] > rows[0] + 15)


def test_unknown_film_is_refused(files, tmp_path):
    dng = tmp_path / "CRW_0002.DNG"
    chdk_like_dng(dng)
    rc, kv, _, _ = develop(files, dng, film="no-such-film")
    assert rc != 0 and kv["rc"] == "-23"
