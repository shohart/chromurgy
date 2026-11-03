# SPDX-License-Identifier: GPL-2.0-only
"""Receiver API (docs/09) driven by the fake camera."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from mfilm_server import core, db, devices, worker
from mfilm_server.api import create_app
from mfilm_server.importer import find_manifests
from mfilm_server.simulator import Camera, SyncError
from test_develop import SAMPLE
from test_worker import sample_card  # noqa: F401

DEV = "sx510hs-demo-001"


@pytest.fixture
def api(store):
    client = TestClient(create_app(store))
    c = db.connect(store.db_path)
    token = devices.pair(c, DEV)
    yield client, token, c
    c.close()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_and_auth(api):
    client, token, _ = api
    assert client.get("/v1/health").json() == {"status": "ok", "protocol_major": 1}
    assert client.get("/v1/capabilities").status_code == 401
    assert client.get("/v1/capabilities", headers=auth("nope")).status_code == 403
    caps = client.get("/v1/capabilities", headers=auth(token)).json()
    assert caps["device_id"] == DEV and caps["chunk_size"] == 65536


def test_sync_is_idempotent(api, make_card, store):
    client, token, c = api
    card = make_card(frames=3)
    m = find_manifests(card)[0]
    first = Camera(client, token, card).sync_roll(m)
    assert first["finalize"] == 202 and len(first["receipts"]) == 3
    again = Camera(client, token, card).sync_roll(m)
    assert again["receipts"] == first["receipts"]
    assert again["finalize"] == 200
    assert c.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 3
    assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 3        # queued once
    roll = client.get(f"/v1/rolls/{first['roll_id']}", headers=auth(token)).json()
    assert roll["server_state"] == "INPUTS_COMPLETE"
    assert {f["original_state"] for f in roll["frames"]} == {"VERIFIED"}


def test_conflicts_and_isolation(api, make_card, store):
    client, token, c = api
    card = make_card(frames=1)
    m = find_manifests(card)[0]
    Camera(client, token, card).sync_roll(m)
    doc = json.loads(m.read_text())
    doc["film_profile_id"] = "trix400"
    r = client.put(f"/v1/rolls/{doc['roll_id']}", content=json.dumps(doc), headers=auth(token))
    assert r.status_code == 409 and r.json()["error_code"] == "MANIFEST_CONFLICT"
    other = devices.pair(c, "other-cam")
    assert client.get(f"/v1/rolls/{doc['roll_id']}", headers=auth(other)).status_code == 404
    r = client.put(f"/v1/rolls/{doc['roll_id']}", content=m.read_bytes(), headers=auth(other))
    assert r.status_code == 409 and r.json()["error_code"] == "IDENTITY_MISMATCH"
    devices.revoke(c, DEV)
    assert client.get("/v1/capabilities", headers=auth(token)).status_code == 403


def test_hash_mismatch_and_offsets(api, make_card, store):
    client, token, c = api

    def lie(doc, card):                     # the card file differs from what the manifest declares
        p = card / "DCIM" / "100CANON" / "IMG_0001.DNG"
        p.write_bytes(b"II*\x00" + b"\x01" * (doc["frames"][0]["source_size_bytes"] - 4))
    card = make_card(frames=1, mutate=lie)
    m = find_manifests(card)[0]
    with pytest.raises(SyncError, match="422"):
        Camera(client, token, card).sync_roll(m)
    doc = json.loads(m.read_text())
    fr = doc["frames"][0]
    init = client.post("/v1/uploads", headers=auth(token), json={
        "device_id": DEV, "roll_id": doc["roll_id"], "frame_id": fr["frame_id"], "media_role": "original_dng",
        "bytes": fr["source_size_bytes"], "sha256": fr["source_sha256"], "media_type": "image/x-adobe-dng"}).json()
    r = client.put(f"/v1/uploads/{init['upload_id']}/chunk", content=b"abc",
                   headers={**auth(token), "X-Upload-Offset": "7"})
    assert r.status_code == 409 and r.json()["next_offset"] == 0
    r = client.post(f"/v1/rolls/{doc['roll_id']}/finalize", headers=auth(token))
    assert r.status_code == 409 and r.json()["missing_frames"] == [fr["frame_id"]]
    bad = client.post("/v1/uploads", headers=auth(token), json={
        "device_id": DEV, "roll_id": doc["roll_id"], "frame_id": fr["frame_id"], "media_role": "original_dng",
        "bytes": 5, "sha256": "0" * 64, "media_type": "image/x-adobe-dng"})
    assert bad.status_code == 409 and bad.json()["error_code"] == "DECLARED_IDENTITY_MISMATCH"


@pytest.mark.skipif(not SAMPLE.is_file() or not core.lib_path().is_file(), reason="needs vendor + core")
def test_power_loss_resume_develop_and_return(api, sample_card, store):  # noqa: F811
    client, token, c = api
    m = find_manifests(sample_card)[0]
    cam = Camera(client, token, sample_card, chunk_limit=100)
    with pytest.raises(SyncError, match="power loss"):
        cam.sync_roll(m)
    up = c.execute("SELECT offset_bytes, declared_bytes FROM uploads").fetchone()
    assert up["offset_bytes"] == 100 * 65536 < up["declared_bytes"]
    cam2 = Camera(client, token, sample_card)
    res = cam2.sync_roll(m)
    total_chunks = -(-up["declared_bytes"] // 65536)
    assert cam2.chunks_sent == total_chunks - 100                    # resumed, not restarted
    assert res["finalize"] == 202
    assert [r.state for r in worker.run(c, store)] == ["COMMITTED"]
    got = cam2.pull_results(res["roll_id"])
    assert len(got) == 1 and got[0].parent.name == res["roll_id"]
    listed = client.get(f"/v1/rolls/{res['roll_id']}/renders", headers=auth(token)).json()
    assert hashlib.sha256(got[0].read_bytes()).hexdigest() == listed[0]["sha256"]
    assert listed[0]["width"] == 5208
    assert cam2.pull_results(res["roll_id"]) == got                  # already there, nothing re-downloaded


@pytest.mark.skipif(not SAMPLE.is_file() or not core.lib_path().is_file(), reason="needs vendor + core")
def test_camera_render_upload_and_reconciliation(api, sample_card, store, tmp_path):  # noqa: F811
    from mfilm_server import publisher
    from mfilm_server.config import PhotoPrism
    from mfilm_server.simulator import develop_offline
    client, token, c = api
    m = find_manifests(sample_card)[0]
    made = develop_offline(m, sample_card)                        # "Develop Here" on the camera
    rec_path = made[0].with_suffix(".json")
    rec = json.loads(rec_path.read_text())
    cam = Camera(client, token, sample_card)
    res = cam.sync_roll(m)
    assert list(res["camera_renders"]) == [rec["frame_id"]]
    assert res["camera_renders"][rec["frame_id"]]["asset_sha256"] == hashlib.sha256(made[0].read_bytes()).hexdigest()
    rid = rec["render"]["render_id"]
    row = c.execute("SELECT r.origin, r.state, a.kind, a.path FROM renders r JOIN assets a ON a.id=r.asset_id "
                    "WHERE r.id=?", (rid,)).fetchone()
    assert tuple(row)[:3] == ("camera", "COMMITTED", "offline_jpeg")
    assert row["path"].startswith("offline-renders/")
    side = json.loads((store.root / row["path"]).with_suffix(".jpg.json").read_text())
    assert side["developed_by"] == "camera" and side["output_width"] == 1200
    roll = client.get(f"/v1/rolls/{res['roll_id']}", headers=auth(token)).json()
    assert roll["frames"][0]["camera_render_id"] == rid
    assert roll["frames"][0]["render_id"] != rid                   # the linux canonical one is still queued
    assert cam.sync_roll(m)["camera_renders"][rec["frame_id"]]["durable"]        # replay: same receipt
    assert c.execute("SELECT COUNT(*) FROM renders WHERE origin='camera'").fetchone()[0] == 1
    # the camera's own render is listed only on request and never published
    assert client.get(f"/v1/rolls/{res['roll_id']}/renders", headers=auth(token)).json() == []
    listed = client.get(f"/v1/rolls/{res['roll_id']}/renders", params={"origin": "camera"},
                        headers=auth(token)).json()
    assert [(x["render_id"], x["width"], x["origin"]) for x in listed] == [(rid, 1200, "camera")]
    assert [r.state for r in worker.run(c, store)] == ["COMMITTED"]
    lib = tmp_path / "lib"
    lib.mkdir()
    pub = publisher.publish_roll(c, store, PhotoPrism(export_dir=lib), res["roll_id"])
    assert len(pub) == 1 and pub[0].render_id != rid


def test_camera_render_identity_is_checked(api, make_card, store):
    client, token, c = api
    card = make_card(frames=1)
    m = find_manifests(card)[0]
    Camera(client, token, card).sync_roll(m)
    doc = json.loads(m.read_text())
    fr = doc["frames"][0]
    from mfilm_server.develop import default_recipe, recipe_seed
    from mfilm_server.ids import render_id
    recipe = default_recipe(doc["film_profile_id"], doc["profile_bundle_hash"])
    recipe["recipe_id"] = doc["render_recipe_id"]
    seed = recipe_seed(recipe, DEV, doc["roll_id"], fr["frame_id"])
    good = {"render_id": render_id(original_sha256=fr["source_sha256"], recipe=recipe, film_core_version="cam-1",
                                   profile_bundle_hash=doc["profile_bundle_hash"], output_spec=recipe["output_spec"],
                                   input_normalization_version=recipe["input_normalization_version"],
                                   grain_seed=seed),
            "recipe": recipe, "film_core_version": "cam-1", "grain_seed": f"{seed:016x}",
            "output_width": 64, "output_height": 48}
    base = {"device_id": DEV, "roll_id": doc["roll_id"], "frame_id": fr["frame_id"], "media_role": "camera_render",
            "bytes": 1000, "sha256": "c" * 64, "media_type": "image/jpeg"}

    def init(**render):
        return client.post("/v1/uploads", json={**base, "render": {**good, **render}}, headers=auth(token))
    assert init(grain_seed="0" * 16).json()["error_code"] == "GRAIN_SEED_MISMATCH"
    assert init(film_core_version="cam-2").json()["error_code"] == "RENDER_IDENTITY_MISMATCH"
    assert init(recipe={**recipe, "film_profile_id": "ektar100"}).json()["error_code"] == "PROFILE_BUNDLE_MISMATCH"
    assert client.post("/v1/uploads", json=base, headers=auth(token)).status_code == 400
    assert init().status_code == 201
    # a declared JPEG that is not one is refused at complete and the session is aborted
    data = b"\xff\xd8" + b"x" * 998
    r = client.post("/v1/uploads", json={**base, "sha256": hashlib.sha256(data).hexdigest(), "render": good},
                    headers=auth(token))
    uid = r.json()["upload_id"]
    client.put(f"/v1/uploads/{uid}/chunk", content=data, headers={**auth(token), "X-Upload-Offset": "0",
                                                                   "Content-Type": "application/octet-stream"})
    r = client.post(f"/v1/uploads/{uid}/complete", headers=auth(token))
    assert r.status_code == 422 and r.json()["error_code"] == "BAD_CAMERA_RENDER"
    assert c.execute("SELECT state FROM uploads WHERE id=?", (uid,)).fetchone()[0] == "ABORTED"
    assert c.execute("SELECT COUNT(*) FROM renders WHERE origin='camera'").fetchone()[0] == 0
