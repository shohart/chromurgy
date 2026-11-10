# SPDX-License-Identifier: GPL-2.0-only
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from mfilm_server import core
from mfilm_server.darkroom import catalog, grades, grades_catalog, recipe2


PW = "correct horse battery"
H = {"x-mfilm-csrf": "1"}


@pytest.fixture(scope="module")
def bundle():
    from mfilm_server.darkroom import engine
    return engine.current_bundle()


@pytest.fixture
def client(store):
    import shutil
    from mfilm_server.darkroom import app as dapp, auth, engine
    if core.lib_path().is_file():
        (store.root / "bundles").mkdir(exist_ok=True)
        shutil.copy(core.bundle_path(), store.root / "bundles" / f"{engine.current_bundle().sha256}.bin")
    auth.set_password(store, PW)
    from fastapi.testclient import TestClient
    with TestClient(dapp.create_app(store)) as c:
        yield c


@pytest.fixture
def logged(client):
    from mfilm_server.darkroom import app as dapp
    r = client.post(f"{dapp.API}/login", json={"password": PW}, headers=H)
    assert r.status_code == 200, r.text
    return client


@pytest.fixture
def base_recipe(bundle):
    r = json.loads((core.REPO / "contracts" / "v0.5" / "render-recipe-v2.example.json").read_text())
    r["camera_look"] = {"id": "neutral", "version": "1.0.0", "strength": 1}
    r["film"]["id"] = "portra400"
    r["optical"] = {"preset_id": "none", "strength": 0, "stack": []}
    return recipe2.normalize(r, bundle)


def test_catalog_presets_validate_schema():
    import jsonschema
    schema_path = core.REPO / "contracts" / "creative-color-grade.schema.json"
    schema = json.loads(schema_path.read_text())

    presets = grades_catalog.CATALOG_PRESETS
    assert len(presets) == 16, f"Expected 16 starter presets, got {len(presets)}"

    vsco_presets = [p for p in presets if "VSCO" in p.get("tags", [])]
    insta_presets = [p for p in presets if "Instagram Classics" in p.get("tags", [])]

    assert len(vsco_presets) >= 6, "Expected at least 6 VSCO-inspired presets"
    assert len(insta_presets) >= 4, "Expected at least 4 Instagram Classics presets"

    for p in presets:
        jsonschema.validate(p, schema)
        assert p["id"]
        assert p["name"]
        assert p["version"] == "1.0.0"
        assert p["category"] in ["warm-matte", "vintage", "social-classics", "moody", "cinematic", "editorial", "monochrome"]
        assert p["provenance"]["classification"] in [
            "original", "community-inspired", "editorial-inspired",
            "instagram-classics-inspired", "vsco-inspired", "internal-experimental"
        ]
        assert p["enabled"] is True
        assert "parameters" in p


def test_grade_transform_produces_finite_valid_output():
    img = np.random.uniform(0.05, 0.95, (200, 300, 3)).astype(np.float32)

    for p in grades_catalog.CATALOG_PRESETS:
        out = grades.apply_grade(img, p)
        assert out.shape == img.shape
        assert out.dtype == np.float32
        assert not np.isnan(out).any()
        assert not np.isinf(out).any()
        assert out.min() >= 0.0
        assert out.max() <= 1.0


def test_matte_and_contrast_transforms():
    black_pixel = np.zeros((10, 10, 3), dtype=np.float32)

    # Warm Muted Matte lifts black floor
    p_matte = grades_catalog.get_preset("warm-muted-matte")
    out_matte = grades.apply_grade(black_pixel, p_matte)
    assert out_matte.min() > 0.05, "Matte preset should lift pure black floor"

    # Pastel Air also lifts blacks
    p_air = grades_catalog.get_preset("pastel-air")
    out_air = grades.apply_grade(black_pixel, p_air)
    assert out_air.min() > 0.08, "Pastel Air should have lifted black floor"


def test_monochrome_grades_desaturate():
    color_img = np.array([[[0.8, 0.2, 0.1], [0.1, 0.7, 0.2]],
                          [[0.2, 0.3, 0.9], [0.9, 0.8, 0.1]]], dtype=np.float32)

    p_mono = grades_catalog.get_preset("matte-monochrome-soft")
    out_mono = grades.apply_grade(color_img, p_mono)

    # For monochrome, R == G == B (within floating point delta)
    r = out_mono[..., 0]
    g = out_mono[..., 1]
    b = out_mono[..., 2]
    np.testing.assert_allclose(r, g, atol=1e-3)
    np.testing.assert_allclose(g, b, atol=1e-3)


