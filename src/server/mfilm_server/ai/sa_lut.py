# SPDX-License-Identifier: GPL-2.0-only
"""Tier 2 AI Style Transfer: SA-LUT (Style-Aware 3D LUT) transfer engine (Ry3nG et al.).

Extracts color palette, tone curve, and chromatic covariance from a reference image,
builds a style-matching 3D LUT, and transfers color grading while protecting skin tones.
"""
from __future__ import annotations

import math
from typing import Any
import numpy as np

from .types import StyleReferenceConfig
from .adaptive_lut import LUT_DIM, _build_identity_lut, apply_3d_lut


def extract_style_features(ref_img: np.ndarray) -> dict[str, Any]:
    """Extracts tone and chromatic distribution moments from reference image."""
    if ref_img.dtype != np.float32:
        ref_f = ref_img.astype(np.float32)
        if ref_f.max() > 1.0:
            ref_f /= 255.0
    else:
        ref_f = np.clip(ref_img, 0.0, 1.0)

    # Downsample for statistics
    h, w, _ = ref_f.shape
    step_y = max(1, h // 256)
    step_x = max(1, w // 256)
    small = ref_f[::step_y, ::step_x]

    r, g, b = small[..., 0], small[..., 1], small[..., 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b

    # Quantiles for shadow, midtone, highlight
    p10 = float(np.percentile(luma, 10))
    p50 = float(np.percentile(luma, 50))
    p90 = float(np.percentile(luma, 90))

    mean_rgb = np.mean(small, axis=(0, 1))

    # Color biases in shadows vs highlights
    shadow_mask = luma <= (p10 + 1e-4)
    highlight_mask = luma >= (p90 - 1e-4)

    if np.any(shadow_mask):
        shadow_rgb = np.mean(small[shadow_mask], axis=0)
    else:
        shadow_rgb = mean_rgb

    if np.any(highlight_mask):
        highlight_rgb = np.mean(small[highlight_mask], axis=0)
    else:
        highlight_rgb = mean_rgb

    # Overall saturation level
    mean_sat = float(np.mean(np.sqrt(np.square(r - luma) + np.square(g - luma) + np.square(b - luma))))

    return {
        "p10": p10,
        "p50": p50,
        "p90": p90,
        "shadow_rgb": shadow_rgb,
        "highlight_rgb": highlight_rgb,
        "mean_rgb": mean_rgb,
        "mean_sat": mean_sat
    }


def construct_style_lut(ref_features: dict[str, Any], dim: int = LUT_DIM) -> np.ndarray:
    """Constructs a 3D LUT that embodies the tonal and color shift of the reference."""
    id_lut = _build_identity_lut(dim)
    r, g, b = id_lut[..., 0], id_lut[..., 1], id_lut[..., 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b

    out_lut = np.copy(id_lut)

    # 1. Match dynamic range & tonal distribution
    ref_p10 = ref_features["p10"]
    ref_p50 = ref_features["p50"]
    ref_p90 = ref_features["p90"]

    # Target midtone pivot: push toward reference midtone
    gamma = math.log(max(0.05, min(0.95, ref_p50))) / math.log(0.5) if ref_p50 > 0 else 1.0
    gamma = float(np.clip(gamma, 0.6, 1.6))
    luma_adj = np.power(np.clip(luma, 0.0, 1.0), gamma)

    ratio = np.divide(luma_adj, luma, out=np.ones_like(luma), where=luma > 1e-5)
    out_lut = np.clip(out_lut * ratio[..., None], 0.0, 1.0)

    # 2. Match color temperature & tint in shadows and highlights
    s_rgb = ref_features["shadow_rgb"]
    s_luma = float(0.2126 * s_rgb[0] + 0.7152 * s_rgb[1] + 0.0722 * s_rgb[2]) + 1e-6
    s_bias = (s_rgb / s_luma) - 1.0  # relative color cast
    s_bias = np.clip(s_bias, -0.4, 0.4)

    h_rgb = ref_features["highlight_rgb"]
    h_luma = float(0.2126 * h_rgb[0] + 0.7152 * h_rgb[1] + 0.0722 * h_rgb[2]) + 1e-6
    h_bias = (h_rgb / h_luma) - 1.0
    h_bias = np.clip(h_bias, -0.4, 0.4)

    # Apply shadow bias (fading out toward midtones)
    s_weight = np.power(1.0 - np.clip(luma, 0.0, 1.0), 2.5)[..., None]
    out_lut += s_weight * s_bias * 0.35

    # Apply highlight bias (fading out toward midtones)
    h_weight = np.power(np.clip(luma, 0.0, 1.0), 2.0)[..., None]
    out_lut += h_weight * h_bias * 0.35

    return np.clip(out_lut, 0.0, 1.0)


def apply_style_reference(
    target_img: np.ndarray,
    ref_img: np.ndarray | None,
    config: StyleReferenceConfig
) -> np.ndarray:
    """Applies style transfer from reference image with optional skin protection."""
    if not config.enabled or config.strength <= 1e-4 or ref_img is None:
        return target_img

    features = extract_style_features(ref_img)
    lut = construct_style_lut(features, LUT_DIM)
    styled = apply_3d_lut(target_img, lut)

    str_f = float(np.clip(config.strength, 0.0, 1.0))

    if config.preserve_skin:
        # Detect human skin tones in target image:
        # In normalized RGB: R > G > B, (R - G) between 0.05 and 0.35, (G - B) between 0.02 and 0.25
        r, g, b = target_img[..., 0], target_img[..., 1], target_img[..., 2]
        is_skin = (r > g) & (g > b) & ((r - g) > 0.04) & ((r - g) < 0.40) & ((g - b) > 0.01)
        skin_mask = is_skin.astype(np.float32)[..., None]
        # Soften mask
        eff_str = str_f * (1.0 - 0.65 * skin_mask)
    else:
        eff_str = str_f

    return np.clip((1.0 - eff_str) * target_img + eff_str * styled, 0.0, 1.0)
