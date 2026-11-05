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
]
OPTICAL_EFFECTS = [
    ("soft_sun_glow", "Soft Sun Glow"),
    ("ricoh_hdf_diffusion", "Ricoh HDF-inspired diffusion"),
    ("black_pro_mist_like", "Black Pro-Mist-like mist"),
    ("vintage_veiling_flare", "Vintage veiling flare"),
    ("film_halation_extra", "Film halation (extra)"),
    ("orton_glow", "Orton glow"),
]
# implemented in the C core today
SUPPORTED_LOOKS = {"neutral"}
SUPPORTED_EFFECTS: set[str] = set()


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
        "camera_looks": [{"id": i, "name": n, "evidence_tier": t, "supported": i in SUPPORTED_LOOKS}
                         for i, n, t in CAMERA_LOOKS],
        "films": films(bundle),
        "optical_effects": [{"id": i, "name": n, "supported": i in SUPPORTED_EFFECTS} for i, n in OPTICAL_EFFECTS],
        "optical_presets": [{"id": "none", "name": "No optical effect", "supported": True},
                            {"id": "golden_haze", "name": "Golden Haze (composite)", "supported": "golden_haze" in SUPPORTED_EFFECTS}],
        "output": {"formats": ["jpeg"], "color_spaces": ["srgb"], "quality": [1, 100]},
    }
