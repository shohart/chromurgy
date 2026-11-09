import json
import numpy as np
import pytest
from fastapi.testclient import TestClient

from mfilm_server import core
from mfilm_server.darkroom import app as dapp
from mfilm_server.darkroom import auth
from mfilm_server.darkroom import engine
from mfilm_server.darkroom import combos
from mfilm_server.darkroom import optics
from mfilm_server.darkroom.recipe2 import normalize

PW = "correct horse battery"
H = {"x-mfilm-csrf": "1"}


@pytest.fixture
def client(store):
    auth.set_password(store, PW)
    with TestClient(dapp.create_app(store)) as c:
        yield c


@pytest.fixture
def logged(client):
    r = client.post(f"{dapp.API}/login", json={"password": PW}, headers=H)
    assert r.status_code == 200, r.text
    return client


def test_all_21_combos_loaded():
    doc = combos.document()
    presets = doc["presets"]
    assert len(presets) == 21
    b = engine.current_bundle()
    items = combos.list_view(b)
    assert len(items) == 21
    ids = {c["id"] for c in items}
    expected_sample = {
        "leica-portra-daylight-v07",
        "golden-haze-ii-v07",
        "classic-neg-kodak-gold-v07",
        "cinestill-neon-halo-v07",
        "anamorphic-neon-street-v07",
        "superia-vintage-glass-v07",
    }
    assert expected_sample.issubset(ids)


def test_combo_waves():
    b = engine.current_bundle()
    w1 = combos.list_view(b, wave=1)
    w2 = combos.list_view(b, wave=2)
    w3 = combos.list_view(b, wave=3)
    w5 = combos.list_view(b, wave=5)
    w10 = combos.list_view(b, wave=10)
    total_waves = len(w1) + len(w2) + len(w3) + len(w5) + len(w10)
    assert total_waves == 21


def test_seed_derivation():
    s1 = combos.derive_seed("abc", "golden-haze-ii-v07", "v0.7", 0)
    s2 = combos.derive_seed("abc", "golden-haze-ii-v07", "v0.7", 0)
    s3 = combos.derive_seed("abc", "golden-haze-ii-v07", "v0.7", 1)
    s4 = combos.derive_seed("xyz", "golden-haze-ii-v07", "v0.7", 0)
    assert s1 == s2
    assert s1 != s3
    assert s1 != s4
    assert 0 <= s1 < 2**31


def test_resolve_all_21_combos():
    b = engine.current_bundle()
    for p in combos.document()["presets"]:
        res = combos.resolve(p, b, source_digest="test_digest", variation=0)
        assert "recipe" in res
        r = res["recipe"]
        assert r["schema_version"] == 2
        assert "camera_look" in r
        assert "film" in r
        assert "optical" in r
        assert r["preset_id"] == p["id"]


def test_api_combos_list(logged):
    r = logged.get(f"{dapp.API}/combos")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["total"] == 21
    assert len(j["items"]) == 21


def test_api_combos_filter_scene(logged):
    r = logged.get(f"{dapp.API}/combos?scene=street")
    assert r.status_code == 200
    j = r.json()
    assert len(j["items"]) > 0
    for item in j["items"]:
        assert "street" in [s.lower() for s in item["scenes"]]


def test_api_combo_get_and_resolve(logged):
    cid = "leica-portra-daylight-v07"
    r = logged.get(f"{dapp.API}/combos/{cid}")
    assert r.status_code == 200
    details = r.json()
    assert details["id"] == cid
    assert details["camera_look"] == "leica_m9_ccd"

    r2 = logged.post(f"{dapp.API}/combos/{cid}/resolve", json={"source_digest": "deadbeef"}, headers=H)
    assert r2.status_code == 200
    res = r2.json()
    assert res["recipe"]["camera_look"]["id"] == "leica_m9_ccd"
    assert res["preset"]["id"] == cid


def test_detect_optical_sources_synthetic():
    img = np.zeros((100, 100, 3), dtype=np.float32)
    img[48:52, 48:52] = 5.0  # bright point source
    sources = optics.detect_sources(img, threshold=1.0, limit=4)
    assert len(sources) >= 1
    s0 = sources[0]
    assert 0.4 <= s0["x"] <= 0.6
    assert 0.4 <= s0["y"] <= 0.6
    assert s0["peak"] >= 4.0


def test_api_optical_sources_validation(logged):
    r1 = logged.post(f"{dapp.API}/optical-sources", json={}, headers=H)
    assert r1.status_code == 400
    r2 = logged.post(f"{dapp.API}/optical-sources", json={"asset_id": "nonexistent", "effect_id": "soft_sun_glow"}, headers=H)
    assert r2.status_code == 422  # soft_sun_glow is not a source-driven effect (lens_flare_ghosting and starburst_cross_screen are)
