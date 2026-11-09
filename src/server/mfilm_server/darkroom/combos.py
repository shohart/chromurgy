# SPDX-License-Identifier: GPL-2.0-only
"""Curated Camera x Film x Optics combinations (spec v0.7, docs/35-37, contracts/v0.7/curated-combos-v07.yaml).

The 21 presets are authored data merged into the existing recipe registry: no second renderer, no
preset-specific render branch. A preset resolves into an ordinary, fully expanded recipe v2 that goes through
the same `recipe2.normalize` as a hand-made recipe, so preview, develop and PhotoPrism publishing treat it
identically.

HONEST STATE: every preset is a *proposed artistic starting point* (`status` PROPOSED_NOT_VISUALLY_VALIDATED);
nothing here claims community verification or a reviewed look. `available` only says that every film stock,
camera look and optical operator the preset needs exists in this engine and that its wave is activated;
`render_validation_state` stays NOT_VISUALLY_REVIEWED until a human signs the contact sheets off."""
from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache

from .. import core

ACTIVE_WAVE = 10                      # waves 1, 2, 3, 5 and 10 of docs/optical-engine/waves.md are implemented
VALIDATION_STATE = "NOT_VISUALLY_REVIEWED"


@lru_cache(maxsize=1)
def document() -> dict:
    return json.loads((core.REPO / "contracts" / "v0.7" / "curated-combos-v07.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _by_id() -> dict[str, dict]:
    return {p["id"]: p for p in document()["presets"]}


def is_combo_id(pid: str) -> bool:
    return pid in _by_id()


def get(pid: str) -> dict | None:
    return _by_id().get(pid)


def resolve_film(film_id: str, bundle: core.Bundle) -> tuple[str | None, str]:
    """(bundle key or None, reason). Tries the preset's own id, then every documented alias name; never substitutes."""
    from . import recipe2
    if film_id == "none":
        return "none", ""
    names = [film_id, *document().get("film_resolution_aliases", {}).get(film_id, [])]
    for n in names:
        try:
            return recipe2.resolve_film(n, bundle), ""
        except recipe2.RecipeError:
            continue
    return None, f"film {film_id!r} (aliases: {', '.join(names[1:])}) is not in this profile bundle"


def availability(p: dict, bundle: core.Bundle) -> tuple[bool, str]:
    from . import catalog
    if p["wave_required"] > ACTIVE_WAVE:
        return False, f"wave {p['wave_required']} is not activated (active: {ACTIVE_WAVE})"
    if p["camera_look"]["id"] not in catalog.SUPPORTED_LOOKS:
        return False, f"camera look {p['camera_look']['id']!r} is not implemented"
    for s in p["optical"]["stack"]:
        if s["id"] not in catalog.SUPPORTED_EFFECTS:
            return False, f"optical operator {s['id']!r} is not implemented"
    key, why = resolve_film(p["film"]["id"], bundle)
    if key is None:
        return False, why
    return True, ""


def view(p: dict, bundle: core.Bundle, *, detail: bool = False) -> dict:
    from . import optical_registry as reg
    from .optics import IMPLEMENTATION_VERSION
    ok, why = availability(p, bundle)
    film, _ = resolve_film(p["film"]["id"], bundle)
    ops = [s["id"] for s in p["optical"]["stack"]]
    out = {"id": p["id"], "version": p["version"], "name": p["name"], "category": p["category"], "scenes": p["scenes"],
           "wave_required": p["wave_required"], "available": ok, "blocked_reason": why or None,
           "recommendation": p.get("recommendation"), "best_for": p["best_for"], "avoid_when": p["avoid_when"],
           "intent": p["intent"], "notes": p.get("notes") or "", "evidence_tier": p["evidence_tier"],
           "evidence_refs": p["evidence_refs"], "status": p["status"], "render_validation_state": VALIDATION_STATE,
           "camera_look": p["camera_look"]["id"], "look_strength": p["camera_look"]["strength"],
           "film": p["film"]["id"], "film_resolved": film, "optical": ops,
           "operator_versions": {o: (IMPLEMENTATION_VERSION if o in reg.new_effects() else "legacy") for o in ops},
           "suggested_tags": p.get("suggested_tags", []),
           "optical_stack": copy.deepcopy(p["optical"].get("stack", [])),
           "optical_strength": float(p["optical"].get("strength", 1.0)),
           "halation_policy": p["optical"].get("halation_policy", "film"),
           "vignette_policy": p["optical"].get("vignette_policy") or p["optical"].get("vignetting_policy") or "film",
           "grain_scale": float(p["film"].get("grain_scale", 1.0)),
           "halation_scale": float(p["film"].get("halation_scale", 1.0)),
           "softness_scale": float(p["film"].get("softness_scale", 1.0))}
    if detail:
        out["recipe_template"] = {k: copy.deepcopy(p[k]) for k in ("camera_look", "film", "optical", "render")}
        out["seed_policy"] = p.get("seed_policy")
        out["evidence"] = {r: document()["evidence_sources"].get(r) for r in p["evidence_refs"]}
    return out


def list_view(bundle: core.Bundle, *, scene: str = "", category: str = "", available: bool | None = None,
              wave: int | None = None, q: str = "") -> list[dict]:
    """Cards in the Web Darkroom order: general-purpose presets first, experiments after (docs/37 acceptance 1)."""
    rank = {"recommended": 0, "optional": 1, "experimental": 2}
    items = []
    for p in document()["presets"]:
        v = view(p, bundle)
        if scene and scene.lower() not in [s.lower() for s in p["scenes"]]:
            continue
        if category and category.lower() != p["category"].lower():
            continue
        if available is not None and v["available"] != available:
            continue
        if wave is not None and p["wave_required"] != wave:
            continue
        if q:
            hay = " ".join([p["name"], p["category"], p["best_for"], p["intent"], *p["scenes"], *p.get("suggested_tags", [])]).lower()
            if q.lower() not in hay:
                continue
        items.append(v)
    items.sort(key=lambda v: (rank.get(v["recommendation"] or "", 1), v["wave_required"]))
    return items


def derive_seed(source_digest: str, preset_id: str, version: str, variation: int = 0) -> int:
    """docs/35: sha256(source_digest | preset_id | preset_version | user_variation), first 31 bits."""
    h = hashlib.sha256(f"{source_digest}|{preset_id}|{version}|{int(variation)}".encode()).digest()
    return int.from_bytes(h[:4], "big") & 0x7FFFFFFF


class ComboError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def resolve(p: dict, bundle: core.Bundle, *, source_digest: str = "", overrides: dict | None = None,
            variation: int = 0, seed: int | None = None) -> dict:
    """The preset as an expanded, normalized recipe v2 (+ provenance). Raises ComboError when unavailable.

    overrides: {look_strength, optical_strength, film_id, grain_scale, halation_scale, softness_scale,
                effects: {effect_id: {param: value} | {"enabled": bool}}} - everything stays editable."""
    from . import recipe2
    ok, why = availability(p, bundle)
    if not ok:
        raise ComboError("PRESET_UNAVAILABLE", why)
    ov = overrides or {}
    r = {"schema_version": 2, "preset_id": p["id"], "camera_look": copy.deepcopy(p["camera_look"]),
         "film": copy.deepcopy(p["film"]), "optical": copy.deepcopy(p["optical"]), "render": copy.deepcopy(p["render"]),
         "seed": 0}
    film_key, _ = resolve_film(r["film"]["id"], bundle)
    r["film"]["id"] = ov.get("film_id") or film_key
    if "look_strength" in ov:
        r["camera_look"]["strength"] = float(ov["look_strength"])
    for k in ("grain_scale", "halation_scale", "softness_scale"):
        if k in ov:
            r["film"][k] = float(ov[k])
    if "optical_strength" in ov:
        r["optical"]["strength"] = float(ov["optical_strength"])
    for eid, over in (ov.get("effects") or {}).items():
        item = next((s for s in r["optical"]["stack"] if s["id"] == eid), None)
        if item is None:
            raise ComboError("INVALID_OVERRIDE", f"{eid} is not part of preset {p['id']}")
        over = dict(over)
        if "enabled" in over:
            item["enabled"] = bool(over.pop("enabled"))
        item["parameters"].update(over)
    r["seed"] = int(seed) if seed is not None else derive_seed(source_digest, p["id"], p["version"], variation)
    try:
        recipe = recipe2.normalize(r, bundle)
    except recipe2.RecipeError as e:
        raise ComboError(e.code, e.detail) from None
    return {"recipe": recipe, "recipe_hash": recipe2.recipe_hash(recipe),
            "preset": {"id": p["id"], "version": p["version"], "status": p["status"], "evidence_tier": p["evidence_tier"]},
            "seed_derivation": {"explicit": seed is not None, "source_digest": source_digest or None, "variation": int(variation)},
            "overrides": ov, "render_validation_state": VALIDATION_STATE}
