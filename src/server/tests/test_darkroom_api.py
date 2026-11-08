import hashlib

import pytest
from fastapi.testclient import TestClient

from darkroom_fixtures import CR2, DNG, DNG2, NEF
from mfilm_server import core
from mfilm_server.darkroom import app as dapp
from mfilm_server.darkroom import auth

PW = "correct horse battery"
H = {"x-mfilm-csrf": "1"}

needs_core = pytest.mark.skipif(not core.lib_path().is_file(), reason="needs the built film core")
needs_dng = pytest.mark.skipif(not DNG.is_file(), reason="needs a real CHDK DNG (MFILM_TEST_DNG)")
needs_nef = pytest.mark.skipif(NEF is None or not NEF.is_file(), reason="needs a real NEF (MFILM_TEST_NEF)")


@pytest.fixture
def client(store):
    import shutil

    from mfilm_server.darkroom import engine
    if core.lib_path().is_file():                 # pre-archive the bundle: loading it costs ~6 s per fresh store
        (store.root / "bundles").mkdir(exist_ok=True)
        shutil.copy(core.bundle_path(), store.root / "bundles" / f"{engine.current_bundle().sha256}.bin")
    auth.set_password(store, PW)
    with TestClient(dapp.create_app(store)) as c:
        yield c


@pytest.fixture
def logged(client):
    r = client.post(f"{dapp.API}/login", json={"password": PW}, headers=H)
    assert r.status_code == 200, r.text
    return client


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


def test_everything_needs_a_session(client):
    for method, path in [("get", "/catalog"), ("get", "/sources"), ("post", "/sources/uploads"),
                         ("post", "/recipe/validate"), ("get", "/session")]:
        r = getattr(client, method)(dapp.API + path)
        assert r.status_code == 401, path
    assert client.get("/healthz").status_code == 200


