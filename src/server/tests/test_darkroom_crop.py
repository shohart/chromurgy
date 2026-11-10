import io

import numpy as np
import pytest
from PIL import Image

from darkroom_fixtures import DNG
from mfilm_server import core
from mfilm_server.darkroom import app as dapp
from mfilm_server.darkroom import cropping, recipe2
from test_darkroom_api import H, client, logged, upload  # noqa: F401  (fixtures)
from test_darkroom_jobs import drain, job_body, renders_on_disk
from test_darkroom_preview import px, recipe, wait

CROP = {"x": 0.25, "y": 0.1, "w": 0.5, "h": 0.6}


# ---- pure ------------------------------------------------------------------------------------------
def test_crop_normalization_rules():
    assert cropping.normalize_crop(None) is None
    assert cropping.normalize_crop({"x": 0, "y": 0, "w": 1, "h": 1}) is None                  # whole frame = no crop
    assert cropping.normalize_crop({"x": 0.00001, "y": 0, "w": 0.99995, "h": 1}) is None
    assert cropping.normalize_crop({"x": 0.123456, "y": 0.2, "w": 0.5, "h": 0.5}) == {"x": 0.1235, "y": 0.2, "w": 0.5, "h": 0.5}
    assert cropping.normalize_crop({"x": -0.0001, "y": 0, "w": 0.5, "h": 0.5})["x"] == 0.0     # rounding noise at the edge is forgiven
    for bad in ({"x": 0.6, "y": 0, "w": 0.6, "h": 0.5}, {"x": 0, "y": 0, "w": 0.01, "h": 0.5}, {"x": 0, "y": 0, "w": 0.5},
                {"x": "a", "y": 0, "w": 0.5, "h": 0.5}, {"x": 0, "y": 0, "w": 0.5, "h": 0.5, "angle": 3},
                {"x": float("nan"), "y": 0, "w": 0.5, "h": 0.5}, [1, 2, 3, 4]):
        with pytest.raises(cropping.CropError):
            cropping.normalize_crop(bad)


def test_same_fractions_give_the_same_framing_at_every_resolution():
    big = np.zeros((1200, 1600, 3), np.float32)
    big[120:840, 400:1200] = 1.0                                   # exactly the CROP rectangle
    small = big[::4, ::4]
    for img in (big, small):
        out = cropping.apply_crop(img, CROP)
        assert out.min() == 1.0 and out.shape[1] / out.shape[0] == pytest.approx(0.5 * 4 / (0.6 * 3), rel=0.01)
    assert cropping.apply_crop(big, None) is big
    with pytest.raises(cropping.CropError):
        cropping.apply_crop(np.zeros((100, 100, 3), np.float32), {"x": 0, "y": 0, "w": 0.05, "h": 0.5})   # 5x50 px


def test_fit_output_orientation_and_oversize():
    from mfilm_server import develop
    # Portrait image 2000x3000
    portrait = np.zeros((3000, 2000, 3), dtype=np.float32)
    # 1. Landscape preset 3000x2000 fits rotated to 2000x3000
    res = develop.fit_output(portrait, 3000, 2000)
    assert res.shape == (3000, 2000, 3)

    # 2. Downscaled landscape preset 1500x1000 fits rotated to 1000x1500
    res2 = develop.fit_output(portrait, 1500, 1000)
    assert res2.shape == (1500, 1000, 3)

    # 3. Oversized preset 4000x3000 raises OUTPUT_LARGER_THAN_SOURCE
    with pytest.raises(develop.DevelopError) as e:
        develop.fit_output(portrait, 4000, 3000)
    assert e.value.code == "OUTPUT_LARGER_THAN_SOURCE"


