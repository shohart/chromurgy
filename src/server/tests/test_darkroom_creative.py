"""Numeric checks of the creative stage (docs/web/24): synthetic scenes, no RAW needed."""
import numpy as np
import pytest

from mfilm_server.darkroom import catalog, creative
from mfilm_server.darkroom.creative_params import EFFECTS, LOOKS

EFFECT_IDS = [i for i, _ in catalog.OPTICAL_EFFECTS]


def scene(w=240, h=160):
    """Dim room (0.05) with a small blown-out window (4.0) and a mid-grey card, plus a colour gradient."""
    x = np.full((h, w, 3), 0.05, np.float32)
    x[60:100, 100:140] = 4.0                                   # bright source, scene-linear above white
    x[20:50, 20:60] = 0.18
    x[110:150, 150:230] = np.linspace(0.02, 0.9, 80)[None, :, None] * np.array([1.0, 0.6, 0.3], np.float32)
    return x


def stack(*ids, **over):
    return [{"id": i, "enabled": True, "parameters": {**EFFECTS[i], **over}} for i in ids]


@pytest.mark.parametrize("eid", EFFECT_IDS)
def test_effect_at_strength_zero_is_exactly_neutral(eid):
    x = scene()
    assert np.array_equal(creative.apply_optics(x, stack(eid), 0.0), x)


@pytest.mark.parametrize("eid", EFFECT_IDS)
def test_effect_is_finite_nonnegative_and_deterministic(eid):
    x = scene()
    a = creative.apply_optics(x, stack(eid), 0.8)
    assert np.isfinite(a).all() and a.min() >= -1e-6
    assert np.array_equal(a, creative.apply_optics(x, stack(eid), 0.8))
    assert np.abs(a - x).max() > 1e-3                           # it does something
    extreme = creative.apply_optics(x, stack(eid), 4.0)
    assert np.isfinite(extreme).all() and extreme.min() >= -1e-6


@pytest.mark.parametrize("eid", ["soft_sun_glow", "ricoh_hdf_diffusion", "black_pro_mist_like", "orton_glow"])
def test_bright_pixels_spill_into_neighbours_and_far_dark_stays_put(eid):
    x = scene()
    a = creative.apply_optics(x, stack(eid), 0.5)
    near = (slice(100, 110), slice(100, 140))                  # just below the window
    far = (slice(0, 10), slice(0, 10))                         # opposite corner
    assert (a[near] - x[near]).mean() > 0.002                  # light spreads out of the source ...
    assert abs((a[far] - x[far]).mean()) < 0.5 * (a[near] - x[near]).mean()   # ... and mostly stays local


def test_effect_strength_is_monotonic():
    x = scene()
    d = [np.abs(creative.apply_optics(x, stack("soft_sun_glow"), k) - x).mean() for k in (0.25, 0.5, 0.75, 1.0, 2.0, 4.0)]
    assert d == sorted(d) and d[0] > 0


def test_sun_glow_is_warm_and_halation_is_red():
    x = scene()
    g = creative.apply_optics(x, stack("soft_sun_glow"), 0.8) - x
    assert g[100:110, 100:140, 0].mean() > g[100:110, 100:140, 2].mean()
    h = creative.apply_optics(x, stack("film_halation_extra"), 0.8) - x
    assert h[..., 0].sum() > 2 * h[..., 2].sum() and h[..., 2].min() >= -1e-6


def test_radii_are_fractions_of_the_diagonal_so_scale_does_not_change_the_look():
    big = scene(480, 320)
    small = big[::2, ::2]                                       # same picture at half size
    a = creative.apply_optics(big, stack("soft_sun_glow"), 0.7)[::2, ::2]
    b = creative.apply_optics(small, stack("soft_sun_glow"), 0.7)
    assert np.abs(a - b).mean() < 0.03 * max(float(a.mean()), 0.05)     # resampling noise only


def test_engine_order_is_fixed_not_the_clients():
    x = scene()
    a = creative.apply_optics(x, stack("orton_glow", "soft_sun_glow"), 0.6)
    b = creative.apply_optics(x, stack("soft_sun_glow", "orton_glow"), 0.6)
    assert np.array_equal(a, b)


