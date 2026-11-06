# SPDX-License-Identifier: GPL-2.0-only
"""Crop of one frame (Web Darkroom). A crop is a rectangle in NORMALIZED coordinates of the upright,
lens-corrected frame (0..1, origin top-left): the same numbers mean the same framing in a 1280 px preview
and in the full-size render. It is applied right after the frame is normalized and before the optical
effects, the Camera Look and the film stage, so every radius, the scanner exposure and the grain scale
refer to the picture that is actually kept. The RAW is never altered; a crop is part of a rendition's
identity (render id), so a different crop is a different file next to the old one."""
from __future__ import annotations

import numpy as np

MIN_FRACTION = 0.02          # smaller than 2 % of a side is not a photograph
MIN_PIXELS = 16
FULL_EPS = 0.0005
ASPECTS = {"free": None, "original": "original", "1:1": 1.0, "5:4": 5 / 4, "4:5": 4 / 5, "4:3": 4 / 3, "3:4": 3 / 4,
           "3:2": 3 / 2, "2:3": 2 / 3, "16:9": 16 / 9, "9:16": 9 / 16, "65:24": 65 / 24}


class CropError(ValueError):
    pass


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
