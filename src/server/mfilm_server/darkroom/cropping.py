# SPDX-License-Identifier: GPL-2.0-only
"""Crop of one frame (Web Darkroom). A crop is a rectangle in NORMALIZED coordinates of the upright,
lens-corrected frame (0..1, origin top-left): the same numbers mean the same framing in a 1280 px preview
and in the full-size render. It is applied right after the frame is normalized and before the optical
effects, the Camera Look and the film stage, so every radius, the scanner exposure and the grain scale
refer to the picture that is actually kept. The RAW is never altered; a crop is part of a rendition's
identity (render id), so a different crop is a different file next to the old one."""
from __future__ import annotations

import math

import numpy as np

MIN_FRACTION = 0.02          # smaller than 2 % of a side is not a photograph
MIN_PIXELS = 16
FULL_EPS = 0.0005
ROT_EPS = 0.01
ASPECTS = {"free": None, "original": "original", "1:1": 1.0, "5:4": 5 / 4, "4:5": 4 / 5, "4:3": 4 / 3, "3:4": 3 / 4,
           "3:2": 3 / 2, "2:3": 2 / 3, "16:9": 16 / 9, "9:16": 9 / 16, "65:24": 65 / 24}


class CropError(ValueError):
    pass


def normalize_rotate(r) -> float | None:
    """Canonical clockwise rotation in degrees in (-180, 180], or None for 0 (no rotation). Raises CropError."""
    if r is None:
        return None
    if isinstance(r, bool) or not isinstance(r, (int, float)):
        raise CropError("rotate must be a number in degrees")
    v = float(r)
    if not np.isfinite(v) or not -360.0 <= v <= 360.0:
        raise CropError("rotate must be between -360 and 360 degrees")
    v = ((v + 180.0) % 360.0) - 180.0
    if abs(v + 180.0) < ROT_EPS:
        v = 180.0
    v = round(v, 2)
    if abs(v) < ROT_EPS:
        return None
    return int(v) if v.is_integer() else v


def apply_rotate(img: np.ndarray, rotate: float | None) -> np.ndarray:
    """Rotate HxWx3 float image clockwise by `rotate` degrees. Exact 90° steps use np.rot90; fine angles crop to the inscribed frame."""
    if not rotate:
        return img
    v = float(rotate)
    q = int(round(v / 90.0)) * 90
    rem = v - q
    k_cw = (q // 90) % 4
    if k_cw:
        img = np.ascontiguousarray(np.rot90(img, k=-k_cw))
    if abs(rem) >= ROT_EPS:
        from PIL import Image
        h, w = img.shape[:2]
        chans = [np.asarray(Image.fromarray(img[..., c], "F").rotate(-rem, resample=Image.BICUBIC, expand=False))
                 for c in range(img.shape[2])]
        rot = np.clip(np.stack(chans, -1), 0.0, 1.0)
        rad = abs(math.radians(rem))
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        s = min(w / (w * cos_a + h * sin_a), h / (w * sin_a + h * cos_a))
        cw = max(MIN_PIXELS, min(w, int(math.floor(w * s))))
        ch = max(MIN_PIXELS, min(h, int(math.floor(h * s))))
        x0 = (w - cw) // 2
        y0 = (h - ch) // 2
        img = rot[y0:y0 + ch, x0:x0 + cw]
    return np.ascontiguousarray(img)


def normalize_crop(c) -> dict | None:
    """Canonical crop dict {x, y, w, h} (4 decimals), or None for 'the whole frame'. Raises CropError."""
    if c is None:
        return None
    if not isinstance(c, dict) or set(c) - {"x", "y", "w", "h"} or not {"x", "y", "w", "h"} <= set(c):
        raise CropError("crop needs exactly x, y, w, h")
    try:
        x, y, w, h = (float(c[k]) for k in ("x", "y", "w", "h"))
    except (TypeError, ValueError):
        raise CropError("crop values must be numbers") from None
    if not all(np.isfinite(v) for v in (x, y, w, h)):
        raise CropError("crop values must be finite")
    if w < MIN_FRACTION or h < MIN_FRACTION:
        raise CropError(f"crop is smaller than {MIN_FRACTION:.0%} of the frame")
    if x < -FULL_EPS or y < -FULL_EPS or x + w > 1 + FULL_EPS or y + h > 1 + FULL_EPS:
        raise CropError("crop leaves the frame")
    x, y = max(x, 0.0), max(y, 0.0)
    w, h = min(w, 1 - x), min(h, 1 - y)
    if x < FULL_EPS and y < FULL_EPS and w > 1 - FULL_EPS and h > 1 - FULL_EPS:
        return None
    return {"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)}


def pixel_box(crop: dict, width: int, height: int) -> tuple[int, int, int, int]:
    """(x0, y0, x1, y1) in pixels: rounded outward from the same fractions at every resolution, at least MIN_PIXELS."""
    x0 = int(np.floor(crop["x"] * width + 1e-6))
    y0 = int(np.floor(crop["y"] * height + 1e-6))
    x1 = int(np.ceil((crop["x"] + crop["w"]) * width - 1e-6))
    y1 = int(np.ceil((crop["y"] + crop["h"]) * height - 1e-6))
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
    if x1 - x0 < MIN_PIXELS or y1 - y0 < MIN_PIXELS:
        raise CropError(f"crop is {x1 - x0}x{y1 - y0} px: too small")
    return x0, y0, x1, y1


def apply_crop(img: np.ndarray, crop: dict | None) -> np.ndarray:
    """HxWx3 float image -> its crop (a copy, contiguous). No crop = the same array."""
    if not crop:
        return img
    h, w = img.shape[:2]
    x0, y0, x1, y1 = pixel_box(crop, w, h)
    return np.ascontiguousarray(img[y0:y1, x0:x1])