def test_resolve_output_size_ladder_and_oversize():
    from mfilm_server import develop
    # Full size landscape (3000, 4000) -> fits 3000x2000 directly
    w, h, warn = develop.resolve_output_size((3000, 4000), 3000, 2000)
    assert (w, h, warn) == (3000, 2000, None)

    # Full size portrait (4000, 3000) -> fits 3000x2000 as 2000x3000
    w, h, warn = develop.resolve_output_size((4000, 3000), 3000, 2000)
    assert (w, h, warn) == (2000, 3000, None)

    # Cropped frame (1600, 2400) requested 3000x2000 -> falls back to 2000x1333 with warning
    w, h, warn = develop.resolve_output_size((1600, 2400), 3000, 2000)
    assert (w, h) == (2000, 1333)
    assert warn is not None and "2000×1333" in warn

    # Cropped frame (1200, 1800) requested 3000x2000 -> falls back to 1600x1200 with warning
    w, h, warn = develop.resolve_output_size((1200, 1800), 3000, 2000)
    assert (w, h) == (1600, 1200)
    assert warn is not None and "1600×1200" in warn

    # Extremely cropped frame (600, 800) requested 3000x2000 -> falls back to original (0, 0) with warning
    w, h, warn = develop.resolve_output_size((600, 800), 3000, 2000)
    assert (w, h) == (0, 0)
    assert warn is not None and "native size" in warn

    # Oversized non-preset request (9000x6000) -> raises OUTPUT_LARGER_THAN_SOURCE
    with pytest.raises(develop.DevelopError) as e:
        develop.resolve_output_size((3000, 4000), 9000, 6000)
    assert e.value.code == "OUTPUT_LARGER_THAN_SOURCE"



def test_recipe_carries_the_crop_and_a_crop_changes_identity():
    from mfilm_server.darkroom import engine
    b = engine.current_bundle()
    r = recipe2.default("portra400", b)
    plain = recipe2.to_v1(r)
    assert "crop" not in plain                                      # uncropped renders keep their old ids
    c = recipe2.with_crop(r, CROP)
    assert recipe2.to_v1(c)["crop"] == CROP and recipe2.recipe_hash(c) != recipe2.recipe_hash(r)
    assert recipe2.recipe_hash(recipe2.with_crop(c, {"x": 0, "y": 0, "w": 1, "h": 1})) == recipe2.recipe_hash(r)
    bad = recipe2.default("portra400", b)
    bad["extensions"] = {"crop": {"x": 0.9, "y": 0, "w": 0.5, "h": 0.5}}
    with pytest.raises(recipe2.RecipeError) as e:
        recipe2.normalize(bad, b)
    assert e.value.code == "INVALID_CROP"


def test_rotate_normalization_and_geometry():
    assert cropping.normalize_rotate(None) is None
    assert cropping.normalize_rotate(0) is None
    assert cropping.normalize_rotate(360) is None
    assert cropping.normalize_rotate(90) == 90
    assert cropping.normalize_rotate(270) == -90
    assert cropping.normalize_rotate(-180) == 180
    assert cropping.normalize_rotate(3.456) == 3.46
    for bad in ("90", True, 500, -400, float("nan")):
        with pytest.raises(cropping.CropError):
            cropping.normalize_rotate(bad)
    img = np.zeros((100, 160, 3), np.float32)
    img[0, 0] = [1.0, 0.0, 0.0]
    r90 = cropping.apply_rotate(img, 90)
    assert r90.shape == (160, 100, 3) and np.allclose(r90[0, -1], [1.0, 0.0, 0.0])
    rm90 = cropping.apply_rotate(img, -90)
    assert rm90.shape == (160, 100, 3) and np.allclose(rm90[-1, 0], [1.0, 0.0, 0.0])
    r5 = cropping.apply_rotate(np.ones((100, 160, 3), np.float32), 5.0)
    assert r5.shape[0] < 100 and r5.shape[1] < 160 and r5.min() > 0.95
    from mfilm_server.darkroom import engine
    b = engine.current_bundle()
    r = recipe2.default("portra400", b)
    r_rot = recipe2.with_crop(r, None, rotate=90)
    assert recipe2.to_v1(r_rot)["rotate"] == 90
    assert recipe2.recipe_hash(r_rot) != recipe2.recipe_hash(r)
    assert recipe2.recipe_hash(recipe2.with_crop(r_rot, None, rotate=0)) == recipe2.recipe_hash(r)


# ---- through the service --------------------------------------------------------------------------
pytestmark_real = [pytest.mark.skipif(not core.lib_path().is_file(), reason="needs the built film core"),
                   pytest.mark.skipif(not DNG.is_file(), reason="needs a real CHDK DNG")]


