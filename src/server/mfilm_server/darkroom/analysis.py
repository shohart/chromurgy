# SPDX-License-Identifier: GPL-2.0-only
"""Smart Auto Exposure and Auto White Balance analyzer (docs/web/30, docs/28).

Extracts camera baseline exposure bias and white balance metadata from RAW
containers, and calculates scene-adaptive Auto Exposure (log-average luminance
middle-gray zone matching with highlight protection) and Shades of Gray
Auto White Balance (Minkowski p-norm illuminant estimation, Kelvin & tint).
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

LUMA_COEFFS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def srgb_to_linear(srgb: np.ndarray) -> np.ndarray:
    """Vectorized sRGB [0.0, 1.0] to scene-linear."""
    x = np.clip(srgb, 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92, np.power((x + 0.055) / 1.055, 2.4)).astype(np.float32)


def compute_auto_exposure(lin_rgb: np.ndarray, baseline_bias: float = 0.0) -> float:
    """Calculate target exposure compensation in EV stops.

    Analyzes midtone log-average luminance against 18% middle-gray Zone V target,
    with upper percentile highlight headroom protection.
    """
    if lin_rgb.size == 0:
        return round(float(baseline_bias), 2)

    luma = lin_rgb[..., 0] * LUMA_COEFFS[0] + lin_rgb[..., 1] * LUMA_COEFFS[1] + lin_rgb[..., 2] * LUMA_COEFFS[2]

    # Filter out deep sensor noise floor and saturated specular blown highlights
    mask = (luma > 0.003) & (luma < 0.98)
    if not np.any(mask):
        return round(float(np.clip(baseline_bias, -3.0, 3.0)), 2)

    valid_luma = luma[mask]

    # Geometric mean / log-average luminance
    log_mean = float(np.exp(np.mean(np.log(np.maximum(valid_luma, 1e-4)))))

    # Middle gray target (18% reflectance)
    target_mid = 0.18
    ev_shift = np.log2(target_mid / max(log_mean, 1e-4))

    # Highlight preservation: ensure 99th percentile doesn't clip past 0.96
    exposed_luma = luma[luma > 0.003]
    if exposed_luma.size > 0:
        p99 = float(np.percentile(exposed_luma, 99.0))
        if p99 > 0.05:
            max_allowed_ev = np.log2(0.96 / p99)
            ev_shift = min(ev_shift, max_allowed_ev)

    # Incorporate camera baseline bias if present
    total_ev = ev_shift + baseline_bias
    return round(float(np.clip(total_ev, -3.0, 3.0)), 2)


def compute_auto_wb(lin_rgb: np.ndarray, p_norm: float = 6.0) -> dict[str, Any]:
    """Calculate Shades of Gray (Minkowski p-norm) illuminant estimate, Kelvin and Tint.

    p=6 Shades of Gray gives robust estimation without bias from dark or low-chroma areas.
    """
    default_wb = {"kelvin": 5500, "tint": 0, "gains": [1.0, 1.0, 1.0]}
    if lin_rgb.size == 0:
        return default_wb

    luma = lin_rgb[..., 0] * LUMA_COEFFS[0] + lin_rgb[..., 1] * LUMA_COEFFS[1] + lin_rgb[..., 2] * LUMA_COEFFS[2]
    mask = (luma > 0.01) & (luma < 0.95)
    if not np.any(mask):
        return default_wb

    r_valid = lin_rgb[..., 0][mask]
    g_valid = lin_rgb[..., 1][mask]
    b_valid = lin_rgb[..., 2][mask]

    # Minkowski p-norm
    r_p = float(np.power(np.mean(np.power(r_valid, p_norm)), 1.0 / p_norm))
    g_p = float(np.power(np.mean(np.power(g_valid, p_norm)), 1.0 / p_norm))
    b_p = float(np.power(np.mean(np.power(b_valid, p_norm)), 1.0 / p_norm))

    if r_p < 1e-6 or g_p < 1e-6 or b_p < 1e-6:
        return default_wb

    gain_r = g_p / r_p
    gain_b = g_p / b_p

    # Correlated Color Temperature mapping from red/blue illuminant gain ratio
    ratio_rb = gain_r / max(gain_b, 1e-6)
    k_est = 5500.0 * (ratio_rb ** 0.65)
    kelvin = int(round(np.clip(k_est, 2000.0, 12000.0) / 50.0) * 50)

    # Tint (- green · + magenta)
    avg_gain = (gain_r + gain_b) / 2.0
    tint_raw = 100.0 * (1.0 - (1.0 / max(avg_gain, 1e-6)))
    tint = int(round(np.clip(tint_raw, -100.0, 100.0)))

    return {
        "kelvin": kelvin,
        "tint": tint,
        "gains": [round(float(gain_r), 4), 1.0, round(float(gain_b), 4)],
    }


def analyze_image_array(srgb_arr: np.ndarray, baseline_bias: float = 0.0) -> dict[str, Any]:
    """Analyze an sRGB image array (e.g. decoded preview / thumbnail) in [0..255] or [0..1]."""
    if srgb_arr.dtype == np.uint8 or srgb_arr.max() > 1.0:
        norm = srgb_arr.astype(np.float32) / 255.0
    else:
        norm = srgb_arr.astype(np.float32)
    lin = srgb_to_linear(norm)
    auto_ev = compute_auto_exposure(lin, baseline_bias=baseline_bias)
    auto_wb = compute_auto_wb(lin)
    return {
        "baseline_ev": round(float(baseline_bias), 2),
        "auto_exposure_ev": auto_ev,
        "auto_wb": auto_wb,
    }


def analyze_raw_path(path: Path | str) -> dict[str, Any]:
    """Comprehensive analysis of a RAW file on disk.

    Extracts EXIF/DNG exposure bias and camera WB, and computes scene auto EV and AWB.
    """
    path = Path(path)
    baseline_ev = 0.0
    camera_wb = None
    daylight_wb = None

    # 1. EXIF extraction
    try:
        with Image.open(path) as im:
            tags = im.getexif()
            sub = tags.get_ifd(0x8769)
            # ExposureBiasValue (37380) or BaselineExposure (50730)
            bias_val = sub.get(37380) or tags.get(50730)
            if bias_val is not None:
                try:
                    baseline_ev = float(bias_val)
                except (TypeError, ValueError):
                    pass
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        pass

    # 2. RAW decode & thumbnail inspection via rawpy
    lin_thumb: np.ndarray | None = None
    try:
        import rawpy
        with rawpy.imread(str(path)) as raw:
            if raw.camera_whitebalance:
                camera_wb = [round(float(x), 2) for x in raw.camera_whitebalance]
            if raw.daylight_whitebalance:
                daylight_wb = [round(float(x), 2) for x in raw.daylight_whitebalance]

            try:
                t = raw.extract_thumb()
                if t.format == rawpy.ThumbFormat.JPEG:
                    im = Image.open(io.BytesIO(t.data)).convert("RGB")
                    arr = np.asarray(im, dtype=np.float32) / 255.0
                    lin_thumb = srgb_to_linear(arr)
                elif t.format == rawpy.ThumbFormat.BITMAP:
                    arr = np.asarray(t.data, dtype=np.float32) / 255.0
                    lin_thumb = srgb_to_linear(arr)
            except Exception:
                pass

            if lin_thumb is None:
                # Fast half-size linear preview if no thumbnail extracted
                arr = raw.postprocess(user_flip=0, half_size=True, gamma=(1, 1), no_auto_bright=True,
                                      output_bps=8, output_color=rawpy.ColorSpace.sRGB)
                lin_thumb = arr.astype(np.float32) / 255.0
    except Exception:
        pass

    if lin_thumb is not None:
        auto_ev = compute_auto_exposure(lin_thumb, baseline_bias=baseline_ev)
        auto_wb = compute_auto_wb(lin_thumb)
    else:
        auto_ev = round(float(baseline_ev), 2)
        auto_wb = {"kelvin": 5500, "tint": 0, "gains": [1.0, 1.0, 1.0]}

    return {
        "baseline_ev": round(float(baseline_ev), 2),
        "auto_exposure_ev": auto_ev,
        "camera_wb": camera_wb,
        "daylight_wb": daylight_wb,
        "auto_wb": auto_wb,
    }
