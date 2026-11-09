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

from .imgops import LUMA, blur, luma, smoothstep  # noqa: F401  (re-exported: other modules/tests use creative.blur etc.)
from .creative_params import EFFECTS as EFFECT_DEFAULTS
from .creative_params import LOOKS as LOOK_PARAMS

VERSION = "mfilm-creative-1"             # recipes that use none of the NEW_EFFECTS keep this identity
VERSION_OPTICS = "mfilm-creative-2"      # recipes with a v0.6 operator (see optics.IMPLEMENTATION_VERSION)
LEGACY_ORDER = ["vintage_veiling_flare", "soft_sun_glow", "ricoh_hdf_diffusion", "black_pro_mist_like",
                "orton_glow", "film_halation_extra"]
# Canonical execution order (docs/optical-engine/integration.md): geometry -> channel warp -> softening/focus ->
# source-driven light optics -> the six original diffusion/glow effects (their relative order is unchanged, so
# archived recipes render exactly as before) -> light leaks -> exposure vignette.
EFFECT_ORDER = ["vintage_glass_barrel_distortion", "vintage_glass_chromatic_aberration", "vintage_glass_edge_softness",
                "lensbaby_sweet_spot", "tilt_shift_miniature",
                "lens_flare_ghosting", "starburst_cross_screen", "anamorphic_streak",
                *LEGACY_ORDER, "analog_light_leaks", "optical_vignetting"]
NEW_EFFECTS = [e for e in EFFECT_ORDER if e not in LEGACY_ORDER]
# composite optical presets: the stack they expand to (per-effect parameter overrides; strength scales them)
PRESETS = {"golden_haze": [("soft_sun_glow", {"warm_shift": 0.18, "veil": 0.12}),
                           ("black_pro_mist_like", {"veil": 0.03})],
           # compound preset: expands to its three real operators plus the exposure vignette, all editable (algorithms.md H4)
           "vintage_glass": [("vintage_glass_barrel_distortion", {}), ("vintage_glass_chromatic_aberration", {}),
                             ("vintage_glass_edge_softness", {}), ("optical_vignetting", {})]}
# every parameter a recipe may set, with its allowed range
PARAM_RANGE = {"threshold": (0.0, 4.0), "knee": (0.01, 2.0), "radius_fraction": (0.0005, 0.2), "broad_radius_fraction": (0.001, 0.4),
               "warm_shift": (-0.5, 0.5), "veil": (0.0, 0.6), "red_gain": (0.0, 1.0), "mix": (0.0, 1.0)}


# ---- optical effects --------------------------------------------------------------------------------
def _soft_mask(lum: np.ndarray, thr: float, knee: float) -> np.ndarray:
    return smoothstep(lum, thr - knee, thr + knee)       # smooth knee, no hard threshold


class Ctx:
    """Per-render context of the optical stage: seed/salt of the stochastic operators and the per-effect source
    selection; `sources` collects what each source-driven effect actually acted on (for no-source reporting)."""

    def __init__(self, seed: int = 0, salt: str = "", items: dict | None = None):
        self.seed, self.salt, self.items = int(seed), str(salt), items or {}
        self.sources: dict[str, list[dict]] = {}

    def selection(self, eid: str) -> dict | None:
        return (self.items.get(eid) or {}).get("source_selection")

    def note(self, eid: str, srcs: list[dict]) -> None:
        self.sources[eid] = srcs


def apply_effect(x: np.ndarray, eid: str, p: dict, k: float, diag: float, ctx: Ctx | None = None) -> np.ndarray:
    """One effect at strength k (0..1), on scene-linear RGB. k == 0 returns the input unchanged."""
    if k <= 0:
        return x
    if eid in NEW_EFFECTS:
        from . import optics
        return optics.OPERATORS[eid](x, p, k, ctx or Ctx())
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


def apply_optics(x: np.ndarray, stack: list[dict], strength: float, ctx: Ctx | None = None) -> np.ndarray:
    """stack: normalized items [{id, enabled, parameters}] (all parameters present). Legal order is the
    engine's (EFFECT_ORDER), never the order the client listed them in."""
    h, w = x.shape[:2]
    diag = float(np.hypot(h, w))
    by = {s["id"]: s for s in stack if s["enabled"]}
    ctx = ctx or Ctx(items=by)
    ctx.items = by
    for eid in EFFECT_ORDER:
        if eid in by:
            x = apply_effect(x, eid, by[eid]["parameters"], strength, diag, ctx)
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


def apply_creative(lin: np.ndarray, creative: dict | None, salt: str = "", report: dict | None = None) -> np.ndarray:
    """The whole pre-film creative stage for one v1-bridge `creative` block; no block = identity."""
    if not creative:
        return lin
    x = np.asarray(lin, dtype=np.float32)
    opt = creative.get("optical")
    if opt and opt["strength"] > 0 and opt["stack"]:
        ctx = Ctx(creative.get("seed", 0), salt)
        x = apply_optics(x, opt["stack"], opt["strength"], ctx)
        if report is not None:       # what the source-driven effects acted on: "no light source detected" must be visible
            from .optics import source_id
            for eid, srcs in ctx.sources.items():
                report[eid] = [{"id": source_id(s), "x": round(s["x"], 4), "y": round(s["y"], 4),
                                "confidence": round(s["confidence"], 3), "manual": bool(s.get("manual"))} for s in srcs]
    look = creative.get("camera_look")
    if look and look["strength"] > 0 and look["id"] != "neutral":
        x = apply_look(x, look["id"], look["strength"])
    return np.ascontiguousarray(x, dtype=np.float32)
