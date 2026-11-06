import io
import json

import numpy as np
import pytest
from PIL import Image

from darkroom_fixtures import DNG
from mfilm_server import core
from mfilm_server.darkroom import app as dapp
from mfilm_server.darkroom import recipe2, tone, wb
from test_darkroom_api import H, client, logged, upload  # noqa: F401  (fixtures)
from test_darkroom_jobs import drain, job_body, renders_on_disk
from test_darkroom_preview import px, recipe, wait

real = pytest.mark.skipif(not core.lib_path().is_file() or not DNG.is_file(), reason="needs core and a real DNG")


def bundle():
    from mfilm_server.darkroom import engine
    return engine.current_bundle()


# ---- white balance maths ------------------------------------------------------------------------------
def test_reference_daylight_changes_nothing_and_luminance_is_kept():
    assert wb.gains_for(5500) == [1.0, 1.0, 1.0]
    for k in (2000, 2856, 3200, 4200, 6500, 8000, 12000):
        g = np.array(wb.gains_for(k))
        assert g @ wb.LUMA == pytest.approx(1.0, abs=2e-3)


def test_warm_light_is_corrected_by_more_blue_and_cool_light_by_more_red():
    tung, shade = wb.gains_for(3200), wb.gains_for(8000)
    assert tung[2] > 1 > tung[0] and shade[0] > 1 > shade[2]
    assert tung[2] / tung[0] > wb.gains_for(4200)[2] / wb.gains_for(4200)[0]            # warmer light, stronger correction
    assert wb.gains_for(5500, tint=20)[1] < 1 < wb.gains_for(5500, tint=-20)[1]         # + tint = magenta = less green


def test_builtin_library_is_published_data_with_sources():
    lib = wb.builtins()
    ids = [p["id"] for p in lib]
    assert len(ids) == len(set(ids)) >= 28 and all(i.startswith("builtin:") for i in ids)
    assert all(p["source"] and 1700 <= p["kelvin"] <= 25000 and len(p["gains"]) == 3 for p in lib)
    by = {p["id"]: p for p in lib}
    assert by["builtin:nikon-sun-5200"]["kelvin"] == 5200 and by["builtin:nikon-shade-8000"]["kelvin"] == 8000
    assert by["builtin:tungsten-film-3200"]["kelvin"] == 3200 and by["builtin:cie-d65-6504"]["kelvin"] == 6504


# ---- import formats -----------------------------------------------------------------------------------
def test_import_json_csv_xmp_lrtemplate_pp3():
    j = wb.parse_import("a.json", json.dumps({"profiles": [{"name": "Studio", "kelvin": 5600, "tint": 3},
                                                           {"name": "Raw gains", "gains": [1.3, 1.0, 0.8]}]}).encode())
    assert [p["name"] for p in j] == ["Studio", "Raw gains"] and j[1]["kelvin"] is None
    csv = wb.parse_import("lights.csv", b"name,kelvin,tint\nTungsten,3200,0\nShade;8000;5\n")
    assert [(p["name"], p["kelvin"], p["tint"]) for p in csv] == [("Tungsten", 3200.0, 0.0), ("Shade", 8000.0, 5.0)]
    xmp = wb.parse_import("Cloudy.xmp", b'<x:xmpmeta><rdf:Description crs:Temperature="6500" crs:Tint="+10" crs:WhiteBalance="Custom"/></x:xmpmeta>')
    assert xmp[0]["kelvin"] == 6500 and xmp[0]["tint"] == 10 and xmp[0]["name"] == "Cloudy"
    lrt = wb.parse_import("p.lrtemplate", b's = { title = "My Warm", value = { settings = { Temperature = 7200, Tint = -5, }, }, }')
    assert lrt[0]["name"] == "My Warm" and lrt[0]["kelvin"] == 7200 and lrt[0]["tint"] == -5
    pp3 = wb.parse_import("Dusk.pp3", b"[White Balance]\nSetting=Custom\nTemperature=4100\nGreen=1.0\n")
    assert pp3[0]["kelvin"] == 4100 and abs(pp3[0]["tint"]) < 1e-6


