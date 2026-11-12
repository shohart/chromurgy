# SPDX-License-Identifier: GPL-2.0-only
"""Tests for AI Darkroom Extension (Auto-Enhancement, SA-LUT, Neural Engine)."""
import numpy as np
import pytest

from mfilm_server.ai.types import (
    AIRecipe,
    AutoEnhanceConfig,
    StyleReferenceConfig,
    NeuralEngineConfig
)
from mfilm_server.ai.adaptive_lut import (
    analyze_image_characteristics,
    predict_lut_weights,
    blend_3d_lut,
    apply_3d_lut,
    auto_enhance_image
)
from mfilm_server.ai.sa_lut import (
    extract_style_features,
    construct_style_lut,
    apply_style_reference
)
from mfilm_server.ai.neural_engine import (
    separate_chroma_luma_denoise,
    apply_upscale,
    apply_neural_engine
)
from mfilm_server.ai.pipeline import apply_ai_pipeline
from mfilm_server.darkroom import recipe2
from mfilm_server import core


def test_ai_recipe_types_and_defaults():
    rec = AIRecipe()
    assert rec.mode == "pure"
    assert rec.auto_enhance.enabled is False
    assert rec.auto_enhance.strength == 1.0
    assert rec.style_reference.enabled is False
    assert rec.neural_engine.enabled is False

    d = rec.to_dict()
    assert "auto_enhance" in d
    assert "style_reference" in d
    assert "neural_engine" in d

    rec2 = AIRecipe.from_dict({
        "mode": "hybrid",
        "auto_enhance": {"enabled": True, "strength": 0.85, "style": "vivid"},
        "style_reference": {"enabled": True, "strength": 0.5, "reference_id": "warm_sunset"},
        "neural_engine": {"enabled": True, "engine": "rawnind", "chroma_strength": 0.75}
    })
    assert rec2.mode == "hybrid"
    assert rec2.auto_enhance.enabled is True
    assert rec2.auto_enhance.style == "vivid"
    assert rec2.style_reference.reference_id == "warm_sunset"
    assert rec2.neural_engine.chroma_strength == 0.75


def test_tier1_adaptive_lut_enhancement():
    # Synthetic gradient image
    img = np.zeros((128, 128, 3), dtype=np.float32)
    img[..., 0] = np.linspace(0.1, 0.8, 128)[:, None]
    img[..., 1] = np.linspace(0.1, 0.7, 128)[None, :]
    img[..., 2] = 0.3

    stats = analyze_image_characteristics(img)
    assert 0.0 < stats["mean_luma"] < 1.0
    assert stats["dynamic_range"] > 0

    weights = predict_lut_weights(stats, style="standard")
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert "shadow_recovery" in weights

    lut = blend_3d_lut(weights, dim=17)
    assert lut.shape == (17, 17, 17, 3)

    enhanced = apply_3d_lut(img, lut)
    assert enhanced.shape == img.shape
    assert np.all(enhanced >= 0.0) and np.all(enhanced <= 1.0)

    # auto_enhance_image wrapper with disabled config returns original
    off_cfg = AutoEnhanceConfig(enabled=False)
    assert np.array_equal(auto_enhance_image(img, off_cfg), img)

    # with enabled config returns enhanced image
    on_cfg = AutoEnhanceConfig(enabled=True, strength=0.8, style="vivid")
    res = auto_enhance_image(img, on_cfg)
    assert not np.array_equal(res, img)
    assert res.shape == img.shape


def test_tier2_sa_lut_style_transfer():
    target = np.ones((64, 64, 3), dtype=np.float32) * 0.4
    # Warm golden reference
    ref = np.zeros((64, 64, 3), dtype=np.float32)
    ref[..., 0] = 0.9  # warm red/yellow
    ref[..., 1] = 0.7
    ref[..., 2] = 0.2

    feats = extract_style_features(ref)
    assert feats["highlight_rgb"][0] > feats["highlight_rgb"][2]

    lut = construct_style_lut(feats, dim=17)
    assert lut.shape == (17, 17, 17, 3)

    cfg = StyleReferenceConfig(enabled=True, strength=0.9, preserve_skin=True)
    styled = apply_style_reference(target, ref, cfg)
    assert styled.shape == target.shape
    # Warm shift should significantly increase red-to-blue ratio
    assert np.mean(styled[..., 0]) > np.mean(target[..., 0])
    target_rb = np.mean(target[..., 0]) / np.mean(target[..., 2])
    styled_rb = np.mean(styled[..., 0]) / np.mean(styled[..., 2])
    assert styled_rb > target_rb


def test_tier3_neural_engine_denoise_and_upscale():
    # Create noisy image with chroma noise
    np.random.seed(42)
    clean = np.ones((64, 64, 3), dtype=np.float32) * 0.5
    noise = np.random.normal(0, 0.08, clean.shape).astype(np.float32)
    noisy = np.clip(clean + noise, 0.0, 1.0)

    denoised = separate_chroma_luma_denoise(noisy, chroma_strength=0.9, luma_strength=0.5, detail_preservation=0.8)
    assert denoised.shape == noisy.shape
    # Denoising should reduce variance
    assert np.var(denoised) < np.var(noisy)

    # Upscale 2x
    upscaled = apply_upscale(clean, scale=2)
    assert upscaled.shape == (128, 128, 3)


def test_ai_pipeline_orchestration():
    img = np.ones((64, 64, 3), dtype=np.float32) * 0.3
    recipe = AIRecipe(
        mode="pure",
        auto_enhance=AutoEnhanceConfig(enabled=True, strength=0.5, style="standard"),
        neural_engine=NeuralEngineConfig(enabled=True, chroma_strength=0.5)
    )
    out = apply_ai_pipeline(img, recipe)
    assert out.shape == img.shape
    assert np.all(out >= 0.0) and np.all(out <= 1.0)


def test_recipe2_ai_extension_normalization():
    from mfilm_server.darkroom import engine
    bundle = engine.current_bundle()
    base_rec = recipe2.default("portra400", bundle)
    base_rec["extensions"] = {
        "ai": {
            "mode": "pure",
            "auto_enhance": {"enabled": True, "strength": 0.8, "style": "vivid"},
            "style_reference": {"enabled": False},
            "neural_engine": {"enabled": False}
        }
    }
    norm = recipe2.normalize(base_rec, bundle)
    assert "extensions" in norm
    assert "ai" in norm["extensions"]
    assert norm["extensions"]["ai"]["mode"] == "pure"
    assert norm["extensions"]["ai"]["auto_enhance"]["strength"] == 0.8

    # In pure mode, to_v1 forces film_profile_id = 'none'
    v1 = recipe2.to_v1(norm)
    assert v1["film_profile_id"] == "none"
    assert "ai" in v1

    # In hybrid mode, to_v1 preserves original film stock
    norm["extensions"]["ai"]["mode"] = "hybrid"
    v1_hybrid = recipe2.to_v1(norm)
    assert v1_hybrid["film_profile_id"] == "portra400"
    assert "ai" in v1_hybrid