def test_recipe_normalization_and_backward_compatibility(bundle, base_recipe):
    # 1. Old recipe without creative_color_grade validates and normalizes without change
    norm = recipe2.normalize(base_recipe, bundle)
    assert "creative_color_grade" not in norm
    v1 = recipe2.to_v1(norm)
    assert "color_grade" not in v1

    # 2. Recipe with creative_color_grade mode none
    r_none = copy.deepcopy(base_recipe)
    r_none["creative_color_grade"] = {"mode": "none"}
    norm_none = recipe2.normalize(r_none, bundle)
    assert norm_none["creative_color_grade"] == {"mode": "none"}
    v1_none = recipe2.to_v1(norm_none)
    assert "color_grade" not in v1_none

    # 3. Recipe with creative_color_grade mode preset
    r_preset = copy.deepcopy(base_recipe)
    r_preset["creative_color_grade"] = {
        "mode": "preset",
        "preset_id": "warm-muted-matte",
        "preset_version": "1.0.0",
        "overrides": {"global": {"contrast": 0.05}},
    }
    norm_preset = recipe2.normalize(r_preset, bundle)
    assert norm_preset["creative_color_grade"]["preset_id"] == "warm-muted-matte"
    v1_preset = recipe2.to_v1(norm_preset)
    assert "color_grade" in v1_preset
    assert v1_preset["color_grade"]["id"] == "warm-muted-matte"
    assert v1_preset["color_grade"]["parameters"]["global"]["contrast"] == 0.05

    # 4. Unknown preset raises RecipeError
    r_bad = copy.deepcopy(base_recipe)
    r_bad["creative_color_grade"] = {"mode": "preset", "preset_id": "nonexistent-grade"}
    with pytest.raises(recipe2.RecipeError) as excinfo:
        recipe2.normalize(r_bad, bundle)
    assert excinfo.value.code == "UNKNOWN_COLOR_GRADE"


def test_resolution_and_overrides_flow(bundle, base_recipe):
    global_grade = {
        "mode": "preset",
        "preset_id": "warm-muted-matte",
        "preset_version": "1.0.0",
        "overrides": {},
    }

    # Frame A: Inherits global
    scope_a, res_a = grades.resolve_effective_grade(global_grade, {}, "frame-A")
    assert scope_a == "inherited"
    assert res_a["id"] == "warm-muted-matte"

    # Frame B: Overridden to Pastel Air
    frame_overrides = {
        "frame-B": {
            "mode": "preset",
            "preset_id": "pastel-air",
            "preset_version": "1.0.0",
            "overrides": {},
        },
        "frame-C": {"mode": "none"},
    }
    scope_b, res_b = grades.resolve_effective_grade(global_grade, frame_overrides, "frame-B")
    assert scope_b == "individual"
    assert res_b["id"] == "pastel-air"

    # Frame C: Explicit None (disabled grading)
    scope_c, res_c = grades.resolve_effective_grade(global_grade, frame_overrides, "frame-C")
    assert scope_c == "individual"
    assert res_c is None

    # Frame D (not in overrides map): Still inherits global
    scope_d, res_d = grades.resolve_effective_grade(global_grade, frame_overrides, "frame-D")
    assert scope_d == "inherited"
    assert res_d["id"] == "warm-muted-matte"

    # Reset frame B to global
    frame_overrides.pop("frame-B")
    scope_b_reset, res_b_reset = grades.resolve_effective_grade(global_grade, frame_overrides, "frame-B")
    assert scope_b_reset == "inherited"
    assert res_b_reset["id"] == "warm-muted-matte"

    # Summary descriptor
    summary = grades.effective_grade_summary(global_grade, {"frame-C": {"mode": "none"}}, "frame-C")
    assert summary["scope"] == "individual"
    assert summary["mode"] == "none"
    assert "None (this frame)" in summary["display_label"]