@pytest.mark.parametrize("name,data", [
    ("x.json", b"{not json"), ("x.json", b'[{"name":"a","kelvin":50}]'), ("x.json", b'[{"name":"a","gains":[1,2]}]'),
    ("x.csv", b"just,words\n"), ("x.xmp", b'<!DOCTYPE x [<!ENTITY a "b">]><x crs:Temperature="5000"/>'),
    ("x.xmp", b"<x/>"), ("x.pp3", b"[Exposure]\nA=1\n"), ("x.exe", b"MZ"), ("x.json", b"x" * (300 * 1024))])
def test_bad_imports_are_refused_with_a_reason(name, data):
    with pytest.raises(wb.WBError):
        wb.parse_import(name, data)


def test_user_profiles_are_immutable_content_addressed_and_deletable(tmp_path):
    u = wb.UserProfiles(tmp_path)
    p = wb.parse_import("a.json", b'{"name": "Mine", "kelvin": 4300}')[0]
    a = u.add(p, "a.json")
    assert a["id"].startswith("user:mine-") and u.get(a["id"])["kelvin"] == 4300
    assert u.add(p, "a.json")["id"] == a["id"] and len(u.list()) == 1            # same profile again: same id
    assert u.get("user:../../etc/passwd") is None and u.get("builtin:x") is None
    assert u.delete(a["id"]) and u.get(a["id"]) is None and not u.delete(a["id"])


# ---- tone ---------------------------------------------------------------------------------------------
def test_contrast_curve_is_monotonic_and_filters_do_what_they_say():
    x = np.linspace(0, 1, 512, dtype=np.float32)
    for c in (-1, -0.5, 0.5, 1):
        y = tone.contrast_curve(x, c)
        assert np.all(np.diff(y) >= -1e-6) and y[0] == pytest.approx(0, abs=1e-6) and y[-1] == pytest.approx(1, abs=1e-6)
    assert tone.contrast_curve(x, 0.8)[100] < x[100] < tone.contrast_curve(x, 0.8)[400]        # steeper: darks darker, lights lighter
    assert tone.contrast_curve(x, 0) is x
    img = np.random.default_rng(1).random((20, 20, 3)).astype(np.float32)
    g = tone.tone_filter(img, "grayscale", 1.0)
    assert np.allclose(g[..., 0], g[..., 1]) and np.allclose(g[..., 1], g[..., 2])
    s = tone.tone_filter(img, "sepia", 1.0)
    assert (s[..., 0] >= s[..., 1] - 1e-6).all() and (s[..., 1] >= s[..., 2] - 1e-6).all()   # always warm-ordered
    assert np.array_equal(tone.tone_filter(img, "sepia", 0.0), img) and np.array_equal(tone.tone_filter(img, "none", 1.0), img)
    half = tone.tone_filter(img, "grayscale", 0.5)
    assert np.allclose(half, (img + g) / 2, atol=1e-5)
    # the gray is the luminance (measured in linear light), not the plain channel average
    red = np.zeros((1, 1, 3), np.float32)
    red[..., 0] = 1.0
    assert tone.tone_filter(red, "grayscale", 1.0)[0, 0, 0] == pytest.approx(tone.srgb_encode(np.array(0.2126)), abs=1e-3)


# ---- recipe -------------------------------------------------------------------------------------------
def neutral(**ext):
    r = recipe("none")
    if ext:
        r["extensions"] = ext
    return r


def test_film_none_is_a_canonical_identity_and_everything_can_be_off():
    b = bundle()
    n = recipe2.normalize(neutral(), b)
    assert n["film"]["id"] == "none" and n["film"]["grain_scale"] == 1.0
    odd = neutral()
    odd["film"].update(grain_scale=0.3, halation_scale=1.7)
    assert recipe2.recipe_hash(recipe2.normalize(odd, b)) == recipe2.recipe_hash(n)       # nothing to scale without a film
    v1 = recipe2.to_v1(n)
    assert v1["film_profile_id"] == "none" and "tone" not in v1 and "creative" not in v1 and "wb_profile" not in v1


