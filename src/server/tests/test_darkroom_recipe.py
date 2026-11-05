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


def test_catalog_marks_unimplemented_stages(bundle):
    c = catalog.build(bundle)
    looks = {x["id"]: x["supported"] for x in c["camera_looks"]}
    assert len(looks) == 9 and looks["neutral"] and not looks["leica_m9_ccd"]
    assert {x["id"] for x in c["optical_effects"]} >= {"soft_sun_glow", "ricoh_hdf_diffusion", "orton_glow"}
    assert not any(x["supported"] for x in c["optical_effects"])
    assert len(c["films"]) == 72


def test_neutral_recipe_normalizes_and_pins_bundle(bundle):
    r = recipe2.normalize(neutral(), bundle)
    assert r["film"]["bundle_hash"] == bundle.sha256
    assert recipe2.recipe_hash(r) == recipe2.recipe_hash(recipe2.normalize(neutral(), bundle))


def test_spec_style_film_alias_resolves(bundle):
    r = neutral("kodak-portra-400")
    assert recipe2.normalize(r, bundle)["film"]["id"] == "portra400"


@pytest.mark.parametrize("code,edit", [
    ("UNSUPPORTED_CAMERA_LOOK", lambda r: r["camera_look"].update(id="leica_m9_ccd")),
    ("UNKNOWN_CAMERA_LOOK", lambda r: r["camera_look"].update(id="made_up")),
    ("UNSUPPORTED_OPTICAL_EFFECT", lambda r: r["optical"].update(
        preset_id="soft_sun_glow", strength=0.4,
        stack=[{"id": "soft_sun_glow", "enabled": True, "parameters": {"threshold": 1.0}}])),
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
