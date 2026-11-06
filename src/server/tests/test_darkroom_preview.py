import io
import json
import time

import numpy as np
import pytest
from PIL import Image

from darkroom_fixtures import DNG
from mfilm_server import core
from mfilm_server.darkroom import app as dapp
from test_darkroom_api import H, client, logged, upload  # noqa: F401  (fixtures)

pytestmark = [pytest.mark.skipif(not core.lib_path().is_file(), reason="needs the built film core"),
              pytest.mark.skipif(not DNG.is_file(), reason="needs a real CHDK DNG")]


def recipe(film="portra400", seed=1, **render):
    r = {"schema_version": 2, "camera_look": {"id": "neutral", "version": "1", "strength": 1},
         "film": {"id": film}, "optical": {"preset_id": "none", "strength": 0, "stack": []},
         "render": {"output_format": "jpeg", "output_color_space": "srgb", "quality": 90}, "seed": seed}
    r["render"].update(render)
    return r


def wait(c, pid, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = c.get(f"{dapp.API}/previews/{pid}").json()
        if st["status"] in ("DONE", "FAILED", "SUPERSEDED"):
            return st
        time.sleep(0.3)
    raise AssertionError("preview timed out")


def px(c, pid):
    r = c.get(f"{dapp.API}/previews/{pid}/image")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    return np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB")).astype(float)


def test_preview_changes_with_film_and_is_cached(logged):
    src = upload(logged, DNG, "a.dng").json()["source"]["asset_id"]
    a = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "recipe": recipe("portra400"), "max_edge": 640}).json()
    sa = wait(logged, a["preview_id"])
    assert sa["status"] == "DONE" and max(sa["width"], sa["height"]) == 640 and sa["recipe_hash"] == a["recipe_hash"]
    b = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "recipe": recipe("cinestill800t"), "max_edge": 640}).json()
    assert b["recipe_hash"] != a["recipe_hash"] and b["preview_id"] != a["preview_id"]
    wait(logged, b["preview_id"])
    diff = np.abs(px(logged, a["preview_id"]) - px(logged, b["preview_id"])).mean()
    assert diff > 3, f"two different films gave the same picture (mean abs diff {diff})"
    again = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "recipe": recipe("portra400"), "max_edge": 640}).json()
    assert again["preview_id"] == a["preview_id"] and again["status"] == "DONE"      # same recipe: served from cache
    # the neutral 'before' is a different, film-free picture of the same frame
    bf = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "kind": "before", "max_edge": 640}).json()
    wait(logged, bf["preview_id"])
    assert np.abs(px(logged, bf["preview_id"]) - px(logged, a["preview_id"])).mean() > 3


def test_unknown_look_is_refused_not_ignored(logged):
    src = upload(logged, DNG, "a.dng").json()["source"]["asset_id"]
    r = recipe()
    r["camera_look"]["id"] = "made_up_cam"
    resp = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "recipe": r})
    assert resp.status_code == 422 and resp.json()["error_code"] == "UNKNOWN_CAMERA_LOOK"
    assert logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": "nope", "recipe": recipe()}).status_code == 404
    assert logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "recipe": recipe(), "max_edge": 10}).status_code == 422
    assert logged.get(f"{dapp.API}/previews/{'0' * 64}").status_code == 404
    assert logged.get(f"{dapp.API}/previews/..%2f..%2fetc").status_code in (404, 422)


def test_before_side_follows_the_recipe_white_balance(logged):
    src = upload(logged, DNG, "a.dng").json()["source"]["asset_id"]
    day = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "kind": "before", "max_edge": 640}).json()
    shot = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "kind": "before", "max_edge": 640,
                                                                "white_balance": "as-shot"}).json()
    assert day["preview_id"] != shot["preview_id"]          # a different baseline is a different picture
    assert logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "kind": "before",
                                                                "white_balance": "x"}).status_code == 422
    r = recipe()
    r["extensions"] = {"white_balance": "as-shot"}
    t = logged.post(f"{dapp.API}/previews", headers=H, json={"asset_id": src, "recipe": r, "max_edge": 640}).json()
    assert wait(logged, t["preview_id"])["status"] == "DONE"
    assert wait(logged, shot["preview_id"])["status"] == "DONE" and wait(logged, day["preview_id"])["status"] == "DONE"
    assert np.abs(px(logged, day["preview_id"]) - px(logged, shot["preview_id"])).mean() > 1
