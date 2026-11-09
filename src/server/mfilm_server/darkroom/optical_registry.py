# SPDX-License-Identifier: GPL-2.0-only
"""Typed descriptors of the optical effects (spec v0.6 `contracts/v0.7/optical-effects-catalog.yaml`, loaded from
its generated JSON twin so the server needs no YAML dependency).

One registry feeds the renderer, recipe validation, the catalog API and the Web Darkroom Step 4. The six
original effects keep their historical defaults and bounds (creative_params.py / creative.PARAM_RANGE); this
module adds the new operators and their parameter bounds."""
from __future__ import annotations

import json
from functools import lru_cache

from .. import core

# numeric encodings of the enum controls (recipe parameters are numbers only, schema additionalProperties)
EXTRA_CONTROLS = {
    "analog_light_leaks": {"edge": {"default": 4, "minimum": 0, "maximum": 4, "unit": "enum_0_left_1_right_2_top_3_bottom_4_auto"}},
    "vintage_glass_barrel_distortion": {"crop_mode": {"default": 1, "minimum": 0, "maximum": 2,
                                                      "unit": "enum_0_extend_1_auto_crop_2_black_edge"}},
}
GROUP_ORDER = ["Diffusion & Glow", "Flares & Streaks", "Light & Film Artifacts", "Lens Character", "Creative Focus"]


@lru_cache(maxsize=1)
def document() -> dict:
    return json.loads((core.REPO / "contracts" / "v0.7" / "optical-effects-catalog.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def new_effects() -> dict[str, dict]:
    """id -> descriptor (name, group, wave, stage, description, tags, controls) of every operator added in v0.6."""
    out = {}
    for e in document()["effects"]:
        if e.get("origin") != "new_v0.6":
            continue
        controls = {**e["controls"], **EXTRA_CONTROLS.get(e["id"], {})}
        out[e["id"]] = {**{k: e[k] for k in ("id", "name", "group", "kind", "wave", "stage", "description") if k in e},
                        "tags": e.get("tags", []), "controls": controls}
    return out


@lru_cache(maxsize=1)
def legacy_effects() -> dict[str, dict]:
    return {e["id"]: e for e in document()["effects"] if e.get("origin") == "existing_v0.5"}


def defaults(eid: str) -> dict:
    return {n: c["default"] for n, c in new_effects()[eid]["controls"].items()}


def check_value(eid: str, name: str, v) -> str | None:
    """None when `v` is a legal value of the new effect's control, else a reason."""
    c = new_effects()[eid]["controls"][name]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return "must be a finite number"
    if not c["minimum"] <= v <= c["maximum"]:
        return f"outside {c['minimum']}..{c['maximum']}"
    unit = c.get("unit", "")
    if unit == "integer" and float(v) != int(v):
        return "must be an integer"
    if unit == "enum_4_6_8" and v not in (4, 6, 8):
        return "must be 4, 6 or 8"
    if unit.startswith("enum_0") and float(v) != int(v):
        return "must be an integer code"
    return None


def extend(effects: dict) -> None:
    """Add the new operators' defaults to creative_params.EFFECTS (called once, at import)."""
    for eid in new_effects():
        effects[eid] = defaults(eid)
