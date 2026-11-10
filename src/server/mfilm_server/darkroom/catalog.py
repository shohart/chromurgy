# SPDX-License-Identifier: GPL-2.0-only
"""What the Darkroom can offer, derived from the engine actually installed.

Camera Looks and optical effects are listed with `supported` False until the
C core implements them: the UI shows them disabled and recipe validation
rejects them. A label must never be accepted and then rendered as neutral
(docs/web/27 requirement 4, docs/web/34 W03)."""
from __future__ import annotations

import json
from pathlib import Path

from .. import core
from . import creative, optics
from . import optical_registry as reg
from .creative_params import EFFECTS as _FX
from .creative_params import LOOKS as _LOOKS

CAMERA_LOOKS = [
    # id, name, evidence tier (contracts/v0.5/camera-presets.yaml)
    ("neutral", "Neutral rendering", "baseline"),
    ("leica_m8_ccd", "Leica M8 CCD", "inspired"),
    ("leica_m9_ccd", "Leica M9 CCD", "inspired"),
    ("fujifilm_s5_pro", "Fujifilm FinePix S5 Pro", "inspired"),
    ("nikon_d200_ccd", "Nikon D200 CCD", "inspired"),
    ("pentax_645d_ccd", "Pentax 645D CCD", "inspired"),
    ("ricoh_gr_iii_positive", "Ricoh GR III Positive Film", "inspired"),
    ("sigma_dp2_merrill_foveon", "Sigma DP2 Merrill Foveon Look", "inspired"),
    ("fujifilm_xpro3_classic_negative", "Fujifilm X-Pro3 Classic Negative", "inspired"),
    ("fujifilm_x100vi", "Fujifilm X100VI (Reala Ace)", "inspired"),
    # Iconic film cameras
    ("hasselblad_500cm", "Hasselblad 500 C/M (Zeiss Planar)", "inspired"),
    ("leica_m6_rangefinder", "Leica M6 Rangefinder (Summicron)", "inspired"),
    ("contax_t2_sonnar", "Contax T2 (Carl Zeiss Sonnar)", "inspired"),
    ("mamiya_7_ii", "Mamiya 7 II (Sekor 80mm)", "inspired"),
    ("olympus_om1_zuiko", "Olympus OM-1 (OM Zuiko)", "inspired"),
    ("pentax_k1000", "Pentax K1000 (SMC 50mm)", "inspired"),
    ("pentax_67", "Pentax 67 (SMC 105mm f/2.4)", "inspired"),
    ("rolleiflex_28f_tlr", "Rolleiflex 2.8F TLR (Planar)", "inspired"),
    ("zenit_e_ttl", "Zenit E / TTL (Helios 44)", "inspired"),
    ("zorki_4", "Zorki 4 (Jupiter-8)", "inspired"),
    ("polaroid_sx70_instant", "Polaroid SX-70 Instant", "inspired"),
    ("lomo_lca", "Lomo LC-A (Minitar-1)", "inspired"),
]
OPTICAL_EFFECTS = [
    ("soft_sun_glow", "Soft Sun Glow"),
    ("ricoh_hdf_diffusion", "Ricoh HDF-inspired diffusion"),
    ("black_pro_mist_like", "Black Pro-Mist-like mist"),
    ("vintage_veiling_flare", "Vintage veiling flare"),
    ("film_halation_extra", "Film halation (extra)"),
    ("orton_glow", "Orton glow"),
]
# the operators added in spec v0.6 (darkroom/optics.py), in engine order; the six above keep their own list
OPTICAL_EFFECTS_V06 = [(i, reg.new_effects()[i]["name"]) for i in creative.NEW_EFFECTS]
ALL_EFFECT_IDS = [i for i, _ in OPTICAL_EFFECTS] + [i for i, _ in OPTICAL_EFFECTS_V06]
# implemented in darkroom/creative.py + optics.py (numpy, Linux server only)
SUPPORTED_LOOKS = {i for i, _, _ in CAMERA_LOOKS}
SUPPORTED_EFFECTS = set(ALL_EFFECT_IDS) | {"golden_haze", "vintage_glass"}


