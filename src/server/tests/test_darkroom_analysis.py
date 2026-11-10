import numpy as np
import pytest
from fastapi.testclient import TestClient

from mfilm_server.darkroom import analysis
from mfilm_server.darkroom import app as dapp
from mfilm_server.darkroom import auth

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


def test_compute_auto_exposure_dark_and_bright():
    # 1. Dark uniform image (middle gray in sRGB is ~0.18 linear / ~0.46 sRGB).
    # Array of 0.05 linear (~0.23 sRGB): should require positive EV boost
    dark_lin = np.full((100, 100, 3), 0.04, dtype=np.float32)
    ev_dark = analysis.compute_auto_exposure(dark_lin)
    assert ev_dark > 1.5, f"Expected strong positive EV for dark image, got {ev_dark}"

    # 2. Bright uniform image (0.6 linear): should require negative EV compensation
    bright_lin = np.full((100, 100, 3), 0.6, dtype=np.float32)
    ev_bright = analysis.compute_auto_exposure(bright_lin)
    assert ev_bright < -1.0, f"Expected negative EV for bright image, got {ev_bright}"

    # 3. Clamping range test: extreme darkness or brightness
    extreme_dark = np.full((50, 50, 3), 0.0001, dtype=np.float32)
    assert analysis.compute_auto_exposure(extreme_dark) <= 3.0

    extreme_bright = np.full((50, 50, 3), 0.99, dtype=np.float32)
    assert analysis.compute_auto_exposure(extreme_bright) >= -3.0


def test_compute_auto_exposure_highlight_headroom():
    # Image with dark midtones but some bright highlights (2% of pixels)
    img = np.full((100, 100, 3), 0.02, dtype=np.float32)
    # Put highlights in 2% of the pixels (200 / 10000)
    img[:20, :10, :] = 0.95
    ev = analysis.compute_auto_exposure(img)
    # The headroom constraint should prevent blowing out the highlights past 0.96
    # 0.95 * 2^ev <= 0.96 => ev <= log2(0.96/0.95) ~ 0.015
    assert ev < 0.2, f"Highlight headroom failed, ev was {ev}"


def test_compute_auto_wb():
    # 1. Neutral gray image: RGB is balanced
    neutral = np.full((64, 64, 3), 0.3, dtype=np.float32)
    awb_neutral = analysis.compute_auto_wb(neutral)
    assert 4000 <= awb_neutral["kelvin"] <= 7500
    assert abs(awb_neutral["tint"]) <= 20
    assert abs(awb_neutral["gains"][0] - 1.0) < 0.1
    assert abs(awb_neutral["gains"][1] - 1.0) < 0.1
    assert abs(awb_neutral["gains"][2] - 1.0) < 0.1

    # 2. Warm image (red cast, low blue):
    warm = np.zeros((64, 64, 3), dtype=np.float32)
    warm[:, :, 0] = 0.5  # R
    warm[:, :, 1] = 0.3  # G
    warm[:, :, 2] = 0.15 # B
    awb_warm = analysis.compute_auto_wb(warm)
    # Since image is warm (excess red), auto WB needs blue boost and red attenuation:
    # gain_b should be > gain_r
    assert awb_warm["gains"][2] > awb_warm["gains"][0]

    # 3. Cool image (blue cast, low red):
    cool = np.zeros((64, 64, 3), dtype=np.float32)
    cool[:, :, 0] = 0.15 # R
    cool[:, :, 1] = 0.3  # G
    cool[:, :, 2] = 0.5  # B
    awb_cool = analysis.compute_auto_wb(cool)
    # Since image is cool, auto WB needs red boost:
    assert awb_cool["gains"][0] > awb_cool["gains"][2]


def test_analyze_image_array():
    arr = np.full((50, 50, 3), 128, dtype=np.uint8)
    res = analysis.analyze_image_array(arr, baseline_bias=0.25)
    assert "baseline_ev" in res
    assert res["baseline_ev"] == 0.25
    assert "auto_exposure_ev" in res
    assert "auto_wb" in res
    assert "kelvin" in res["auto_wb"]
    assert "tint" in res["auto_wb"]
    assert "gains" in res["auto_wb"]


import hashlib
from darkroom_fixtures import DNG

needs_dng = pytest.mark.skipif(not DNG.is_file(), reason="needs a real CHDK DNG")


def upload(c, path_or_bytes, name, *, declare_hash=True, chunk=1 << 20):
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else path_or_bytes.read_bytes()
    body = {"filename": name, "size_bytes": len(data)}
    if declare_hash:
        body["sha256"] = hashlib.sha256(data).hexdigest()
    r = c.post(f"{dapp.API}/sources/uploads", json=body, headers=H)
    if r.status_code != 201:
        return r
    j = r.json()
    if j["state"] == "COMPLETE":
        return r
    off = 0
    while off < len(data):
        piece = data[off:off + chunk]
        rr = c.put(f"{dapp.API}/sources/uploads/{j['upload_id']}/chunk", content=piece,
                   headers={**H, "X-Upload-Offset": str(off)})
        assert rr.status_code == 200, rr.text
        off = rr.json()["next_offset"]
    return c.post(f"{dapp.API}/sources/uploads/{j['upload_id']}/complete", headers=H)


@needs_dng
def test_analysis_api_endpoint(logged, store):
    r = upload(logged, DNG, "CRW_4211.DNG")
    assert r.status_code == 200, r.text
    asset_id = r.json()["source"]["asset_id"]

    # Call the analysis endpoint
    an_res = logged.get(f"{dapp.API}/sources/{asset_id}/analysis")
    assert an_res.status_code == 200, an_res.text
    data = an_res.json()
    assert "auto_exposure_ev" in data
    assert "auto_wb" in data
    assert "kelvin" in data["auto_wb"]
    assert "tint" in data["auto_wb"]
