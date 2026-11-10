# SPDX-License-Identifier: GPL-2.0-only
"""Creative Color Grades transform engine, effective grade resolver, and helpers."""
from __future__ import annotations

import copy
import hashlib
from typing import Any

import numpy as np

from ..ids import canonical_json
from . import grades_catalog

COLOR_FAMILIES = {
    "red": 0.0,
    "orange": 30.0,
    "yellow": 60.0,
    "green": 120.0,
    "aqua": 180.0,
    "blue": 240.0,
    "purple": 280.0,
    "magenta": 320.0,
}


def merge_overrides(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Deep merge of override dictionary into base dictionary without mutating base."""
    merged = copy.deepcopy(base)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = merge_overrides(merged[k], v)
        else:
            merged[k] = copy.deepcopy(v)
    return merged


def resolve_effective_grade(
    global_grade: dict[str, Any] | None,
    frame_overrides: dict[str, Any] | None,
    frame_id: str | None,
    user_presets: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Resolve the effective grade for a given frame.

    Returns:
        (scope, resolved_preset_dict)
        where scope is 'inherited' or 'individual'.
        If no grade is active, resolved_preset_dict is None.
    """
    def _lookup(pid: str) -> dict[str, Any] | None:
        if user_presets and pid in user_presets:
            return copy.deepcopy(user_presets[pid])
        return grades_catalog.get_preset(pid)

    # 1. Check frame-specific override
    if frame_id and frame_overrides and frame_id in frame_overrides:
        fo = frame_overrides[frame_id]
        if not isinstance(fo, dict):
            return "inherited", None
        mode = fo.get("mode")
        if mode == "none":
            return "individual", None
        if mode == "preset":
            pid = fo.get("preset_id", "")
            base = _lookup(pid)
            if not base:
                return "individual", None
            resolved = copy.deepcopy(base)
            if fo.get("overrides"):
                resolved["parameters"] = merge_overrides(resolved.get("parameters", {}), fo["overrides"])
            if fo.get("preset_version"):
                resolved["version"] = fo["preset_version"]
            resolved["strength"] = float(fo.get("strength", 1.0))
            return "individual", resolved

    # 2. Inherit from global grade
    if global_grade and isinstance(global_grade, dict):
        mode = global_grade.get("mode")
        if mode == "preset":
            pid = global_grade.get("preset_id", "")
            base = _lookup(pid)
            if not base:
                return "inherited", None
            resolved = copy.deepcopy(base)
            if global_grade.get("overrides"):
                resolved["parameters"] = merge_overrides(resolved.get("parameters", {}), global_grade["overrides"])
            if global_grade.get("preset_version"):
                resolved["version"] = global_grade["preset_version"]
            resolved["strength"] = float(global_grade.get("strength", 1.0))
            return "inherited", resolved

    return "inherited", None


def effective_grade_hash(grade: dict[str, Any] | None) -> str:
    """Deterministic hash of the effective grade parameters and version."""
    if not grade:
        return hashlib.sha256(b"none").hexdigest()
    doc = {
        "id": grade.get("id"),
        "version": grade.get("version", "1.0.0"),
        "strength": round(float(grade.get("strength", 1.0)), 4),
        "parameters": grade.get("parameters", {}),
    }
    return hashlib.sha256(canonical_json(doc)).hexdigest()


def effective_grade_summary(
    global_grade: dict[str, Any] | None,
    frame_overrides: dict[str, Any] | None,
    frame_id: str,
    revision: int = 0,
    user_presets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Summary descriptor of the effective grade on a specific frame."""
    scope, grade = resolve_effective_grade(global_grade, frame_overrides, frame_id, user_presets=user_presets)
    if grade is None:
        is_override = bool(frame_overrides and frame_id in frame_overrides and frame_overrides[frame_id].get("mode") == "none")
        return {
            "frame_id": frame_id,
            "scope": "individual" if is_override else "inherited",
            "mode": "none",
            "preset_id": None,
            "preset_version": None,
            "strength": 0.0,
            "display_label": "None (this frame)" if is_override else "None — Inherited",
            "style_tags": [],
            "effective_grade_hash": effective_grade_hash(None),
            "revision": revision,
        }

    label_suffix = " — Inherited" if scope == "inherited" else ""
    return {
        "frame_id": frame_id,
        "scope": scope,
        "mode": "preset",
        "preset_id": grade["id"],
        "preset_version": grade.get("version", "1.0.0"),
        "strength": float(grade.get("strength", 1.0)),
        "display_label": f"{grade['name']}{label_suffix}",
        "style_tags": grade.get("tags", []),
        "effective_grade_hash": effective_grade_hash(grade),
        "revision": revision,
    }


def _rgb_to_hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized RGB to HSV (H in degrees 0..360, S and V in 0..1)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    v = maxc
    deltac = maxc - minc

    s = np.where(maxc > 1e-6, deltac / np.maximum(maxc, 1e-6), 0.0)

    # Hue calculation
    rc = np.where(deltac > 1e-6, (maxc - r) / np.maximum(deltac, 1e-6), 0.0)
    gc = np.where(deltac > 1e-6, (maxc - g) / np.maximum(deltac, 1e-6), 0.0)
    bc = np.where(deltac > 1e-6, (maxc - b) / np.maximum(deltac, 1e-6), 0.0)

    h = np.zeros_like(maxc)
    mask_r = (r == maxc) & (deltac > 1e-6)
    mask_g = (g == maxc) & (r != maxc) & (deltac > 1e-6)
    mask_b = (b == maxc) & (r != maxc) & (g != maxc) & (deltac > 1e-6)

    h = np.where(mask_r, bc - gc, h)
    h = np.where(mask_g, 2.0 + rc - bc, h)
    h = np.where(mask_b, 4.0 + gc - rc, h)
    h = (h / 6.0) % 1.0 * 360.0
    return h, s, v


def _hsv_to_rgb(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Vectorized HSV to RGB."""
    h_norm = (h % 360.0) / 60.0
    i = np.floor(h_norm).astype(np.int32) % 6
    f = h_norm - np.floor(h_norm)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))

    r = np.zeros_like(v)
    g = np.zeros_like(v)
    b = np.zeros_like(v)

    m0 = i == 0
    m1 = i == 1
    m2 = i == 2
    m3 = i == 3
    m4 = i == 4
    m5 = i == 5

    r = np.where(m0, v, np.where(m1, q, np.where(m2, p, np.where(m3, p, np.where(m4, t, v)))))
    g = np.where(m0, t, np.where(m1, v, np.where(m2, v, np.where(m3, q, np.where(m4, p, p)))))
    b = np.where(m0, p, np.where(m1, p, np.where(m2, t, np.where(m3, v, np.where(m4, v, q)))))

    return np.stack([r, g, b], axis=-1)