def test_with_frame_overrides_in_recipe2(bundle, base_recipe):
    r = copy.deepcopy(base_recipe)
    r["creative_color_grade"] = {
        "mode": "preset",
        "preset_id": "warm-muted-matte",
        "preset_version": "1.0.0",
        "overrides": {},
    }
    r["frame_color_grade_overrides"] = {
        "asset-1": {"mode": "preset", "preset_id": "pastel-air", "preset_version": "1.0.0", "overrides": {}},
        "asset-2": {"mode": "none"},
    }

    # Inheriting frame
    res_default = recipe2.with_frame_overrides(r, {"asset_id": "asset-other"})
    assert res_default["creative_color_grade"]["preset_id"] == "warm-muted-matte"
    assert "frame_color_grade_overrides" not in res_default

    # Frame with preset override
    res_1 = recipe2.with_frame_overrides(r, {"asset_id": "asset-1"})
    assert res_1["creative_color_grade"]["preset_id"] == "pastel-air"
    assert "frame_color_grade_overrides" not in res_1

    # Frame with none override
    res_2 = recipe2.with_frame_overrides(r, {"asset_id": "asset-2"})
    assert res_2["creative_color_grade"]["mode"] == "none"
    assert "frame_color_grade_overrides" not in res_2


def test_api_color_grades_catalog_and_filter(logged):
    from mfilm_server.darkroom import app as dapp

    # List all
    r = logged.get(f"{dapp.API}/color-grades")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 16

    # Tag filter
    r_vsco = logged.get(f"{dapp.API}/color-grades?tag=VSCO")
    assert r_vsco.status_code == 200
    assert all("VSCO" in p["tags"] for p in r_vsco.json()["items"])

    # Category filter
    r_cat = logged.get(f"{dapp.API}/color-grades?category=social-classics")
    assert r_cat.status_code == 200
    assert all(p["category"] == "social-classics" for p in r_cat.json()["items"])

    # Detail
    r_item = logged.get(f"{dapp.API}/color-grades/warm-muted-matte")
    assert r_item.status_code == 200
    assert r_item.json()["name"] == "Warm Muted Matte"


def test_api_user_presets_crud_and_duplicate(logged):
    from mfilm_server.darkroom import app as dapp

    custom_preset = {
        "id": "my-custom-editorial",
        "name": "My Custom Editorial",
        "version": "1.0.0",
        "description": "Custom editorial look",
        "category": "editorial",
        "tags": ["Editorial", "Custom", "Warm"],
        "provenance": {"classification": "original", "notes": "Hand-crafted"},
        "enabled": True,
        "parameters": {
            "global": {"contrast": 0.05, "black_lift": 0.04},
            "tone_curve": {"rgb_master": [[0.0, 0.04], [1.0, 0.98]]},
            "split_toning": {"shadows": {"hue": 40, "saturation": 0.05}, "midtones": {}, "highlights": {}, "balance": 0.0},
            "hsl": {"orange": {"luminance": 0.04}},
            "skin_protection": {"enabled": True, "strength": 0.5},
        },
    }

    # 1. Create
    r_create = logged.post(f"{dapp.API}/color-grades", json=custom_preset, headers=H)
    assert r_create.status_code == 201

    # 2. Get
    r_get = logged.get(f"{dapp.API}/color-grades/my-custom-editorial")
    assert r_get.status_code == 200
    assert r_get.json()["name"] == "My Custom Editorial"

    # 3. Duplicate
    r_dup = logged.post(f"{dapp.API}/color-grades/duplicate/my-custom-editorial", headers=H)
    assert r_dup.status_code == 201
    dup_id = r_dup.json()["id"]
    assert "copy" in dup_id

    # 4. Delete custom
    r_del = logged.delete(f"{dapp.API}/color-grades/my-custom-editorial", headers=H)
    assert r_del.status_code == 200

    # 5. Prevent deleting built-in
    r_del_builtin = logged.delete(f"{dapp.API}/color-grades/warm-muted-matte", headers=H)
    assert r_del_builtin.status_code == 403


