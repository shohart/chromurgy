# SPDX-License-Identifier: GPL-2.0-only
"""Small numpy image helpers shared by the creative stage and the optical operators (moved verbatim from
creative.py; numerics unchanged so archived renders stay reproducible)."""
from __future__ import annotations

import numpy as np
from PIL import Image

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def luma(x: np.ndarray) -> np.ndarray:
    return x @ LUMA


def smoothstep(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    t = np.clip((x - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ---- blur -------------------------------------------------------------------------------------------
def _box(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """Box blur of radius r along axis, edges replicated (cumulative-sum form: O(n) per radius)."""
    if r < 1:
        return a
    n = a.shape[axis]
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    hi = np.take(c, range(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, range(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(np.float32)


def _gauss_small(a: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian approximated by three box blurs per axis ('boxes for gauss')."""
    if sigma < 0.5:
        return a
    n = 3
    w = np.sqrt(12 * sigma * sigma / n + 1)
    wl = int(np.floor(w))
    wl -= (wl % 2 == 0)
    wu = wl + 2
    m = round((12 * sigma * sigma - n * wl * wl - 4 * n * wl - 3 * n) / (-4 * wl - 4))
    out = a
    for i in range(n):
        r = ((wl if i < m else wu) - 1) // 2
        out = _box(_box(out, r, 0), r, 1)
    return out


def blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur of an HxWxC float image. Large sigmas run on a reduced copy (far-field glow needs no
    full-resolution kernel); the factor is a pure function of sigma, so results are reproducible."""
    if sigma < 0.5:
        return a
    f = 1
    while sigma / f > 6 and f < 64:
        f *= 2
    if f == 1:
        return _gauss_small(a, sigma)
    h, w = a.shape[:2]
    sw, sh = max(1, w // f), max(1, h // f)
    small = np.stack([np.asarray(Image.fromarray(a[..., c], "F").resize((sw, sh), Image.BOX)) for c in range(a.shape[2])], -1)
    small = _gauss_small(small, sigma / f)
    return np.stack([np.asarray(Image.fromarray(small[..., c], "F").resize((w, h), Image.BICUBIC)) for c in range(a.shape[2])], -1)
