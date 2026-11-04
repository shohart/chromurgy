# SPDX-License-Identifier: GPL-2.0-only
"""Developed frames for the camera's own viewer (app "Rolls on card" -> View).

The camera shows a frame by copying it into the playback image buffer
(viewport_fb_d), so a frame is stored ready to copy: an MFV file, a 12-byte
header and the buffer's own pixel format, UYVYYY (pre-DIGIC 6 CHDK cameras):
6 bytes per 4 pixels, U and V signed bytes shared by the 4, then Y0 Y1 Y2 Y3
(CHDK modules/histogram.c reads p[0], p[2] as signed char). The SX510 HS
playback buffer is 720x480 for a 4:3 screen, so pixels are 8/9 as wide as
tall; a 4:3 frame fills it, a portrait frame is pillarboxed.

On the card (outside A/CHDK/MFILM, which every sync downloads):
    A/CHDK/MFVIEW/INDEX.CFG           one line per roll the server developed
    A/CHDK/MFVIEW/<ROLL8>/F01.MFV ... the frames, in roll order
INDEX.CFG lines: roll=<roll uuid>|<film key>|<film short>|<YYYY-MM-DD>|<frames>|<ROLL8>|<sha8 of the set>
"""
from __future__ import annotations

import hashlib
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .store import Store, safe_id

MAGIC = b"MFV1"
WIDTH, HEIGHT = 720, 480
BYTE_WIDTH = WIDTH * 6 // 4
SCREEN_ASPECT = 4 / 3                      # the LCD; the buffer's pixels are not square
VIEW_DIR = "CHDK/MFVIEW"


def header() -> bytes:
    return MAGIC + struct.pack("<HHHH", WIDTH, HEIGHT, BYTE_WIDTH, 0)


def fit_to_screen(rgb: np.ndarray) -> np.ndarray:
    """HxWx3 uint8 photo -> 480x720x3 as it should look on the 4:3 screen (black bars)."""
    from PIL import Image
    h, w = rgb.shape[:2]
    px_aspect = (SCREEN_ASPECT * HEIGHT) / WIDTH           # displayed width / height of one buffer pixel
    img_aspect = w / h
    if img_aspect >= SCREEN_ASPECT:                         # wider: full width
        tw, th = WIDTH, round(WIDTH * px_aspect / img_aspect)
    else:                                                   # taller (portrait): full height
        tw, th = round(HEIGHT * img_aspect / px_aspect), HEIGHT
    tw -= tw % 4                                            # whole UYVYYY blocks
    small = np.asarray(Image.fromarray(rgb).resize((tw, th), Image.Resampling.LANCZOS))
    out = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    y0, x0 = (HEIGHT - th) // 2, ((WIDTH - tw) // 2) & ~3
    out[y0:y0 + th, x0:x0 + tw] = small
    return out


def pack_uyvyyy(rgb: np.ndarray) -> bytes:
    """480x720x3 uint8 -> UYVYYY rows (full-range BT.601, as JPEG)."""
    f = rgb.astype(np.float32)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    u = -0.168736 * r - 0.331264 * g + 0.5 * b
    v = 0.5 * r - 0.418688 * g - 0.081312 * b
    h, w = y.shape
    yq = np.clip(np.rint(y), 0, 255).astype(np.uint8).reshape(h, w // 4, 4)
    uq = np.clip(np.rint(u.reshape(h, w // 4, 4).mean(-1)), -128, 127).astype(np.int8).view(np.uint8)
    vq = np.clip(np.rint(v.reshape(h, w // 4, 4).mean(-1)), -128, 127).astype(np.int8).view(np.uint8)
    blk = np.empty((h, w // 4, 6), np.uint8)
    blk[..., 0], blk[..., 1], blk[..., 2] = uq, yq[..., 0], vq
    blk[..., 3], blk[..., 4], blk[..., 5] = yq[..., 1], yq[..., 2], yq[..., 3]
    return blk.tobytes()


def unpack_uyvyyy(data: bytes) -> np.ndarray:
    """Inverse of pack_uyvyyy (tests, previews): -> 480x720x3 uint8."""
    blk = np.frombuffer(data, np.uint8).reshape(HEIGHT, WIDTH // 4, 6)
    u = blk[..., 0].view(np.int8).astype(np.float32)[..., None]
    v = blk[..., 2].view(np.int8).astype(np.float32)[..., None]
    y = blk[..., [1, 3, 4, 5]].astype(np.float32)
    r = y + 1.402 * v
    g = y - 0.344136 * u - 0.714136 * v
    b = y + 1.772 * u
    return np.clip(np.rint(np.stack([r, g, b], -1)), 0, 255).astype(np.uint8).reshape(HEIGHT, WIDTH, 3)


def mfv_from_jpeg(path: Path) -> bytes:
    from PIL import Image
    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"))
    return header() + pack_uyvyyy(fit_to_screen(rgb))


@dataclass
class ViewRoll:
    roll_id: str
    film_key: str
    film_short: str
    day: str
    dir8: str
    frames: list[Path]                     # committed renders in roll order

    def set_hash(self) -> str:
        h = hashlib.sha256()
        for f in self.frames:
            h.update(f.name.encode())
        return h.hexdigest()[:8]

    def index_line(self) -> str:
        return (f"roll={self.roll_id}|{self.film_key}|{self.film_short}|{self.day}|{len(self.frames)}|"
                f"{self.dir8}|{self.set_hash()}")


def developed_rolls(conn: sqlite3.Connection, store: Store, device_id: str) -> list[ViewRoll]:
    """Rolls of this camera with a committed Linux render for every frame (the newest one per frame)."""
    from .publisher import _film_short
    out = []
    for roll in conn.execute("SELECT * FROM rolls WHERE device_id=? ORDER BY created_at", (device_id,)):
        rows = conn.execute(
            "SELECT f.ordinal, a.path, rc.json AS recipe_json, rc.bundle_hash FROM frames f "
            "JOIN renders r ON r.device_id=f.device_id AND r.frame_id=f.id "
            "JOIN assets a ON a.id=r.asset_id JOIN recipes rc ON rc.id=r.recipe_id "
            "WHERE f.device_id=? AND f.roll_id=? AND r.origin='linux' AND r.state IN ('COMMITTED','PUBLISHED') "
            "ORDER BY f.ordinal, r.rowid", (device_id, roll["id"])).fetchall()
        newest: dict[int, sqlite3.Row] = {}
        for r in rows:
            newest[r["ordinal"]] = r
        n = conn.execute("SELECT COUNT(*) FROM frames WHERE device_id=? AND roll_id=?",
                         (device_id, roll["id"])).fetchone()[0]
        if not newest or len(newest) != n:
            continue
        import json
        last = newest[max(newest)]
        film = json.loads(last["recipe_json"])["film_profile_id"]
        day = (roll["created_at"] or roll["sealed_at"] or roll["received_at"] or "")[:10] or "undated"
        out.append(ViewRoll(roll["id"], film, _film_short(store, last["bundle_hash"], film), day,
                            safe_id(roll["id"])[:8].upper(),
                            [store.root / newest[k]["path"] for k in sorted(newest)]))
    return out


def parse_index(text: str) -> dict[str, str]:
    """roll uuid -> set hash, from a camera's INDEX.CFG."""
    out = {}
    for ln in text.splitlines():
        if ln.startswith("roll="):
            p = ln[5:].split("|")
            if len(p) >= 7:
                out[p[0]] = p[6]
    return out
