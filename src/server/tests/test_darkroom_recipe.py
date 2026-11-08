import copy
import json

import pytest

from mfilm_server import core
from mfilm_server.darkroom import catalog, recipe2

EXAMPLE = core.REPO / "contracts" / "v0.5" / "render-recipe-v2.example.json"


@pytest.fixture(scope="module")
def bundle():
    from mfilm_server.darkroom import engine
    return engine.current_bundle()


def example():
    return json.loads(EXAMPLE.read_text())


def neutral(film="portra400"):
    r = example()
    r["camera_look"] = {"id": "neutral", "version": "1.0.0", "strength": 1}
    r["film"]["id"] = film
    r["optical"] = {"preset_id": "none", "strength": 0, "stack": []}
    return r


def test_catalog_lists_every_look_and_effect_as_available(bundle):
    c = catalog.build(bundle)
    looks = {x["id"]: x["supported"] for x in c["camera_looks"]}
    assert len(looks) == 9 and all(looks.values()) and "leica_m9_ccd" in looks
    assert {x["id"] for x in c["optical_effects"]} == {"soft_sun_glow", "ricoh_hdf_diffusion", "black_pro_mist_like",
                                                       "vintage_veiling_flare", "film_halation_extra", "orton_glow"}
    assert all(x["supported"] and x["defaults"] for x in c["optical_effects"])
    assert len(c["films"]) == 72 and c["effect_order"][0] == "vintage_veiling_flare"


def test_neutral_recipe_normalizes_and_pins_bundle(bundle):
    r = recipe2.normalize(neutral(), bundle)
    assert r["film"]["bundle_hash"] == bundle.sha256
    assert recipe2.recipe_hash(r) == recipe2.recipe_hash(recipe2.normalize(neutral(), bundle))


def test_spec_style_film_alias_resolves(bundle):
    r = neutral("kodak-portra-400")
    assert recipe2.normalize(r, bundle)["film"]["id"] == "portra400"


@pytest.mark.parametrize("code,edit", [
    ("UNKNOWN_CAMERA_LOOK", lambda r: r["camera_look"].update(id="made_up")),
    ("INVALID_RECIPE", lambda r: r["optical"].update(
        preset_id="soft_sun_glow", strength=0.4,
        stack=[{"id": "soft_sun_glow", "enabled": True, "parameters": {"bogus": 1.0}}])),
    ("INVALID_RECIPE", lambda r: r["optical"].update(
        preset_id="soft_sun_glow", strength=0.4,
        stack=[{"id": "soft_sun_glow", "enabled": True, "parameters": {"veil": 9.0}}])),
    ("HALATION_CONFLICT", lambda r: r["optical"].update(
        preset_id="film_halation_extra", strength=0.4, stack=[{"id": "film_halation_extra", "enabled": True, "parameters": {}}])),
    ("HALATION_CONFLICT", lambda r: r["optical"].update(preset_id="none", strength=0, halation_policy="optical", stack=[])),
    ("UNKNOWN_OPTICAL_PRESET", lambda r: r["optical"].update(preset_id="nonsense", strength=0.5, stack=[])),
    ("UNSUPPORTED_PROFILE", lambda r: r["film"].update(id="no-such-film")),
    ("UNSUPPORTED_OUTPUT", lambda r: r["render"].update(output_format="tiff")),
    ("INVALID_RECIPE", lambda r: r.pop("seed")),
    ("INVALID_RECIPE", lambda r: r["render"].pop("height")),
])
def test_rejections_are_explicit(bundle, code, edit):
    r = neutral()
    edit(r)
    with pytest.raises(recipe2.RecipeError) as e:
        recipe2.normalize(r, bundle)
    assert e.value.code == code


def test_disabled_unimplemented_effect_is_not_an_error(bundle):
    r = neutral()
    r["optical"]["stack"] = [{"id": "orton_glow", "enabled": False, "parameters": {}}]
    recipe2.normalize(r, bundle)


