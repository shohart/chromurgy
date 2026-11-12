# SPDX-License-Identifier: GPL-2.0-only
"""Tier 1 AI Auto-Enhancement: Image-Adaptive 3D LUT engine (Hui Zeng et al.).

Evaluates image scene luminance, dynamic range, and chroma characteristics,
predicts adaptive mixture weights across basis 3D LUTs, and applies the blended
3D LUT with full floating-point accuracy.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .types import AutoEnhanceConfig


LUT_DIM = 17  # 17x17x17 lattice (standard for real-time 3D LUT evaluation)


def _build_identity_lut(dim: int = LUT_DIM) -> np.ndarray:
    """Returns (dim, dim, dim, 3) identity lattice in [0, 1]."""
    x = np.linspace(0.0, 1.0, dim, dtype=np.float32)
    r, g, b = np.meshgrid(x, x, x, indexing="ij")
    return np.stack([r, g, b], axis=-1)


def _build_basis_luts(dim: int = LUT_DIM) -> dict[str, np.ndarray]:
    """Generates calibrated basis 3D LUTs representing core tonal enhancements."""
    id_lut = _build_identity_lut(dim)
    r, g, b = id_lut[..., 0], id_lut[..., 1], id_lut[..., 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b

    # 1. Shadow recovery + highlight protection (S-curve with lifted shadows)
    # y = x + 0.2 * sin(pi * x) * (1 - x)
    lift = 0.25 * np.sin(np.pi * luma) * (1.0 - luma)
    luma_lifted = np.clip(luma + lift, 0.0, 1.0)
    ratio_1 = np.divide(luma_lifted, luma, out=np.ones_like(luma), where=luma > 1e-5)
    lut_shadow_rec = np.clip(id_lut * ratio_1[..., None], 0.0, 1.0)

    # 2. Contrast & micro-clarity (sigmoid contrast curve centered at 0.45)
    # y = 1 / (1 + exp(-6 * (x - 0.45)))
    c_curve = 1.0 / (1.0 + np.exp(-7.0 * (luma - 0.42)))
    # normalize to 0..1
    c_min = 1.0 / (1.0 + np.exp(-7.0 * (0.0 - 0.42)))
    c_max = 1.0 / (1.0 + np.exp(-7.0 * (1.0 - 0.42)))
    c_curve = (c_curve - c_min) / (c_max - c_min)
    ratio_2 = np.divide(c_curve, luma, out=np.ones_like(luma), where=luma > 1e-5)
    lut_contrast = np.clip(id_lut * ratio_2[..., None], 0.0, 1.0)

    # 3. Vivid & Color Vibrance (saturation boost biased towards greens/blues, protecting skin)
    mean_rgb = (r + g + b) / 3.0
    sat_factor = 1.28
    # Skin tone protection: hue roughly orange/red
    skin_mask = np.clip((r - b) * 2.0, 0.0, 1.0) * np.clip(1.0 - np.abs(g - b) * 2.0, 0.0, 1.0)
    eff_sat = sat_factor - 0.22 * skin_mask
    lut_vivid = np.clip(mean_rgb[..., None] + (id_lut - mean_rgb[..., None]) * eff_sat[..., None], 0.0, 1.0)

    # 4. Cinematic Warmth (golden hour highlights, cool teal shadows)
    lut_cinematic = np.copy(id_lut)
    # Warm highlights: increase red/green in upper half
    lut_cinematic[..., 0] += 0.06 * np.power(luma, 1.5)
    lut_cinematic[..., 1] += 0.03 * np.power(luma, 1.5)
    # Cool shadows: increase blue in lower half
    lut_cinematic[..., 2] += 0.05 * np.power(1.0 - luma, 2.0)
    lut_cinematic = np.clip(lut_cinematic, 0.0, 1.0)

    return {
        "identity": id_lut,
        "shadow_recovery": lut_shadow_rec,
        "contrast": lut_contrast,
        "vivid": lut_vivid,
        "cinematic": lut_cinematic
    }


_BASIS_LUTS = _build_basis_luts(LUT_DIM)


def analyze_image_characteristics(img: np.ndarray) -> dict[str, float]:
    """Analyzes a downsampled image to compute scene brightness, contrast, and saturation statistics."""
    # Ensure float32 in [0, 1]
    if img.dtype != np.float32:
        img_f = img.astype(np.float32)
        if img_f.max() > 1.0:
            img_f /= 255.0
    else:
        img_f = np.clip(img, 0.0, 1.0)

    # Downsample if larger than 256 on max side for fast feature extraction
    h, w, _ = img_f.shape
    step_y = max(1, h // 256)
    step_x = max(1, w // 256)
    small = img_f[::step_y, ::step_x]

    r, g, b = small[..., 0], small[..., 1], small[..., 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b

    mean_luma = float(np.mean(luma))
    std_luma = float(np.std(luma))
    p10 = float(np.percentile(luma, 10))
    p90 = float(np.percentile(luma, 90))
    dynamic_range = p90 - p10

    # Chroma saturation measure
    chroma = np.sqrt(np.square(r - luma) + np.square(g - luma) + np.square(b - luma))
    mean_sat = float(np.mean(chroma))

    return {
        "mean_luma": mean_luma,
        "std_luma": std_luma,
        "p10": p10,
        "p90": p90,
        "dynamic_range": dynamic_range,
        "mean_sat": mean_sat
    }


def predict_lut_weights(stats: dict[str, float], style: str = "standard") -> dict[str, float]:
    """Predicts optimal mixing weights for the basis 3D LUTs based on scene statistics."""
    # Under-exposed scene -> needs shadow recovery
    need_recovery = max(0.0, min(1.0, (0.42 - stats["mean_luma"]) * 2.5))
    # Low dynamic range / flat image -> needs contrast
    need_contrast = max(0.0, min(1.0, (0.55 - stats["dynamic_range"]) * 2.2))
    # Pale / washed-out image -> needs vividness
    need_vivid = max(0.0, min(1.0, (0.20 - stats["mean_sat"]) * 3.0))

    if style == "vivid":
        need_vivid = min(1.0, need_vivid + 0.4)
        need_contrast = min(1.0, need_contrast + 0.2)
    elif style == "portrait":
        # Softer contrast, subtle warmth, less harsh saturation
        need_contrast *= 0.5
        need_vivid *= 0.4
    elif style == "cinematic":
        need_contrast = min(1.0, need_contrast + 0.3)

    # Base identity weight ensures stability
    w_identity = 0.35
    w_shadow = need_recovery * 0.40
    w_contrast = need_contrast * 0.35
    w_vivid = need_vivid * (0.35 if style == "vivid" else 0.20)
    w_cinematic = 0.25 if style == "cinematic" else 0.05

    total = w_identity + w_shadow + w_contrast + w_vivid + w_cinematic
    if total <= 0:
        return {"identity": 1.0}

    return {
        "identity": w_identity / total,
        "shadow_recovery": w_shadow / total,
        "contrast": w_contrast / total,
        "vivid": w_vivid / total,
        "cinematic": w_cinematic / total
    }


def blend_3d_lut(weights: dict[str, float], dim: int = LUT_DIM) -> np.ndarray:
    """Blends basis 3D LUTs according to predicted weights."""
    out_lut = np.zeros((dim, dim, dim, 3), dtype=np.float32)
    for name, w in weights.items():
        if w > 1e-4 and name in _BASIS_LUTS:
            out_lut += _BASIS_LUTS[name] * np.float32(w)
    return np.clip(out_lut, 0.0, 1.0)


def apply_3d_lut(img: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Applies a 3D LUT using fast vectorized trilinear interpolation on [0, 1] RGB image."""
    orig_shape = img.shape
    dim = lut.shape[0]

    # Flatten pixels to (N, 3)
    flat = np.clip(img.reshape(-1, 3), 0.0, 1.0)
    coords = flat * (dim - 1)

    # Lower and upper integer grid indices
    i0 = np.floor(coords).astype(np.int32)
    i1 = np.minimum(i0 + 1, dim - 1)

    # Fractional offsets
    f = coords - i0
    f_r, f_g, f_b = f[:, 0, None], f[:, 1, None], f[:, 2, None]

    r0, g0, b0 = i0[:, 0], i0[:, 1], i0[:, 2]
    r1, g1, b1 = i1[:, 0], i1[:, 1], i1[:, 2]

    # 8 corner samples
    c000 = lut[r0, g0, b0]
    c100 = lut[r1, g0, b0]
    c010 = lut[r0, g1, b0]
    c110 = lut[r1, g1, b0]
    c001 = lut[r0, g0, b1]
    c101 = lut[r1, g0, b1]
    c011 = lut[r0, g1, b1]
    c111 = lut[r1, g1, b1]

    # Trilinear interpolate
    c00 = c000 * (1.0 - f_r) + c100 * f_r
    c01 = c001 * (1.0 - f_r) + c101 * f_r
    c10 = c010 * (1.0 - f_r) + c110 * f_r
    c11 = c011 * (1.0 - f_r) + c111 * f_r

    c0 = c00 * (1.0 - f_g) + c10 * f_g
    c1 = c01 * (1.0 - f_g) + c11 * f_g

    result = c0 * (1.0 - f_b) + c1 * f_b
    return np.clip(result.reshape(orig_shape), 0.0, 1.0)


def auto_enhance_image(img: np.ndarray, config: AutoEnhanceConfig) -> np.ndarray:
    """High-level entry point: runs Image-Adaptive 3D LUT enhancement with strength blending."""
    if not config.enabled or config.strength <= 1e-4:
        return img

    stats = analyze_image_characteristics(img)
    weights = predict_lut_weights(stats, style=config.style)
    lut = blend_3d_lut(weights, LUT_DIM)
    enhanced = apply_3d_lut(img, lut)

    str_f = float(np.clip(config.strength, 0.0, 1.0))
    if str_f >= 0.999:
        return enhanced
    return (1.0 - str_f) * img + str_f * enhanced