@pytest.mark.skipif(not core.lib_path().is_file() or not DNG.is_file(), reason="needs core and a real DNG")
def test_preview_before_and_treated_share_the_framing(logged):
    src = upload(logged, DNG, "a.dng").json()["source"]["asset_id"]
    full = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "kind": "before", "max_edge": 640, "stream": "a"}).json()
    crop = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "kind": "before", "max_edge": 640, "crop": CROP, "stream": "b"}).json()
    assert full["preview_id"] != crop["preview_id"]
    sf, sc = wait(logged, full["preview_id"]), wait(logged, crop["preview_id"])
    assert sf["status"] == sc["status"] == "DONE"
    assert (sf["width"], sf["height"]) == (640, 480)
    assert sc["width"] / sc["height"] == pytest.approx(0.5 * 4 / (0.6 * 3), rel=0.02)        # 4:3 frame, 0.5 x 0.6 of it
    r = recipe()
    r["extensions"] = {"crop": CROP}
    t = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "recipe": r, "max_edge": 640, "stream": "c"}).json()
    st = wait(logged, t["preview_id"])
    assert (st["width"], st["height"]) == (sc["width"], sc["height"])                         # the wipe's two sides line up
    bad = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "kind": "before", "crop": {"x": 2, "y": 0, "w": 1, "h": 1}})
    assert bad.status_code == 422 and bad.json()["error_code"] == "INVALID_CROP"


@pytest.mark.skipif(not core.lib_path().is_file() or not DNG.is_file(), reason="needs core and a real DNG")
def test_job_crops_per_frame_renders_native_pixels_and_dedups(logged, store):
    a = upload(logged, DNG, "a.dng").json()["source"]["asset_id"]
    body = job_body([a], recipe(), source={"kind": "upload", "assets": [{"asset_id": a, "crop": CROP}]})
    jid = logged.post(f"{dapp.API}/jobs", headers=H, json=body).json()["job_id"]
    drain(store)
    v = logged.get(f"{dapp.API}/jobs/{jid}").json()
    it = v["items"][0]
    assert v["state"] == "COMPLETE" and it["crop"] == CROP
    w, h = it["render"]["width"], it["render"]["height"]
    assert w == pytest.approx(0.5 * 4000, abs=2) and h == pytest.approx(0.6 * 3000, abs=2)   # native pixels of the kept area
    im = Image.open(io.BytesIO(logged.get(f"{dapp.API}/renders/{it['render']['render_id']}/file").content))
    assert im.size == (w, h)
    side = renders_on_disk(store)[0].with_suffix(".jpg.json").read_text()
    assert '"crop"' in side
    # the same crop again: reused, no new file; no crop / another crop: a separate rendition next to it
    logged.post(f"{dapp.API}/jobs", headers=H, json=body)
    assert [x.detail for x in drain(store)] == ["reused"] and len(renders_on_disk(store)) == 1
    logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([a], recipe()))
    logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([a], recipe(), source={"kind": "upload", "assets": [{"asset_id": a, "crop": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}}]}))
    drain(store)
    assert len(renders_on_disk(store)) == 3
    hist = logged.get(f"{dapp.API}/history").json()["items"]
    assert sorted((h["crop"] is not None) for h in hist) == [False, True, True]


@pytest.mark.skipif(not core.lib_path().is_file() or not DNG.is_file(), reason="needs core and a real DNG")
def test_crop_validation_in_jobs_and_publish_later_keeps_the_framing(logged, store):
    a = upload(logged, DNG, "a.dng").json()["source"]["asset_id"]
    r = logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([a], recipe(), source={
        "kind": "upload", "assets": [{"asset_id": a, "crop": {"x": 0.8, "y": 0, "w": 0.5, "h": 0.5}}]}))
    assert r.status_code == 422 and r.json()["error_code"] == "INVALID_CROP"
    jid = logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([a], recipe(), source={
        "kind": "upload", "assets": [{"asset_id": a, "crop": CROP}]})).json()["job_id"]
    drain(store)
    rid = logged.get(f"{dapp.API}/jobs/{jid}").json()["items"][0]["render"]["render_id"]
    p = logged.post(f"{dapp.API}/renders/{rid}/publish", headers=H, json={"photoprism_folder": "M-Film/Developed/crop"})
    assert p.status_code == 202
    assert [x.detail for x in drain(store)] == ["reused"]               # same cropped file, not an uncropped re-render
    assert len(renders_on_disk(store)) == 1