def test_v1_bridge_and_seed_identity(bundle):
    a = recipe2.normalize(neutral(), bundle)
    b = copy.deepcopy(a)
    b["render"].update(width=1280, height=960, quality=70)
    v1a, v1b = recipe2.to_v1(a), recipe2.to_v1(b, width=1280, height=960)
    assert v1a["recipe_id"] == v1b["recipe_id"]              # same grain seed for preview and final
    assert recipe2.recipe_hash(a) != recipe2.recipe_hash(b)
    c = copy.deepcopy(a)
    c["film"]["id"] = "cinestill800t"
    assert recipe2.to_v1(c)["recipe_id"] != v1a["recipe_id"]
    assert v1a["film_profile_id"] == "portra400" and v1a["profile_bundle_hash"] == bundle.sha256


def test_presets_expand_to_an_explicit_canonical_stack(bundle):
    r = neutral()
    r["optical"] = {"preset_id": "golden_haze", "strength": 0.75, "stack": []}
    n = recipe2.normalize(r, bundle)
    assert [e["id"] for e in n["optical"]["stack"]] == ["soft_sun_glow", "black_pro_mist_like"]      # engine order
    assert n["optical"]["stack"][0]["parameters"]["warm_shift"] == 0.18 and "radius_fraction" in n["optical"]["stack"][0]["parameters"]
    assert recipe2.recipe_hash(n) == recipe2.recipe_hash(recipe2.normalize(copy.deepcopy(n), bundle))   # idempotent
    v1 = recipe2.to_v1(n)
    assert v1["creative"]["optical"]["strength"] == 0.75 and v1["look_controls"]["halation_scale"] == 1.0


def test_no_effect_and_neutral_keep_the_old_identity(bundle):
    plain = recipe2.to_v1(recipe2.normalize(neutral(), bundle))
    assert "creative" not in plain                                    # same render ids as before this feature
    off = neutral()
    off["optical"] = {"preset_id": "soft_sun_glow", "strength": 0, "stack": []}
    assert recipe2.recipe_hash(recipe2.normalize(off, bundle)) == recipe2.recipe_hash(recipe2.normalize(neutral(), bundle))
    zero = neutral()
    zero["camera_look"] = {"id": "leica_m9_ccd", "version": "1", "strength": 0}
    assert recipe2.normalize(zero, bundle)["camera_look"]["id"] == "neutral"


def test_halation_policy_has_one_owner(bundle):
    r = neutral()
    r["optical"] = {"preset_id": "film_halation_extra", "strength": 0.35, "halation_policy": "optical", "stack": []}
    v1 = recipe2.to_v1(recipe2.normalize(r, bundle))
    assert v1["look_controls"]["halation_scale"] == 0.0 and v1["creative"]["optical"]["stack"][0]["id"] == "film_halation_extra"
    r["optical"]["halation_policy"] = "stacked"
    assert recipe2.to_v1(recipe2.normalize(r, bundle))["look_controls"]["halation_scale"] == 1.0
    d = neutral()
    d["optical"] = {"preset_id": "none", "strength": 0, "halation_policy": "disabled", "stack": []}
    assert recipe2.to_v1(recipe2.normalize(d, bundle))["look_controls"]["halation_scale"] == 0.0


def test_camera_look_and_optical_strength_up_to_two(bundle):
    r = neutral()
    r["camera_look"] = {"id": "leica_m9_ccd", "version": "1.0.0", "strength": 1.75}
    r["optical"] = {"preset_id": "soft_sun_glow", "strength": 2.0, "stack": []}
    n = recipe2.normalize(r, bundle)
    assert n["camera_look"]["strength"] == 1.75
    assert n["optical"]["strength"] == 2.0
    v1 = recipe2.to_v1(n)
    assert v1["creative"]["camera_look"]["strength"] == 1.75
    assert v1["creative"]["optical"]["strength"] == 2.0

    r_bad = neutral()
    r_bad["camera_look"]["strength"] = 2.01
    with pytest.raises(recipe2.RecipeError):
        recipe2.normalize(r_bad, bundle)