def test_api_jobs_color_grades_overrides_flow(logged, store, base_recipe):
    from mfilm_server.darkroom import app as dapp
    import uuid

    # Create dummy source and job in DB
    c = logged.app.state.store.db_path
    from mfilm_server import db
    conn = db.connect(c)
    sid1 = "src-" + uuid.uuid4().hex[:8]
    sid2 = "src-" + uuid.uuid4().hex[:8]
    conn.execute("INSERT INTO sources(id, sha256, origin, path, filename, bytes, format, eligible) "
                 "VALUES (?,?,'upload','fake1.dng','fake1.dng',1000,'dng',1)", (sid1, "sha1"*16))
    conn.execute("INSERT INTO sources(id, sha256, origin, path, filename, bytes, format, eligible) "
                 "VALUES (?,?,'upload','fake2.dng','fake2.dng',1000,'dng',1)", (sid2, "sha2"*16))

    jid = uuid.uuid4().hex
    recipe_dict = copy.deepcopy(base_recipe)
    recipe_dict["creative_color_grade"] = {"mode": "preset", "preset_id": "warm-muted-matte", "preset_version": "1.0.0", "overrides": {}}
    req_dict = {
        "schema_version": 1,
        "source": {"kind": "upload", "assets": [{"asset_id": sid1}, {"asset_id": sid2}]},
        "recipe": recipe_dict,
        "output": {"format": "jpeg", "quality": 92},
    }
    conn.execute("INSERT INTO darkroom_jobs(id, request, recipe, recipe_hash) VALUES (?,?,?,?)",
                 (jid, json.dumps(req_dict), json.dumps(recipe_dict), "dummyhash"))
    conn.commit()
    conn.close()

    # 1. AC-01: Check job color grades endpoint
    r_cg = logged.get(f"{dapp.API}/jobs/{jid}/creative-color-grades")
    assert r_cg.status_code == 200
    assert r_cg.json()["creative_color_grade"]["preset_id"] == "warm-muted-matte"

    # Both frames inherit
    eff1 = logged.get(f"{dapp.API}/jobs/{jid}/frames/{sid1}/creative-color-grade/effective")
    assert eff1.status_code == 200
    assert eff1.json()["scope"] == "inherited"
    assert eff1.json()["preset_id"] == "warm-muted-matte"

    eff2 = logged.get(f"{dapp.API}/jobs/{jid}/frames/{sid2}/creative-color-grade/effective")
    assert eff2.status_code == 200
    assert eff2.json()["scope"] == "inherited"
    assert eff2.json()["preset_id"] == "warm-muted-matte"

    # 2. AC-02: Individual override on frame 1
    r_put = logged.put(f"{dapp.API}/jobs/{jid}/frames/{sid1}/creative-color-grade",
                       json={"mode": "preset", "preset_id": "pastel-air", "preset_version": "1.0.0"},
                       headers=H)
    assert r_put.status_code == 200
    assert r_put.json()["scope"] == "individual"
    assert r_put.json()["preset_id"] == "pastel-air"

    # Frame 2 still inherits
    eff2 = logged.get(f"{dapp.API}/jobs/{jid}/frames/{sid2}/creative-color-grade/effective")
    assert eff2.json()["scope"] == "inherited"
    assert eff2.json()["preset_id"] == "warm-muted-matte"

    # 3. AC-03: Change global grade to moody-earth-portrait
    r_patch = logged.patch(f"{dapp.API}/jobs/{jid}/creative-color-grade",
                           json={"mode": "preset", "preset_id": "moody-earth-portrait", "preset_version": "1.0.0", "preserve_frame_overrides": True},
                           headers=H)
    assert r_patch.status_code == 200

    # Frame 1 keeps individual override pastel-air
    eff1_after = logged.get(f"{dapp.API}/jobs/{jid}/frames/{sid1}/creative-color-grade/effective")
    assert eff1_after.json()["scope"] == "individual"
    assert eff1_after.json()["preset_id"] == "pastel-air"

    # Frame 2 now inherits new global moody-earth-portrait
    eff2_after = logged.get(f"{dapp.API}/jobs/{jid}/frames/{sid2}/creative-color-grade/effective")
    assert eff2_after.json()["scope"] == "inherited"
    assert eff2_after.json()["preset_id"] == "moody-earth-portrait"

    # 4. AC-04: Explicit None override on frame 2
    logged.put(f"{dapp.API}/jobs/{jid}/frames/{sid2}/creative-color-grade", json={"mode": "none"}, headers=H)
    eff2_none = logged.get(f"{dapp.API}/jobs/{jid}/frames/{sid2}/creative-color-grade/effective")
    assert eff2_none.json()["scope"] == "individual"
    assert eff2_none.json()["mode"] == "none"

    # 5. AC-05: Reset frame 1 to global
    logged.delete(f"{dapp.API}/jobs/{jid}/frames/{sid1}/creative-color-grade", headers=H)
    eff1_reset = logged.get(f"{dapp.API}/jobs/{jid}/frames/{sid1}/creative-color-grade/effective")
    assert eff1_reset.json()["scope"] == "inherited"
    assert eff1_reset.json()["preset_id"] == "moody-earth-portrait"