def test_tone_is_validated_canonical_and_defaults_keep_old_ids():
    b = bundle()
    plain = recipe2.to_v1(recipe2.normalize(recipe("portra400"), b))
    t = recipe("portra400")
    t["extensions"] = {"tone": {"brightness_ev": 0, "contrast": 0.0, "develop_strength": 1, "filter": "none", "filter_strength": 1}}
    assert recipe2.to_v1(recipe2.normalize(t, b)) == plain                               # all defaults = no tone
    t["extensions"] = {"tone": {"brightness_ev": 0.5, "contrast": 0.25, "develop_strength": 0.6, "filter": "sepia", "filter_strength": 0.8}}
    v1 = recipe2.to_v1(recipe2.normalize(t, b))
    assert v1["exposure_compensation_ev"] == 0.5 and v1["tone"] == {"contrast": 0.25, "develop_strength": 0.6, "filter": "sepia", "filter_strength": 0.8}
    for bad in ({"brightness_ev": 9}, {"contrast": "x"}, {"filter": "neon"}, {"mystery": 1}, {"develop_strength": -0.1}, "nope"):
        t["extensions"] = {"tone": bad}
        with pytest.raises(recipe2.RecipeError) as e:
            recipe2.normalize(t, b)
        assert e.value.code == "INVALID_RECIPE"


def test_grain_seed_does_not_move_with_brightness_contrast_or_white_balance():
    b = bundle()
    a = recipe2.to_v1(recipe2.normalize(recipe("portra400"), b))
    t = recipe("portra400")
    t["extensions"] = {"tone": {"brightness_ev": 1, "contrast": 0.5, "filter": "sepia"}, "wb_profile": "builtin:tungsten-film-3200"}
    v = recipe2.to_v1(recipe2.normalize(t, b))
    assert v["recipe_id"] == a["recipe_id"] and v["wb_profile"]["kelvin"] == 3200
    f = recipe("cinestill800t")
    assert recipe2.to_v1(recipe2.normalize(f, b))["recipe_id"] != a["recipe_id"]           # a different film still gets its own grain


def test_wb_profile_embedding_and_errors():
    b = bundle()
    r = recipe("portra400")
    r["extensions"] = {"wb_profile": "builtin:daylight-5500"}
    assert "wb_profile" not in recipe2.to_v1(recipe2.normalize(r, b))                       # identity gains = no profile
    r["extensions"] = {"wb_profile": "builtin:nope"}
    with pytest.raises(recipe2.RecipeError) as e:
        recipe2.normalize(r, b)
    assert e.value.code == "UNKNOWN_WB_PROFILE"
    r["extensions"] = {"wb_profile": {"name": "Custom", "kelvin": 4000, "tint": 5}}
    emb = recipe2.normalize(r, b)["extensions"]["wb_profile"]
    assert emb["gains"] == wb.gains_for(4000, 5) and set(emb) == {"id", "name", "kelvin", "tint", "gains"}
    r["extensions"] = {"wb_profile": {"name": "Bad", "kelvin": 10}}
    with pytest.raises(recipe2.RecipeError) as e:
        recipe2.normalize(r, b)
    assert e.value.code == "INVALID_WB_PROFILE"


# ---- through the service ----------------------------------------------------------------------------------
@real
def test_api_lists_imports_and_deletes_profiles(logged):
    lst = logged.get(f"{dapp.API}/wb-profiles").json()
    assert len(lst["builtin"]) >= 28 and lst["imported"] == [] and ".xmp" in lst["formats"]
    r = logged.post(f"{dapp.API}/wb-profiles", params={"filename": "My Look.json"}, headers=H, content=b'{"name":"Mine","kelvin":4300,"tint":4}')
    assert r.status_code == 200
    pid = r.json()["added"][0]["id"]
    assert logged.get(f"{dapp.API}/wb-profiles").json()["imported"][0]["id"] == pid
    bad = logged.post(f"{dapp.API}/wb-profiles", params={"filename": "x.xmp"}, headers=H, content=b"<x/>")
    assert bad.status_code == 422 and bad.json()["error_code"] == "INVALID_WB_PROFILE"
    ok = logged.post(f"{dapp.API}/recipe/validate", headers=H, json={**recipe("portra400"), "extensions": {"wb_profile": pid}})
    assert ok.status_code == 200 and ok.json()["recipe"]["extensions"]["wb_profile"]["kelvin"] == 4300     # resolved and embedded
    assert logged.delete(f"{dapp.API}/wb-profiles/{pid}", headers=H).status_code == 200
    gone = logged.post(f"{dapp.API}/recipe/validate", headers=H, json={**recipe("portra400"), "extensions": {"wb_profile": pid}})
    assert gone.status_code == 422 and gone.json()["error_code"] == "UNKNOWN_WB_PROFILE"
    assert logged.delete(f"{dapp.API}/wb-profiles/builtin:nikon-sun-5200", headers=H).status_code == 404   # built-ins are not deletable


