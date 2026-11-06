# SPDX-License-Identifier: GPL-2.0-only
"""Recipe v2 (contracts/v0.5/render-recipe-v2.schema.json): validation and the
bridge to the v1 recipe the film core pipeline (develop.py) consumes.

Anything the engine cannot genuinely process is rejected with a stable code,
never ignored."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from functools import lru_cache

import jsonschema

from .. import core
from ..ids import canonical_json
from . import catalog, cropping


class RecipeError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@lru_cache(maxsize=1)
def _schema() -> dict:
    return json.loads((core.REPO / "contracts" / "v0.5" / "render-recipe-v2.schema.json").read_text())


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def resolve_film(film_id: str, bundle: core.Bundle) -> str:
    """Bundle key, or a spec-style alias ('kodak-portra-400' -> 'portra400')."""
    if film_id in bundle.keys:
        return film_id
    want = _norm(film_id)
    by_norm: dict[str, str] = {}
    for f in catalog.films(bundle):
        for n in (f["id"], f["name"], f["short"]):
            by_norm.setdefault(_norm(n), f["id"])
    if want in by_norm:
        return by_norm[want]
    raise RecipeError("UNSUPPORTED_PROFILE", f"film {film_id!r} is not in bundle {bundle.sha256[:12]}")


def normalize(recipe: dict, bundle: core.Bundle) -> dict:
    """Validated, canonical copy: film resolved to its key, bundle hash pinned."""
    try:
        jsonschema.validate(recipe, _schema())
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path) or "(root)"
        raise RecipeError("INVALID_RECIPE", f"{path}: {e.message}") from None
    r = copy.deepcopy(recipe)
    look = r["camera_look"]
    if look["id"] not in catalog.SUPPORTED_LOOKS:
        known = look["id"] in {i for i, _, _ in catalog.CAMERA_LOOKS}
        raise RecipeError("UNSUPPORTED_CAMERA_LOOK" if known else "UNKNOWN_CAMERA_LOOK",
                          f"{look['id']}: " + ("not implemented in this engine yet" if known else "not in the catalog"))
    if look["id"] == "neutral":
        look["strength"] = 1                       # neutral has no strength: one identity per rendition
    elif look["strength"] == 0:
        look["id"], look["strength"] = "neutral", 1   # a look at strength 0 is no look
    r["film"]["id"] = resolve_film(r["film"]["id"], bundle)
    film_hash = r["film"].get("bundle_hash")
    if film_hash and film_hash != bundle.sha256:
        raise RecipeError("PROFILE_BUNDLE_MISMATCH", f"recipe wants {film_hash}, available {bundle.sha256}")
    r["film"]["bundle_hash"] = bundle.sha256
    for k in ("grain_scale", "halation_scale", "softness_scale"):
        r["film"].setdefault(k, 1.0)
    r["optical"] = _optical(r["optical"])
    wb = (r.get("extensions") or {}).get("white_balance", "daylight")
    if wb not in ("daylight", "as-shot"):
        raise RecipeError("INVALID_RECIPE", f"extensions.white_balance={wb!r}: use daylight or as-shot")
    rd = r["render"]
    if rd["output_format"] != "jpeg" or rd["output_color_space"] != "srgb":
        raise RecipeError("UNSUPPORTED_OUTPUT", f"{rd['output_format']}/{rd['output_color_space']}: only jpeg/srgb")
    ext = r.get("extensions") or {}
    if "crop" in ext:
        try:
            canon = cropping.normalize_crop(ext["crop"])
        except cropping.CropError as e:
            raise RecipeError("INVALID_CROP", str(e)) from None
        if canon:
            ext["crop"] = canon
        else:
            ext.pop("crop")                                  # the whole frame is no crop: one identity for it
        r["extensions"] = ext
        if not ext:
            r.pop("extensions")
    if bool(rd.get("width")) != bool(rd.get("height")):
        raise RecipeError("INVALID_RECIPE", "render.width and render.height go together")
    return r


def _optical(opt: dict) -> dict:
    """Canonical optical block: effects expanded, every parameter explicit, engine order, halation rules."""
    from .creative import EFFECT_ORDER, PARAM_RANGE, PRESETS
    from .creative_params import EFFECTS
    known = {i for i, _ in catalog.OPTICAL_EFFECTS}
    pid, policy = opt["preset_id"], opt.get("halation_policy", "film")
    if pid != "none" and pid not in known and pid not in PRESETS:
        raise RecipeError("UNKNOWN_OPTICAL_PRESET", pid)
    items: dict[str, dict] = {}
    for s in opt["stack"]:
        if s["id"] not in known:
            raise RecipeError("UNKNOWN_OPTICAL_EFFECT", s["id"])
        if s["id"] in items:
            raise RecipeError("INVALID_RECIPE", f"optical.stack lists {s['id']} twice")
        allowed = EFFECTS[s["id"]]
        for k, v in s["parameters"].items():
            if k not in allowed:
                raise RecipeError("INVALID_RECIPE", f"{s['id']}: unknown parameter {k!r} (allowed: {', '.join(sorted(allowed))})")
            lo, hi = PARAM_RANGE[k]
            if not lo <= v <= hi:
                raise RecipeError("INVALID_RECIPE", f"{s['id']}.{k}={v} outside {lo}..{hi}")
        items[s["id"]] = {"id": s["id"], "enabled": bool(s["enabled"]), "parameters": {**allowed, **s["parameters"]}}
    if not items and pid != "none":                      # a preset name alone selects its bundle
        for eid, over in PRESETS.get(pid, [(pid, {})]):
            items[eid] = {"id": eid, "enabled": True, "parameters": {**EFFECTS[eid], **over}}
    active = [e for e in EFFECT_ORDER if e in items and items[e]["enabled"]]
    strength = opt["strength"]
    extra = "film_halation_extra" in active
    if extra and policy == "film":
        raise RecipeError("HALATION_CONFLICT", "film_halation_extra with halation_policy 'film' would apply halation twice: "
                          "use 'optical' (the effect replaces the film's halation) or 'stacked' (both, deliberately)")
    if policy == "optical" and not extra:
        raise RecipeError("HALATION_CONFLICT", "halation_policy 'optical' needs film_halation_extra enabled")
    if policy == "disabled" and extra:
        raise RecipeError("HALATION_CONFLICT", "halation_policy 'disabled' contradicts an enabled film_halation_extra")
    if not active or strength <= 0:
        return {"preset_id": "none", "strength": 0, "halation_policy": policy if policy == "disabled" else "film", "stack": []}
    return {"preset_id": pid, "strength": strength, "halation_policy": policy,
            "stack": [items[e] for e in EFFECT_ORDER if e in items]}


def recipe_hash(r: dict, *, look_only: bool = False) -> str:
    """Identity of a normalized recipe (display and cache key; preset_id is a label, not identity).
    look_only drops the render block: the creative decisions without size/quality, which is
    what the grain seed derives from, so a preview and the full render share one grain pattern."""
    drop = {"preset_id", "render"} if look_only else {"preset_id"}
    return hashlib.sha256(canonical_json({k: v for k, v in r.items() if k not in drop})).hexdigest()


def to_v1(r: dict, *, width: int = 0, height: int = 0, quality: int | None = None) -> dict:
    """The v1 recipe develop() understands. width/height 0 = native size."""
    from ..develop import INPUT_NORMALIZATION
    from .creative import VERSION
    h = recipe_hash(r, look_only=True)
    rd = r["render"]
    policy = r["optical"].get("halation_policy", "film")
    halation = 0.0 if policy in ("optical", "disabled") else r["film"]["halation_scale"]   # exactly one owner of the halation
    creative: dict = {}
    if r["camera_look"]["id"] != "neutral":
        creative["camera_look"] = {"id": r["camera_look"]["id"], "strength": r["camera_look"]["strength"]}
    if r["optical"]["stack"] and r["optical"]["strength"] > 0:
        creative["optical"] = {"strength": r["optical"]["strength"], "stack": r["optical"]["stack"]}
    v1 = {"schema_version": 1, "recipe_id": f"web2-{h[:16]}", "film_profile_id": r["film"]["id"],
            "profile_bundle_hash": r["film"]["bundle_hash"], "film_core_abi_version": core.abi_version(),
            "input_normalization_version": INPUT_NORMALIZATION,
            "white_balance_mode": (r.get("extensions") or {}).get("white_balance", "daylight"), "demosaic_mode": "reference", "exposure_compensation_ev": 0.0,
            "grain_seed_mode": "derived-per-frame", "user_seed": int(r["seed"]),
            "look_controls": {"grain_scale": r["film"]["grain_scale"], "halation_scale": halation,
                              "softness_scale": r["film"]["softness_scale"]},
            "output_spec": {"format": "image/jpeg", "colorspace": "sRGB", "width": width, "height": height,
                            "jpeg_quality": quality if quality is not None else rd["quality"],
                            "orientation_policy": "normalize-pixels"}}
    crop = (r.get("extensions") or {}).get("crop")
    if crop:
        v1["crop"] = crop                         # absent when uncropped: those render ids stay as before
    if creative:                                  # absent for neutral/no-effect: those render ids stay as before
        v1["creative"] = {"version": VERSION, **creative}
    return v1


def with_crop(r: dict, crop: dict | None) -> dict:
    """Copy of a normalized recipe carrying this frame's crop (None/whole frame = no crop)."""
    out = copy.deepcopy(r)
    ext = dict(out.get("extensions") or {})
    ext.pop("crop", None)
    c = cropping.normalize_crop(crop) if crop else None
    if c:
        ext["crop"] = c
    if ext:
        out["extensions"] = ext
    else:
        out.pop("extensions", None)
    return out


def default(film_id: str, bundle: core.Bundle) -> dict:
    return normalize({"schema_version": 2, "camera_look": {"id": "neutral", "version": "1.0.0", "strength": 1},
                      "film": {"id": film_id}, "optical": {"preset_id": "none", "strength": 0, "stack": []},
                      "render": {"output_format": "jpeg", "output_color_space": "srgb", "quality": 92},
                      "seed": 0}, bundle)
