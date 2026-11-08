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
    if film_id == "none":
        return "none"                                 # no film emulation at all (Darkroom: every stage can be off)
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


def normalize(recipe: dict, bundle: core.Bundle, wb_lookup=None) -> dict:
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
    if r["film"]["id"] == "none":
        for k in ("grain_scale", "halation_scale", "softness_scale"):
            r["film"][k] = 1.0                       # nothing to scale: one identity for "no film"
    r["optical"] = _optical(r["optical"])
    wb = (r.get("extensions") or {}).get("white_balance", "daylight")
    if wb not in ("daylight", "as-shot"):
        raise RecipeError("INVALID_RECIPE", f"extensions.white_balance={wb!r}: use daylight or as-shot")
    rd = r["render"]
    if rd["output_format"] != "jpeg" or rd["output_color_space"] != "srgb":
        raise RecipeError("UNSUPPORTED_OUTPUT", f"{rd['output_format']}/{rd['output_color_space']}: only jpeg/srgb")
    ext = r.get("extensions") or {}
    _tone(ext)
    _wb_profile(ext, wb_lookup)
    if "crop" in ext:
        try:
            canon = cropping.normalize_crop(ext["crop"])
        except cropping.CropError as e:
            raise RecipeError("INVALID_CROP", str(e)) from None
        if canon:
            ext["crop"] = canon
        else:
            ext.pop("crop")                                  # the whole frame is no crop: one identity for it
    if "rotate" in ext:
        try:
            canon_rot = cropping.normalize_rotate(ext["rotate"])
        except cropping.CropError as e:
            raise RecipeError("INVALID_CROP", str(e)) from None
        if canon_rot:
            ext["rotate"] = canon_rot
        else:
            ext.pop("rotate")                                # 0° is no rotation: one identity for it
    if ext:
        r["extensions"] = ext
    else:
        r.pop("extensions", None)                            # an empty block is no block: one identity for "nothing set"
    if bool(rd.get("width")) != bool(rd.get("height")):
        raise RecipeError("INVALID_RECIPE", "render.width and render.height go together")
    return r


TONE_LIMITS = {"brightness_ev": (-3.0, 3.0, 0.0), "contrast": (-1.0, 1.0, 0.0), "develop_strength": (0.0, 1.0, 1.0),
               "filter_strength": (0.0, 1.0, 1.0)}


def _tone(ext: dict) -> None:
    """extensions.tone -> canonical (defaults dropped, 3 decimals); an all-default tone is no tone."""
    if "tone" not in ext:
        return
    t = ext["tone"]
    if not isinstance(t, dict):
        raise RecipeError("INVALID_RECIPE", "extensions.tone must be an object")
    out: dict = {}
    for k, v in t.items():
        if k == "filter":
            if v not in ("none", "grayscale", "sepia", "silver"):
                raise RecipeError("INVALID_RECIPE", f"tone.filter {v!r}: none, grayscale, sepia or silver")
            if v != "none":
                out["filter"] = v
        elif k in TONE_LIMITS:
            lo, hi, default = TONE_LIMITS[k]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                raise RecipeError("INVALID_RECIPE", f"tone.{k}={v!r} outside {lo}..{hi}")
            if round(float(v), 3) != default:
                out[k] = round(float(v), 3)
        else:
            raise RecipeError("INVALID_RECIPE", f"unknown tone setting {k!r}")
    if out.get("filter") is None:
        out.pop("filter_strength", None)             # a strength without a filter changes nothing
    if out:
        ext["tone"] = out
    else:
        ext.pop("tone")


def _wb_profile(ext: dict, lookup) -> None:
    """extensions.wb_profile: an id (built-in or imported) or a profile object -> the canonical embedded profile,
    so a later edit or deletion of the profile can never change what an old recipe means."""
    if "wb_profile" not in ext:
        return
    from . import wb
    p = ext["wb_profile"]
    try:
        if p in (None, "", "none"):
            ext.pop("wb_profile")
            return
        if isinstance(p, str):
            found = (lookup or wb.builtin)(p)
            if not found:
                raise RecipeError("UNKNOWN_WB_PROFILE", p)
            ext["wb_profile"] = wb.canonical(found)
        elif isinstance(p, dict):
            ext["wb_profile"] = wb.canonical(wb.make_profile(p.get("name") or "custom", kelvin=p.get("kelvin"),
                                                             tint=p.get("tint", 0) or 0, gains=p.get("gains"), pid=str(p.get("id") or "custom")))
        else:
            raise RecipeError("INVALID_RECIPE", "extensions.wb_profile must be an id or an object")
    except wb.WBError as e:
        raise RecipeError("INVALID_WB_PROFILE", str(e)) from None
    if abs(max(ext["wb_profile"]["gains"]) - 1) < 1e-4 and abs(min(ext["wb_profile"]["gains"]) - 1) < 1e-4:
        ext.pop("wb_profile")                        # identity gains: the same picture as no profile


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
    body = {k: v for k, v in r.items() if k not in drop}
    if look_only and body.get("extensions"):
        # brightness / contrast / strength / filter / white balance must not reshuffle the grain while a slider moves
        ext = {k: v for k, v in body["extensions"].items() if k not in ("tone", "wb_profile")}
        body = {**body, "extensions": ext} if ext else {k: v for k, v in body.items() if k != "extensions"}
    return hashlib.sha256(canonical_json(body)).hexdigest()


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
    ext = r.get("extensions") or {}
    tone = ext.get("tone") or {}
    if "brightness_ev" in tone:
        v1["exposure_compensation_ev"] = tone["brightness_ev"]
    rest = {k: v for k, v in tone.items() if k != "brightness_ev"}
    if rest:
        v1["tone"] = rest                         # absent at defaults: those render ids stay as before
    if ext.get("wb_profile"):
        v1["wb_profile"] = ext["wb_profile"]
    crop = ext.get("crop")
    if crop:
        v1["crop"] = crop                         # absent when uncropped: those render ids stay as before
    rotate = ext.get("rotate")
    if rotate:
        v1["rotate"] = rotate                     # absent when unrotated: those render ids stay as before
    if creative:                                  # absent for neutral/no-effect: those render ids stay as before
        v1["creative"] = {"version": VERSION, **creative}
    return v1


def with_crop(r: dict, crop: dict | None, rotate: float | None = None) -> dict:
    """Copy of a normalized recipe carrying this frame's crop and rotation (None/0 = unchanged)."""
    out = copy.deepcopy(r)
    ext = dict(out.get("extensions") or {})
    ext.pop("crop", None)
    c = cropping.normalize_crop(crop) if crop else None
    if c:
        ext["crop"] = c
    if rotate is not None:
        ext.pop("rotate", None)
        rot = cropping.normalize_rotate(rotate)
        if rot:
            ext["rotate"] = rot
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
