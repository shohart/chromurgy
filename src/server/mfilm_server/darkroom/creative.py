# SPDX-License-Identifier: GPL-2.0-only
"""Creative render stages of the Web Darkroom (docs/web/20, 21): optical effects and Camera Looks.

Pipeline position (docs/web/20): normalized scene-linear RGB -> optical effects (pre-tone, scene-linear,
fixed legal order) -> Camera Look (linear-domain tone/colour, blended by strength) -> M-Film film stock
(shared C core) -> output. All radii are fractions of the image diagonal, so a preview and a full-size
render of one recipe look the same. Everything is deterministic (no RNG).

HONEST LIMITS: these are original artistic approximations driven by provisional starter parameters,
NOT measured recreations of the cameras or filters they are named after. They are implemented in numpy,
not in the shared C core, so they run on the Linux server only (the camera never renders them);
`VERSION` is part of every creative render's identity."""
from __future__ import annotations

import numpy as np
from PIL import Image

from .creative_params import EFFECTS as EFFECT_DEFAULTS
from .creative_params import LOOKS as LOOK_PARAMS

VERSION = "mfilm-creative-1"
EFFECT_ORDER = ["vintage_veiling_flare", "soft_sun_glow", "ricoh_hdf_diffusion", "black_pro_mist_like",
                "orton_glow", "film_halation_extra"]
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)
# composite optical presets: the stack they expand to (per-effect parameter overrides; strength scales them)
PRESETS = {"golden_haze": [("soft_sun_glow", {"warm_shift": 0.18, "veil": 0.12}),
                           ("black_pro_mist_like", {"veil": 0.03})]}
# every parameter a recipe may set, with its allowed range
PARAM_RANGE = {"threshold": (0.0, 4.0), "knee": (0.01, 2.0), "radius_fraction": (0.0005, 0.2), "broad_radius_fraction": (0.001, 0.4),
               "warm_shift": (-0.5, 0.5), "veil": (0.0, 0.6), "red_gain": (0.0, 1.0), "mix": (0.0, 1.0)}


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


# ---- optical effects --------------------------------------------------------------------------------
def _soft_mask(lum: np.ndarray, thr: float, knee: float) -> np.ndarray:
    return smoothstep(lum, thr - knee, thr + knee)       # smooth knee, no hard threshold


def apply_effect(x: np.ndarray, eid: str, p: dict, k: float, diag: float) -> np.ndarray:
    """One effect at strength k (0..1), on scene-linear RGB. k == 0 returns the input unchanged."""
    if k <= 0:
        return x
    lum = luma(x)
    m = _soft_mask(lum, p.get("threshold", 1.0), p.get("knee", 0.3))
    hi = x * m[..., None]                                  # bright branch keeps its colour
    r = p.get("radius_fraction", 0.01) * diag
    if eid == "soft_sun_glow":
        glow = blur(hi, r) + 0.5 * blur(hi, 3 * r)       # multi-scale bloom
        warm = np.array([1 + p.get("warm_shift", 0.1), 1.0, 1 - p.get("warm_shift", 0.1)], np.float32)
        out = x + k * glow * warm
        out = out + k * p.get("veil", 0.08) * blur(x, 8 * r) * warm      # warm low-frequency lift
        return out
    if eid == "ricoh_hdf_diffusion":
        near, far = blur(hi, r), blur(hi, p.get("broad_radius_fraction", 0.025) * diag)
        veil = p.get("veil", 0.08)
        soft = 0.5 * near + 0.5 * far
        return np.maximum(x * (1 - 0.5 * veil * k) + k * (soft * 0.8 + veil * blur(x, p.get("broad_radius_fraction", 0.025) * diag)), 0.0)
    if eid == "black_pro_mist_like":
        glow = blur(hi, r)
        veil = p.get("veil", 0.06)
        out = x + k * glow * 0.9
        gray = luma(out)[..., None]
        cf = np.maximum(1 - 0.25 * k * m[..., None], 0.0)
        return np.maximum(out * cf + (1 - cf) * gray + k * veil * blur(x, 2 * r), 0.0)   # highlight desaturation + black lift
    if eid == "vintage_veiling_flare":
        veil = p.get("veil", 0.18)
        scatter = blur(x, r) * np.array([1.0, 0.97, 0.88], np.float32)    # warm, wide, scene-weighted scatter
        wbright = blur(hi, 2 * r)
        return np.maximum(x * (1 - veil * k * 0.5) + k * veil * (0.6 * scatter + 0.8 * wbright), 0.0)
    if eid == "film_halation_extra":
        edge = np.maximum(blur(m[..., None] * lum[..., None], r) - m[..., None] * lum[..., None] * 0.6, 0)  # rim outside the highlight
        g = p.get("red_gain", 0.2)
        return x + k * edge * np.array([g * 3, g * 0.9, 0.0], np.float32)
    if eid == "orton_glow":
        wgt = smoothstep(lum, p.get("threshold", 0.5) - p.get("knee", 0.4), p.get("threshold", 0.5) + p.get("knee", 0.4))[..., None]
        soft = blur(x * 1.35, r)                          # exposure-raised, blurred branch
        mix = p.get("mix", 0.28) * k
        return x + (soft - x) * mix * (0.35 + 0.65 * wgt)                     # mid-tones keep texture, highlights glow
    raise ValueError(f"unknown effect {eid}")