@real
def test_previews_follow_film_none_tone_filters_and_white_balance(logged):
    src = upload(logged, DNG, "a.dng").json()["source"]["asset_id"]

    def prev(stream, **ext):
        r = recipe("none")
        r["extensions"] = ext
        j = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "recipe": r, "max_edge": 640, "stream": stream}).json()
        assert wait(logged, j["preview_id"])["status"] == "DONE"
        return px(logged, j["preview_id"])
    base = prev("a")
    bright = prev("b", tone={"brightness_ev": 1.0})
    assert bright.mean() > base.mean() + 8                                                   # +1 EV is visibly brighter
    assert prev("c", tone={"contrast": 0.8}).std() > base.std()
    sep = prev("d", tone={"filter": "sepia"})
    assert (sep[..., 0] >= sep[..., 2]).mean() > 0.99 and np.abs(sep[..., 0] - sep[..., 2]).mean() > 8
    bw = prev("e", tone={"filter": "grayscale"})
    assert np.abs(bw[..., 0] - bw[..., 2]).max() <= 2
    warm = prev("f", wb_profile="builtin:tungsten-film-3200")
    assert warm[..., 2].mean() / warm[..., 0].mean() > base[..., 2].mean() / base[..., 0].mean() * 1.15   # blue lifted, red pulled
    full = recipe("portra400")
    half = recipe("portra400")
    half["extensions"] = {"tone": {"develop_strength": 0.0}}
    a = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "recipe": half, "max_edge": 640, "stream": "g"}).json()
    wait(logged, a["preview_id"])
    n = prev("h")                                                                           # film none, same exposure
    assert np.abs(px(logged, a["preview_id"]) - n).mean() < 1.0                              # strength 0 = no film at all


@real
def test_full_size_job_applies_the_same_settings_and_keeps_them_in_the_record(logged, store):
    a = upload(logged, DNG, "a.dng").json()["source"]["asset_id"]
    r = recipe("none", width=1200, height=900)
    r["extensions"] = {"tone": {"brightness_ev": 0.5, "contrast": 0.3, "filter": "sepia"}, "wb_profile": "builtin:nikon-shade-8000"}
    jid = logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([a], r)).json()["job_id"]
    drain(store)
    v = logged.get(f"{dapp.API}/jobs/{jid}").json()
    assert v["state"] == "COMPLETE" and v["film"] == "none"
    rid = v["items"][0]["render"]["render_id"]
    im = np.asarray(Image.open(io.BytesIO(logged.get(f"{dapp.API}/renders/{rid}/file").content)).convert("RGB")).astype(int)
    assert im.shape[:2] == (900, 1200) and (im[..., 0] >= im[..., 2]).mean() > 0.97          # sepia ordering survived the JPEG
    side = json.loads(renders_on_disk(store)[0].with_suffix(".jpg.json").read_text())
    assert side["tone"]["filter"] == "sepia" and side["wb_profile"]["kelvin"] == 8000 and side["film_profile_id"] == "none"
    assert side["recipe_v2"]["extensions"]["tone"]["contrast"] == 0.3
    again = logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([a], r))
    assert again.status_code == 202 and [x.detail for x in drain(store)] == ["reused"]       # same settings: no second file
    r["extensions"]["tone"]["contrast"] = 0.31
    logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([a], r))
    drain(store)
    assert len(renders_on_disk(store)) == 2                                                  # another slider value, another rendition


