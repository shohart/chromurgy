# SPDX-License-Identifier: GPL-2.0-only
"""Lens geometry for CHDK DNGs (docs/05 input normalization).

A CHDK DNG holds the sensor's visible area as read out: at the wide end of
the SX510 HS zoom that is a strongly barrel-distorted image whose corners
fall outside the lens's image circle. The camera corrects this itself for
its JPEGs; the DNG carries no opcode lists, so LibRaw does not. The lens
table (profiles/lenses/*.json, fitted by tools/fit_lens.py from DNG + camera
JPEG pairs) gives, per calibrated focal length, where each output pixel
comes from in the raw. Between calibrated focal lengths the two neighbouring
mappings are interpolated linearly in focal length; outside the range the
nearest one is used.

Output is the camera JPEG's framing (4000x3000 on the SX510 HS), so a film
render and the camera's own JPEG show the same picture.
"""
from __future__ import annotations

import hashlib
import json
from functools import cache
from pathlib import Path

import numpy as np

LENS_DIR = Path(__file__).resolve().parents[3] / "profiles" / "lenses"
EXIF, FOCAL, DTORIG = 0x8769, 37386, 36867
SOFTWARE, MODEL, DATETIME, UNIQUE_MODEL = 305, 272, 306, 50708


def dng_info(path: Path) -> dict:
    """Software, camera model, focal length and capture time from a DNG's TIFF/EXIF tags ({} if unreadable)."""
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(path) as im:
            tags = im.getexif()
            sub = tags.get_ifd(EXIF)
    except (UnidentifiedImageError, OSError, ValueError):
        return {}
    try:
        focal = float(sub.get(FOCAL) or 0) or None
    except (TypeError, ValueError):
        focal = None
    model = tags.get(UNIQUE_MODEL) or tags.get(MODEL)
    return {"software": str(tags.get(SOFTWARE) or ""), "model": str(model).strip("\0 ") if model else None,
            "focal_mm": focal, "time": sub.get(DTORIG) or tags.get(DATETIME)}


def radial_map(j: np.ndarray, size: tuple[int, int], cx: float, cy: float, s: float,
               k1: float, k2: float, k3: float) -> np.ndarray:
    """Output (JPEG-frame) coordinates -> raw coordinates; both with pixel centres at i + 0.5."""
    j0 = np.array([size[0] / 2, size[1] / 2])
    d = j - j0
    r2 = (d ** 2).sum(-1) / (j0 ** 2).sum()
    f = s * (1 + r2 * (k1 + r2 * (k2 + r2 * k3)))
    return np.array([cx, cy]) + d * f[..., None]


@cache
def _tables() -> dict[str, dict]:
    out = {}
    for p in sorted(LENS_DIR.glob("*.json")) if LENS_DIR.is_dir() else []:
        t = json.loads(p.read_text())
        t["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
        t["file"] = p.name
        t["focal_lengths"] = sorted(t["focal_lengths"], key=lambda e: e["focal_mm"])
        out[t["camera_model"]] = t
    return out


def table_for(info: dict) -> dict | None:
    """The lens table for a CHDK DNG of a calibrated camera, else None (geometry left as decoded)."""
    if not info.get("software", "").startswith("CHDK"):
        return None
    return _tables().get(info.get("model") or "")


def _params(e: dict) -> tuple[float, ...]:
    return e["cx"], e["cy"], e["s"], e["k1"], e["k2"], e["k3"]


def source_coords(table: dict, focal_mm: float, xy: np.ndarray) -> np.ndarray:
    size = (table["output_width"], table["output_height"])
    fls = table["focal_lengths"]
    if focal_mm <= fls[0]["focal_mm"]:
        return radial_map(xy, size, *_params(fls[0]))
    if focal_mm >= fls[-1]["focal_mm"]:
        return radial_map(xy, size, *_params(fls[-1]))
    i = next(i for i in range(1, len(fls)) if fls[i]["focal_mm"] >= focal_mm)
    a, b = fls[i - 1], fls[i]
    t = (focal_mm - a["focal_mm"]) / (b["focal_mm"] - a["focal_mm"])
    return (1 - t) * radial_map(xy, size, *_params(a)) + t * radial_map(xy, size, *_params(b))


def correct(img: np.ndarray, table: dict, focal_mm: float, strip: int = 256) -> np.ndarray:
    """Resample a decoded linear image (LibRaw visible area, HxWx3 float32) into the camera's
    JPEG frame, bilinear. Pixels mapped outside the raw are clamped to its edge."""
    w, h = table["output_width"], table["output_height"]
    H, W = img.shape[:2]
    out = np.empty((h, w, img.shape[2]), np.float32)
    xs = np.arange(w, dtype=np.float64) + 0.5
    for y0 in range(0, h, strip):
        ys = np.arange(y0, min(y0 + strip, h), dtype=np.float64) + 0.5
        gx, gy = np.meshgrid(xs, ys)
        src = source_coords(table, focal_mm, np.stack([gx, gy], -1))
        sx = np.clip(src[..., 0] - 0.5, 0, W - 1)
        sy = np.clip(src[..., 1] - 0.5, 0, H - 1)
        x0 = np.minimum(sx.astype(np.int64), W - 2)
        y0i = np.minimum(sy.astype(np.int64), H - 2)
        fx = (sx - x0).astype(np.float32)[..., None]
        fy = (sy - y0i).astype(np.float32)[..., None]
        top = img[y0i, x0] * (1 - fx) + img[y0i, x0 + 1] * fx
        bot = img[y0i + 1, x0] * (1 - fx) + img[y0i + 1, x0 + 1] * fx
        out[y0:y0 + len(ys)] = top * (1 - fy) + bot * fy
    return out