# camera-presets.yaml composites: a one-click combination of look, film and optics (film names resolved at use)
COMPOSITES = [
    {"id": "golden_haze", "name": "Golden Haze", "camera_look": "fujifilm_s5_pro", "look_strength": 0.5, "film": "kodak-gold-200",
     "optical_preset": "golden_haze", "optical_strength": 0.75},
    {"id": "leica-m9-portra-sun-v1", "name": "Leica M9 + Portra + Soft Sun Glow", "camera_look": "leica_m9_ccd", "look_strength": 0.8,
     "film": "kodak-portra-400", "optical_preset": "soft_sun_glow", "optical_strength": 0.45},
    {"id": "ricoh-gr-hdf-street", "name": "Ricoh GR III HDF Street", "camera_look": "ricoh_gr_iii_positive", "look_strength": 0.9,
     "film": None, "optical_preset": "ricoh_hdf_diffusion", "optical_strength": 0.65},
    {"id": "fuji-s5-portrait", "name": "Fuji S5 Portrait", "camera_look": "fujifilm_s5_pro", "look_strength": 1.0,
     "film": "kodak-portra-400", "optical_preset": "black_pro_mist_like", "optical_strength": 0.2},
    {"id": "cine-halo", "name": "Cine Halo", "camera_look": "neutral", "look_strength": 1.0, "film": "cinestill-800t",
     "optical_preset": "film_halation_extra", "optical_strength": 0.35, "halation_policy": "optical"},
]


def effect_view(eid: str, name: str) -> dict:
    """One optical effect as the API/UI sees it: group, description, typed controls with bounds, source support."""
    base = {"id": eid, "name": name, "supported": eid in SUPPORTED_EFFECTS, "defaults": _FX[eid]}
    if eid in reg.new_effects():
        d = reg.new_effects()[eid]
        return {**base, "group": d["group"], "kind": d["kind"], "wave": d["wave"], "stage": d["stage"], "description": d["description"],
                "tags": d["tags"], "controls": d["controls"], "source_driven": eid in optics.SOURCE_DRIVEN,
                "implementation_version": optics.IMPLEMENTATION_VERSION}
    d = reg.legacy_effects()[eid]
    return {**base, "group": d["group"], "kind": "effect", "wave": 0, "description": "", "tags": [], "source_driven": False,
            "controls": {k: {"default": v, "minimum": creative.PARAM_RANGE[k][0], "maximum": creative.PARAM_RANGE[k][1]}
                         for k, v in _FX[eid].items()}}


def _films_meta() -> dict[str, dict]:
    p = core.bundle_path().with_name("films.json")
    try:
        return {f["key"]: f for f in json.loads(Path(p).read_text())["films"]}
    except (OSError, ValueError, KeyError):
        return {}


def films(bundle: core.Bundle) -> list[dict]:
    meta = _films_meta()
    return [{"id": k, "name": meta.get(k, {}).get("name", k), "short": meta.get(k, {}).get("short", k),
             "iso": meta.get(k, {}).get("iso"), "kind": meta.get(k, {}).get("kind")} for k in bundle.keys]


def build(bundle: core.Bundle) -> dict:
    return {
        "profile_bundle_hash": bundle.sha256,
        "film_core_version": core.core_version(),
        "creative_version": creative.VERSION,
        "camera_looks": [{"id": i, "name": n, "evidence_tier": t, "supported": i in SUPPORTED_LOOKS, "params": _LOOKS[i]}
                         for i, n, t in CAMERA_LOOKS],
        "films": films(bundle),
        "optical_effects": [effect_view(i, n) for i, n in [*OPTICAL_EFFECTS, *OPTICAL_EFFECTS_V06]],
        "effect_groups": reg.GROUP_ORDER,
        "vignette_policies": ["film", "optical", "stacked", "disabled"],
        "optics_version": optics.IMPLEMENTATION_VERSION,
        "effect_order": creative.EFFECT_ORDER,
        "film_none": {"id": "none", "name": "None (no film emulation)"},
        "tone": {"brightness_ev": [-3, 3, 0], "contrast": [-1, 1, 0], "develop_strength": [0, 1, 1],
                 "filters": ["none", "grayscale", "sepia", "silver"], "filter_strength": [0, 1, 1]},
        "halation_policies": ["film", "optical", "stacked", "disabled"],
        "composites": COMPOSITES,
        "optical_presets": [{"id": "none", "name": "No optical effect", "supported": True},
                            {"id": "golden_haze", "name": "Golden Haze (composite)", "supported": "golden_haze" in SUPPORTED_EFFECTS},
                            {"id": "vintage_glass", "name": "Vintage Glass (compound: barrel + CA + edge softness + vignette)",
                             "supported": True, "expands_to": [e for e, _ in creative.PRESETS["vintage_glass"]]}],
        "output": {"formats": ["jpeg"], "color_spaces": ["srgb"], "quality": [1, 100]},
    }