def apply_optics(x: np.ndarray, stack: list[dict], strength: float) -> np.ndarray:
    """stack: normalized items [{id, enabled, parameters}] (all parameters present). Legal order is the
    engine's (EFFECT_ORDER), never the order the client listed them in."""
    h, w = x.shape[:2]
    diag = float(np.hypot(h, w))
    by = {s["id"]: s for s in stack if s["enabled"]}
    for eid in EFFECT_ORDER:
        if eid in by:
            x = apply_effect(x, eid, by[eid]["parameters"], strength, diag)
    return x


# ---- camera looks -----------------------------------------------------------------------------------
def apply_look(x: np.ndarray, look_id: str, strength: float) -> np.ndarray:
    """Camera Look on scene-linear RGB (pivot 0.18), blended with the input by `strength` in linear light."""
    p = LOOK_PARAMS[look_id]
    if strength <= 0 or look_id == "neutral":
        return x
    h, w = x.shape[:2]
    y = np.maximum(luma(x), 1e-6)
    y1 = 0.18 * np.power(y / 0.18, p["contrast_gain"])                     # contrast about middle grey
    y2 = y1 * (1 - p["toe_strength"] * np.exp(-y1 / 0.02))                  # toe: denser blacks
    s = p["highlight_shoulder"]
    y3 = y2 / (1 + s * np.maximum(y2 - 0.6, 0))                             # shoulder: soft highlight roll-off
    if p["microcontrast_amount"]:
        detail = y3 - blur(y3[..., None], 0.002 * float(np.hypot(h, w)))[..., 0]
        y3 = np.maximum(y3 + p["microcontrast_amount"] * detail, 1e-6)
    out = x * (y3 / y)[..., None]                                           # luminance change, chromaticity kept
    yy = y3[..., None]
    out = yy + p["global_chroma_gain"] * (out - yy)                          # chroma about luma
    k = p["shadow_warm_cool"] * (1 - smoothstep(y3, 0.0, 0.3)) + p["highlight_warm_cool"] * smoothstep(y3, 0.4, 1.0)
    out = out * np.stack([1 + 2.5 * k, np.ones_like(k), 1 - 2.5 * k], -1)    # warm / cool split
    gb = p["green_hue_bias"]
    if gb:
        g = out[..., 1]
        gw = np.clip((g - np.maximum(out[..., 0], out[..., 2])) / np.maximum(g, 1e-6), 0, 1) * 2.0
        d = gb * 2.5 * gw * g
        out = out.copy()
        if gb > 0:
            out[..., 0] += d                                                 # greens toward yellow
        else:
            out[..., 2] -= d                                                 # greens toward cyan
    out = np.maximum(out, 0)
    return np.maximum(x + strength * (out - x), 0.0)


def apply_creative(lin: np.ndarray, creative: dict | None) -> np.ndarray:
    """The whole pre-film creative stage for one v1-bridge `creative` block; no block = identity."""
    if not creative:
        return lin
    x = np.asarray(lin, dtype=np.float32)
    opt = creative.get("optical")
    if opt and opt["strength"] > 0 and opt["stack"]:
        x = apply_optics(x, opt["stack"], opt["strength"])
    look = creative.get("camera_look")
    if look and look["strength"] > 0 and look["id"] != "neutral":
        x = apply_look(x, look["id"], look["strength"])
    return np.ascontiguousarray(x, dtype=np.float32)