def test_device_tokens_are_not_web_sessions(store, client):
    from mfilm_server import db, devices
    c = db.connect(store.db_path)
    tok = devices.pair(c, "cam-1")
    r = client.get(f"{dapp.API}/catalog", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


def test_login_rules(client):
    assert client.post(f"{dapp.API}/login", json={"password": "nope"}, headers=H).status_code == 401
    assert client.post(f"{dapp.API}/login", json={"password": PW}).status_code == 403     # no CSRF header
    r = client.post(f"{dapp.API}/login", json={"password": PW}, headers=H)
    assert r.status_code == 200
    ck = r.headers["set-cookie"].lower()
    assert "httponly" in ck and "samesite=strict" in ck
    assert client.get(f"{dapp.API}/session").status_code == 200
    # cookie-authenticated writes need the CSRF header
    assert client.post(f"{dapp.API}/recipe/validate", json={}).status_code == 403
    client.post(f"{dapp.API}/logout", headers=H)
    assert client.get(f"{dapp.API}/session").status_code == 401


def test_password_file_is_private_and_short_passwords_refused(store):
    with pytest.raises(ValueError):
        auth.set_password(store, "short")
    auth.set_password(store, PW)
    f = store.root / "web" / "auth.json"
    assert f.stat().st_mode & 0o777 == 0o600 and PW not in f.read_text()


@needs_core
def test_catalog_and_recipe_validation_over_http(logged):
    cat = logged.get(f"{dapp.API}/catalog").json()
    assert len(cat["films"]) == 72 and all(x["supported"] for x in cat["camera_looks"])
    ok = logged.post(f"{dapp.API}/recipe/validate", headers=H, json={
        "schema_version": 2, "camera_look": {"id": "neutral", "version": "1", "strength": 1},
        "film": {"id": "portra400"}, "optical": {"preset_id": "none", "strength": 0, "stack": []},
        "render": {"output_format": "jpeg", "output_color_space": "srgb", "quality": 90}, "seed": 1})
    assert ok.status_code == 200 and len(ok.json()["recipe_hash"]) == 64
    bad = logged.post(f"{dapp.API}/recipe/validate", headers=H, json={
        "schema_version": 2, "camera_look": {"id": "made_up_cam", "version": "1", "strength": 1},
        "film": {"id": "portra400"}, "optical": {"preset_id": "none", "strength": 0, "stack": []},
        "render": {"output_format": "jpeg", "output_color_space": "srgb", "quality": 90}, "seed": 1})
    assert bad.status_code == 422 and bad.json()["error_code"] == "UNKNOWN_CAMERA_LOOK"


@needs_dng
def test_upload_dng_in_chunks_then_duplicate_is_free(logged, store):
    r = upload(logged, DNG, "CRW_4211.DNG", chunk=3 << 20)
    assert r.status_code == 200, r.text
    src = r.json()["source"]
    assert src["format"] == "dng" and src["meta"]["model"] == "Canon PowerShot SX510 HS" and src["eligible"]
    stored = store.root / "web-originals" / src["sha256"][:2] / f"{src['sha256']}.dng"
    assert stored.read_bytes() == DNG.read_bytes() and stored.stat().st_mode & 0o222 == 0
    again = upload(logged, DNG, "other-name.dng")                 # hash declared: nothing is transferred
    assert again.json()["duplicate"] is True and again.json()["source"]["asset_id"] == src["asset_id"]
    listed = logged.get(f"{dapp.API}/sources").json()
    assert listed["total"] == 1


@needs_dng
def test_upload_resume_and_conflicts(logged):
    data = DNG.read_bytes()
    j = logged.post(f"{dapp.API}/sources/uploads", headers=H, json={"filename": "a.dng", "size_bytes": len(data)}).json()
    url = f"{dapp.API}/sources/uploads/{j['upload_id']}"
    assert logged.put(f"{url}/chunk", content=data[:1000], headers={**H, "X-Upload-Offset": "0"}).status_code == 200
    bad = logged.put(f"{url}/chunk", content=data[:10], headers={**H, "X-Upload-Offset": "5"})
    assert bad.status_code == 409 and bad.json()["next_offset"] == 1000
    assert logged.post(f"{url}/complete", headers=H).status_code == 409           # incomplete
    assert logged.get(url).json()["next_offset"] == 1000
    too_big = logged.put(f"{url}/chunk", content=data[1000:], headers={**H, "X-Upload-Offset": "1000"})
    assert too_big.status_code == 413                                            # one request is bounded
    for off in range(1000, len(data), 4 << 20):
        logged.put(f"{url}/chunk", content=data[off:off + (4 << 20)], headers={**H, "X-Upload-Offset": str(off)})
    assert logged.post(f"{url}/complete", headers=H).status_code == 200


@needs_dng
def test_rejections_keep_the_batch_going(logged, store):
    good = DNG.read_bytes()
    cases = [
        (good[:200_000], "cut.dng", "BAD_RAW"),                        # truncated
        (b"\xff\xd8\xff\xe0" + b"x" * 5000, "photo.dng", "NOT_RAW"),   # JPEG named .dng
        (good, "readme.txt", "UNSUPPORTED_EXTENSION"),
    ]
    for data, name, code in cases:
        r = upload(logged, data, name, declare_hash=False)
        assert r.status_code == 422 and r.json()["error_code"] == code, (name, r.text)
    r = upload(logged, DNG2 if DNG2.is_file() else DNG, "fine.dng")      # the batch continues
    assert r.status_code == 200
    assert not list((store.root / "incoming").glob("web-*.part"))        # rejected bytes are not kept
    bad = logged.post(f"{dapp.API}/sources/uploads", headers=H, json={"filename": "../../etc/passwd.dng", "size_bytes": 10})
    assert bad.status_code == 201                                       # name is only a label ...
    assert logged.get(f"{dapp.API}/sources/uploads/..%2Fx").status_code in (404, 422)


@needs_dng
def test_hash_mismatch_and_size_limit(logged):
    data = DNG.read_bytes()
    j = logged.post(f"{dapp.API}/sources/uploads", headers=H, json={
        "filename": "a.dng", "size_bytes": len(data), "sha256": "0" * 64}).json()
    url = f"{dapp.API}/sources/uploads/{j['upload_id']}"
    for off in range(0, len(data), 4 << 20):
        logged.put(f"{url}/chunk", content=data[off:off + (4 << 20)], headers={**H, "X-Upload-Offset": str(off)})
    r = logged.post(f"{url}/complete", headers=H)
    assert r.status_code == 422 and r.json()["error_code"] == "HASH_MISMATCH"
    big = logged.post(f"{dapp.API}/sources/uploads", headers=H, json={"filename": "a.dng", "size_bytes": 10 << 30})
    assert big.status_code == 413


@needs_nef
def test_nef_upload(logged):
    r = upload(logged, NEF, "DSC_0174.NEF")
    assert r.status_code == 200, r.text
    m = r.json()["source"]["meta"]
    assert r.json()["source"]["format"] == "nef" and m["model"] == "NIKON D5100"


@pytest.mark.skipif(not CR2.is_file(), reason="needs vendor/m-film")
def test_unsupported_raw_family_reports_reason(logged):
    r = upload(logged, CR2, "SAMPLE.DNG", declare_hash=False)
    assert r.status_code == 422 and r.json()["error_code"] in ("UNSUPPORTED_RAW", "NOT_RAW"), r.text


def test_ui_is_served_with_strict_csp(client):
    r = client.get("/darkroom")
    assert r.status_code == 200 and "default-src 'self'" in r.headers["content-security-policy"]
    assert "script-src" not in r.headers["content-security-policy"] or "unsafe-inline" not in r.headers["content-security-policy"].split("script-src")[1].split(";")[0]
    assert client.get("/darkroom/static/darkroom.js").status_code == 200
    assert client.get("/darkroom/static/..%2f..%2fapp.py").status_code == 404


@needs_dng
def test_grid_thumbnail_comes_from_the_raw_and_expired_uploads_are_dropped(logged, store):
    src = upload(logged, DNG, "a.dng").json()["source"]
    t = logged.get(f"{dapp.API}/sources/{src['asset_id']}/thumbnail")
    assert t.status_code == 200 and t.headers["content-type"] == "image/jpeg"
    from io import BytesIO

    from PIL import Image
    assert max(Image.open(BytesIO(t.content)).size) <= 320
    assert logged.get(f"{dapp.API}/sources/nope/thumbnail").status_code == 404
    # an abandoned upload expires after 24 h and stops counting against the open-upload limit
    from mfilm_server import db
    j = logged.post(f"{dapp.API}/sources/uploads", headers=H, json={"filename": "x.dng", "size_bytes": 5000}).json()
    c = db.connect(store.db_path)
    c.execute("UPDATE web_uploads SET updated_at='2020-01-01T00:00:00.000Z' WHERE id=?", (j["upload_id"],))
    logged.post(f"{dapp.API}/sources/uploads", headers=H, json={"filename": "y.dng", "size_bytes": 5000})
    st = logged.get(f"{dapp.API}/sources/uploads/{j['upload_id']}").json()
    assert st["state"] == "ABORTED" and st["error_code"] == "EXPIRED"
    assert not (store.root / "incoming" / f"web-{j['upload_id']}.part").exists()


def test_hidden_attribute_cannot_be_overridden_by_layout_rules(client):
    """Regression: `.layer { display: grid }` kept an emptied, 'hidden' crop layer on top of the stage, which then
    swallowed the pointer and froze the before/after wipe. The stylesheet must keep [hidden] absolute."""
    css = client.get("/darkroom/static/darkroom.css").text
    assert "[hidden]{display:none!important}" in css.replace(" ", "")


def test_two_pane_layout_loader_and_preset_separation_in_ui_assets(client):
    html = client.get("/darkroom").text
    css = client.get("/darkroom/static/darkroom.css").text
    js = client.get("/darkroom/static/darkroom.js").text
    assert 'id="loader"' in html
    assert ".workspace{" in css.replace(" ", "") and ".pane-right{position:sticky" in css.replace(" ", "")
    assert ".preset-card[aria-pressed=true]" in css.replace(" ", "") and ".fx-divider{" in css.replace(" ", "")
    assert "renderLiveTone" in js and "withLoading" in js and "isCompositeActive" in js
    assert "clearAssets" in js and "stepRotate" in js and "rotpreset" in js and "rotdeg" in js


def test_operator_presets_roundtrip(logged, client):
    P = f"{dapp.API}/presets"
    assert client.get(P).json()["items"] == []
    st = {"v": 1, "look": "neutral", "film": "portra400", "grain": 1.2, "fx": ["soft_sun_glow"], "fxStrength": 0.4,
          "tone": {"brightness": 0.3, "contrast": 0.1, "develop": 1, "filter": "none", "filterStrength": 1}}
    r = logged.post(P, json={"name": "Autumn soft", "state": st}, headers=H)
    assert r.status_code == 200 and r.json()["created"] and r.json()["state"] == st
    pid = r.json()["id"]
    st2 = {**st, "film": "cinestill800t"}
    r2 = logged.post(P, json={"name": "Autumn soft", "state": st2}, headers=H).json()
    assert r2["id"] == pid and not r2["created"]                       # same name: updated, not duplicated
    items = logged.get(P).json()["items"]
    assert len(items) == 1 and items[0]["state"]["film"] == "cinestill800t"
    assert logged.post(P, json={"name": "  ", "state": st}, headers=H).status_code == 422
    assert logged.post(P, json={"name": "x", "state": "nope"}, headers=H).status_code == 422
    assert logged.delete(f"{P}/{pid}", headers=H).status_code == 200
    assert logged.delete(f"{P}/{pid}", headers=H).status_code == 404
    assert logged.get(P).json()["items"] == []
