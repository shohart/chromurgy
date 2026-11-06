# SPDX-License-Identifier: GPL-2.0-only
"""The final look stage of a Web Darkroom render, shared by the preview and the full-size render so the two
cannot diverge: film (or none), development strength, brightness, contrast and the sepia / black-and-white filters.

Order: scene-linear frame (after crop, white balance, optics, Camera Look) -> film stage of the shared C core
with the brightness exposure compensation (or, with film `none`, a plain exposure + sRGB encoding) ->
blend with the un-filmed render by the development strength -> contrast curve -> tone filter.
Brightness is exposure compensation in stops (the film engine's own exposure control)."""
from __future__ import annotations

import numpy as np
from PIL import Image

FILTERS = ("none", "grayscale", "sepia", "silver")
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def srgb_encode(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055).astype(np.float32)


def srgb_decode(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, np.power((x + 0.055) / 1.055, 2.4)).astype(np.float32)


def contrast_curve(x: np.ndarray, c: float) -> np.ndarray:
    """Monotonic S-curve in display space: c>0 steeper mid-tones (smoothstep blend, no clipping), c<0 flatter."""
    if not c:
        return x
    s = x * x * (3 - 2 * x)
    return np.clip(x + c * (s - x), 0.0, 1.0)


SILVER_MIX = np.array([0.38, 0.52, 0.10], np.float32)   # panchromatic-style response, mixed in display space like a darkroom channel mixer
GRAIN_REF_W = 1200                                        # the grain lives on a grid this wide, whatever the picture size


def silver_grain(h: int, w: int, seed: int) -> np.ndarray:
    """Unit-variance monochrome grain field: deterministic from the seed and defined as a fraction of the picture width,
    so a preview and the full-size render show the same grain structure (grain-tail frequency follows the width)."""
    rw, rh = GRAIN_REF_W, max(8, round(GRAIN_REF_W * h / w))
    g = np.random.default_rng(seed & 0xFFFFFFFFFFFFFFFF).standard_normal((rh, rw)).astype(np.float32)
    g = np.asarray(Image.fromarray(g, "F").resize((w, h), Image.BICUBIC), np.float32)
    return g / max(float(g.std()), 1e-6)


def silver_film(img: np.ndarray, seed: int) -> np.ndarray:
    """Black-and-white silver-halide look: panchromatic grey, a film-like S-curve with a little base fog and a
    rolled-off shoulder, and luminance-weighted silver grain (strongest in the mid-tones, quiet in deep shadows and highlights)."""
    v = np.clip(img @ SILVER_MIX, 0.0, 1.0)
    v = contrast_curve(v, 0.40) * 0.965 + 0.018                        # toe lifted by base fog, shoulder never reaches pure paper white
    amp = 0.008 + 0.034 * 4.0 * v * (1.0 - v)
    v = np.clip(v + amp * silver_grain(*v.shape, seed), 0.0, 1.0)
    return np.repeat(v[..., None], 3, -1)


def tone_filter(img: np.ndarray, name: str, strength: float, seed: int = 0) -> np.ndarray:
    if name == "none" or strength <= 0:
        return img
    lum = srgb_encode(srgb_decode(img) @ LUMA)                    # luminance measured in linear light, shown in sRGB
    if name == "grayscale":
        out = np.repeat(lum[..., None], 3, -1)
    elif name == "silver":
        out = silver_film(img, seed)
    elif name == "sepia":
        v = np.clip(lum, 0, 1)[..., None]
        out = np.concatenate([v ** 0.90 * 1.00, v ** 1.02 * 0.93, v ** 1.30 * 0.78], -1)     # cream highlights, brown shadows
    else:
        raise ValueError(f"unknown filter {name}")
    return img + strength * (out - img)


def render_display(lin: np.ndarray, v1: dict, bundle, seed: int) -> tuple[np.ndarray, float | None]:
    """lin: scene-linear sRGB HxWx3 float32. Returns display sRGB 0..1 and the film's scanner EV (None without film)."""
    ev = float(v1.get("exposure_compensation_ev", 0.0))
    tone = v1.get("tone") or {}
    key = v1["film_profile_id"]
    scanner = None
    if key == "none":
        img = srgb_encode(lin * (2.0 ** ev))
    else:
        look = v1["look_controls"]
        img, scanner = bundle.develop(key, lin, seed=seed, grain_scale=look["grain_scale"], halation_scale=look["halation_scale"],
                                      softness_scale=look["softness_scale"], exposure_ev=ev)
        s = float(tone.get("develop_strength", 1.0))
        if s < 1.0:
            neutral = srgb_encode(lin * (2.0 ** ev))
            img = neutral + s * (img - neutral)                       # 0 = developed with no film, 1 = the full film look
    img = contrast_curve(img, float(tone.get("contrast", 0.0)))
    img = tone_filter(img, tone.get("filter", "none"), float(tone.get("filter_strength", 1.0)), seed)
    return np.ascontiguousarray(np.clip(img, 0, 1), dtype=np.float32), scanner