# ---- silver black-and-white film -------------------------------------------------------------------------
def test_silver_film_is_monochrome_film_like_and_deterministic():
    rng = np.random.default_rng(3)
    ramp = np.tile(np.linspace(0, 1, 400, dtype=np.float32)[None, :, None], (300, 1, 3))
    a = tone.silver_film(ramp, 7)
    assert np.array_equal(a, tone.silver_film(ramp, 7)) and not np.array_equal(a, tone.silver_film(ramp, 8))
    assert np.allclose(a[..., 0], a[..., 1]) and np.allclose(a[..., 1], a[..., 2]) and a.min() >= 0 and a.max() <= 1
    mean_row = a[..., 0].mean(0)
    assert mean_row[0] > 0.012 and mean_row[-1] < 0.99                                      # base fog lifts black, shoulder keeps paper below white
    assert np.all(np.diff(np.convolve(mean_row, np.ones(25) / 25, "valid")) > -1e-3)         # the tone curve stays monotonic
    flat = lambda v: tone.silver_film(np.full((200, 200, 3), v, np.float32), 5)[..., 0].std()   # noqa: E731
    assert flat(0.5) > 2.5 * flat(0.02) and flat(0.5) > 2.5 * flat(0.98)                     # grain lives in the mid-tones
    colour = rng.random((60, 60, 3)).astype(np.float32)
    red, green = np.zeros((8, 8, 3), np.float32), np.zeros((8, 8, 3), np.float32)
    red[..., 0], green[..., 1] = 0.6, 0.6
    assert tone.silver_film(green, 1).mean() > tone.silver_film(red, 1).mean()               # panchromatic: green brighter than red, both grey
    assert colour.shape == tone.silver_film(colour, 1).shape


def test_silver_grain_looks_the_same_at_any_resolution():
    big = tone.silver_grain(900, 1200, 11)
    small = tone.silver_grain(300, 400, 11)                                                  # same picture, a third of the size
    assert big.std() == pytest.approx(1.0, abs=1e-3) and small.std() == pytest.approx(1.0, abs=1e-3)
    down = np.asarray(Image.fromarray(big, "F").resize((400, 300), Image.BOX), np.float32)
    other = tone.silver_grain(300, 400, 12)
    assert np.corrcoef(down.ravel(), small.ravel())[0, 1] > 0.8                              # the same grain pattern, differently resampled
    assert abs(np.corrcoef(down.ravel(), other.ravel())[0, 1]) < 0.1                         # while another seed is another grain


def test_silver_filter_strength_and_recipe_validation():
    img = np.random.default_rng(2).random((40, 40, 3)).astype(np.float32)
    assert np.array_equal(tone.tone_filter(img, "silver", 0.0, 3), img)
    full = tone.tone_filter(img, "silver", 1.0, 3)
    half = tone.tone_filter(img, "silver", 0.5, 3)
    assert np.allclose(half, (img + full) / 2, atol=1e-5)
    t = recipe("none")
    t["extensions"] = {"tone": {"filter": "silver"}}
    assert recipe2.to_v1(recipe2.normalize(t, bundle()))["tone"] == {"filter": "silver"}


@real
def test_preview_and_full_size_render_with_silver(logged, store):
    src = upload(logged, DNG, "a.dng").json()["source"]["asset_id"]
    r = recipe("portra400", width=1200, height=900)
    r["extensions"] = {"tone": {"filter": "silver"}}
    p = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "recipe": r, "max_edge": 640}).json()
    assert wait(logged, p["preview_id"])["status"] == "DONE"
    a = px(logged, p["preview_id"])
    assert np.abs(a[..., 0] - a[..., 2]).max() <= 2                                          # no colour left
    jid = logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([src], r)).json()["job_id"]
    drain(store)
    v = logged.get(f"{dapp.API}/jobs/{jid}").json()
    assert v["state"] == "COMPLETE"
    full = np.asarray(Image.open(io.BytesIO(logged.get(f"{dapp.API}/renders/{v['items'][0]['render']['render_id']}/file").content)).convert("RGB")).astype(int)
    assert np.abs(full[..., 0] - full[..., 2]).max() <= 3 and full.shape[:2] == (900, 1200)