def test_disabled_item_does_nothing():
    x = scene()
    s = stack("soft_sun_glow")
    s[0]["enabled"] = False
    assert np.array_equal(creative.apply_optics(x, s, 1.0), x)


def test_neutral_look_and_zero_strength_are_identity():
    x = scene()
    assert np.array_equal(creative.apply_look(x, "neutral", 1.0), x)
    for lid in LOOKS:
        assert np.array_equal(creative.apply_look(x, lid, 0.0), x)


@pytest.mark.parametrize("lid", [i for i in LOOKS if i != "neutral"])
def test_every_look_is_finite_distinct_and_blends_linearly(lid):
    x = scene()
    full = creative.apply_look(x, lid, 1.0)
    assert np.isfinite(full).all() and full.min() >= 0 and np.abs(full - x).max() > 1e-3
    half = creative.apply_look(x, lid, 0.5)
    assert np.allclose(half, (x + full) / 2, atol=1e-4)          # strength blends in linear light
    double = creative.apply_look(x, lid, 2.0)
    assert np.isfinite(double).all() and double.min() >= 0
    assert np.abs(double - x).max() > np.abs(full - x).max()     # 200% strength is noticeably punchier than 100%
    quad = creative.apply_look(x, lid, 4.0)
    assert np.isfinite(quad).all() and quad.min() >= 0
    assert np.abs(quad - x).max() >= np.abs(double - x).max()    # 400% maximum strength continues scaling
    for other in LOOKS:
        if other not in ("neutral", lid):
            assert np.abs(creative.apply_look(x, other, 1.0) - full).max() > 1e-4, f"{lid} == {other}"


def test_looks_have_their_documented_character():
    x = scene()
    mid = np.full((8, 8, 3), 0.18, np.float32)
    assert np.allclose(creative.apply_look(mid, "leica_m9_ccd", 1.0), mid, atol=0.02)      # pivot stays near grey
    ramp = np.linspace(0.001, 1.0, 256, dtype=np.float32)[None, :, None].repeat(3, 2).repeat(8, 0)
    hi = creative.apply_look(ramp, "fujifilm_xpro3_classic_negative", 1.0)[0, :, 1]
    lo = creative.apply_look(ramp, "fujifilm_s5_pro", 1.0)[0, :, 1]
    assert np.all(np.diff(hi) > 0) and np.all(np.diff(lo) > 0)                              # tone curves stay monotonic
    assert hi[40] < ramp[0, 40, 1] and lo[40] > hi[40]            # classic negative: more contrast than the soft S5 curve
    colour = x[110:150, 150:230]
    def sat(a):                                                    # chroma relative to luminance, so contrast does not count
        y = creative.luma(a)[..., None]
        return float((np.abs(a - y) / np.maximum(y, 1e-6)).mean())
    assert sat(creative.apply_look(colour, "fujifilm_xpro3_classic_negative", 1.0)) < sat(colour) < \
        sat(creative.apply_look(colour, "ricoh_gr_iii_positive", 1.0))                         # chroma gain 0.9 vs 1.13


def test_creative_block_none_is_identity_and_full_block_runs_in_order():
    x = scene()
    assert creative.apply_creative(x, None) is x
    blk = {"version": creative.VERSION, "camera_look": {"id": "leica_m9_ccd", "strength": 0.8},
           "optical": {"strength": 0.45, "stack": stack("soft_sun_glow")}}
    out = creative.apply_creative(x, blk)
    assert out.dtype == np.float32 and out.shape == x.shape and np.abs(out - x).max() > 0.01
    only_optics = creative.apply_optics(x, blk["optical"]["stack"], 0.45)
    assert np.array_equal(out, creative.apply_look(only_optics, "leica_m9_ccd", 0.8).astype(np.float32))   # optics, then look


def test_comparison_sheet_tool_runs_on_the_synthetic_scene(tmp_path):
    import importlib.util

    from conftest import REPO
    spec = importlib.util.spec_from_file_location("creative_sheet", REPO / "tools" / "creative_sheet.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--out", str(tmp_path)]) == 0
    from PIL import Image
    assert Image.open(tmp_path / "optics.png").size[0] == 600 * 4 and Image.open(tmp_path / "looks.png").size[1] > 400