def apply_grade(img: np.ndarray, grade: dict[str, Any] | None) -> np.ndarray:
    """Apply creative color grade to display sRGB image [0.0, 1.0].

    Deterministic, purely vectorized NumPy operations.
    """
    if grade is None:
        return img
    params = grade.get("parameters")
    if not params:
        return img

    strength = float(grade.get("strength", 1.0))
    if strength <= 1e-4:
        return img

    orig = img.astype(np.float32, copy=True)
    out = orig.copy()
    g = params.get("global", {})

    # 1. Tone curve (RGB master)
    curve = params.get("tone_curve", {})
    master_pts = curve.get("rgb_master")
    if master_pts and len(master_pts) >= 2:
        xs = np.array([float(p[0]) for p in master_pts], dtype=np.float32)
        ys = np.array([float(p[1]) for p in master_pts], dtype=np.float32)
        # Interpolate monotonically per channel
        out = np.interp(out, xs, ys).astype(np.float32)

    # 2. Global contrast, black lift, and white rolloff
    contrast = float(g.get("contrast", 0.0))
    if abs(contrast) > 1e-4:
        pivot = 0.5
        out = np.clip(pivot + (out - pivot) * (1.0 + contrast * 0.8), 0.0, 1.0)

    black_lift = float(g.get("black_lift", 0.0))
    if abs(black_lift) > 1e-4:
        if black_lift > 0.0:
            out = out * (1.0 - black_lift) + black_lift
        else:
            out = np.clip((out + black_lift) / (1.0 - abs(black_lift) + 1e-6), 0.0, 1.0)

    white_rolloff = float(g.get("white_rolloff", 0.0))
    if white_rolloff > 1e-4:
        mask = out > 0.7
        compress = white_rolloff * np.square((out - 0.7) / 0.3) * 0.15
        out = np.where(mask, np.maximum(0.0, out - compress), out)

    out = np.clip(out, 0.0, 1.0)

    # 3. Split toning
    split = params.get("split_toning", {})
    if split:
        balance = float(split.get("balance", 0.0))
        # Luminance
        luma = 0.2126 * out[..., 0] + 0.7152 * out[..., 1] + 0.0722 * out[..., 2]
        luma_bal = np.clip(luma - balance * 0.25, 0.0, 1.0)

        # Smooth weights
        w_shadow = np.clip((0.45 - luma_bal) / 0.35, 0.0, 1.0)
        w_highlight = np.clip((luma_bal - 0.55) / 0.35, 0.0, 1.0)
        w_mid = np.maximum(0.0, 1.0 - w_shadow - w_highlight)

        # Apply tint for each zone
        for zone_key, weight in [("shadows", w_shadow), ("midtones", w_mid), ("highlights", w_highlight)]:
            zone_cfg = split.get(zone_key)
            if zone_cfg and float(zone_cfg.get("saturation", 0.0)) > 1e-4:
                hue = float(zone_cfg.get("hue", 0.0))
                sat = float(zone_cfg.get("saturation", 0.0))
                rad = np.radians(hue)
                # Chrominance vector in RGB
                tint_r = np.cos(rad)
                tint_g = np.cos(rad - 2.0 * np.pi / 3.0)
                tint_b = np.cos(rad + 2.0 * np.pi / 3.0)
                tint = np.array([tint_r, tint_g, tint_b], dtype=np.float32)
                out += (weight[..., None] * sat * 0.25) * tint

        out = np.clip(out, 0.0, 1.0)

    # 4. HSL Color Family Adjustments and Skin Protection
    hsl_cfg = params.get("hsl", {})
    skin_cfg = params.get("skin_protection", {})
    has_hsl = any(isinstance(v, dict) and any(abs(float(val)) > 1e-4 for val in v.values()) for v in hsl_cfg.values())
    skin_enabled = skin_cfg.get("enabled", False)
    skin_strength = float(skin_cfg.get("strength", 0.0))

    if has_hsl:
        h, s, v = _rgb_to_hsv(out)

        # Skin mask (protects orange/warm skin tones around 30°)
        skin_mask = np.zeros_like(h)
        if skin_enabled and skin_strength > 1e-4:
            d_skin = np.minimum(np.abs(h - 30.0), 360.0 - np.abs(h - 30.0))
            skin_hue = np.exp(-0.5 * np.square(d_skin / 18.0))
            skin_sat = np.clip((s - 0.1) / 0.15, 0.0, 1.0) * np.clip((0.8 - s) / 0.2, 0.0, 1.0)
            skin_mask = skin_hue * skin_sat * skin_strength

        h_adj = np.zeros_like(h)
        s_scale = np.ones_like(s)
        v_scale = np.ones_like(v)

        for fam_name, center_hue in COLOR_FAMILIES.items():
            fam_adj = hsl_cfg.get(fam_name)
            if not fam_adj:
                continue
            dh_val = float(fam_adj.get("hue", 0.0)) * 60.0  # Normalized hue shift to degrees
            ds_val = float(fam_adj.get("saturation", 0.0))
            dv_val = float(fam_adj.get("luminance", 0.0))

            if abs(dh_val) < 1e-4 and abs(ds_val) < 1e-4 and abs(dv_val) < 1e-4:
                continue

            dist = np.minimum(np.abs(h - center_hue), 360.0 - np.abs(h - center_hue))
            w_fam = np.exp(-0.5 * np.square(dist / 25.0)) * np.clip(s / 0.08, 0.0, 1.0)

            # Dampen on skin if protecting
            if fam_name in ("orange", "yellow", "red") and skin_enabled:
                w_fam = w_fam * (1.0 - skin_mask)

            h_adj += w_fam * dh_val
            s_scale += w_fam * ds_val
            v_scale += w_fam * dv_val

        h = (h + h_adj) % 360.0
        s = np.clip(s * np.maximum(0.0, s_scale), 0.0, 1.0)
        v = np.clip(v * np.maximum(0.0, v_scale), 0.0, 1.0)
        out = _hsv_to_rgb(h, s, v)

    # 5. Global Saturation and Vibrance
    global_sat = float(g.get("global_saturation", 0.0))
    vibrance = float(g.get("vibrance", 0.0))

    if abs(global_sat) > 1e-4 or abs(vibrance) > 1e-4:
        luma = 0.2126 * out[..., 0] + 0.7152 * out[..., 1] + 0.0722 * out[..., 2]
        sat_mult = 1.0 + global_sat
        if abs(vibrance) > 1e-4:
            maxc = np.maximum(np.maximum(out[..., 0], out[..., 1]), out[..., 2])
            minc = np.minimum(np.minimum(out[..., 0], out[..., 1]), out[..., 2])
            cur_sat = np.where(maxc > 1e-6, (maxc - minc) / np.maximum(maxc, 1e-6), 0.0)
            sat_mult = sat_mult * (1.0 + vibrance * (1.0 - cur_sat))
        out = luma[..., None] + (out - luma[..., None]) * np.maximum(0.0, sat_mult)[..., None]

    if abs(strength - 1.0) > 1e-4:
        delta = out - orig
        out = orig + delta * strength

    return np.clip(out, 0.0, 1.0).astype(np.float32)
