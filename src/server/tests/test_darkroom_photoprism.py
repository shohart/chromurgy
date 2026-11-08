import pytest
from fastapi.testclient import TestClient

from darkroom_fixtures import DNG
from fake_photoprism import FakePhotoPrism, sha1
from mfilm_server import config as config_mod
from mfilm_server import core, db
from mfilm_server.darkroom import app as dapp
from mfilm_server.darkroom import auth
from mfilm_server.ids import sha256_file
from test_darkroom_api import H, PW
from test_darkroom_jobs import drain, job_body, renders_on_disk
from test_darkroom_preview import recipe

pytestmark = [pytest.mark.skipif(not core.lib_path().is_file(), reason="needs the built film core"),
              pytest.mark.skipif(not DNG.is_file(), reason="needs a real CHDK DNG")]
P = f"{dapp.API}/photoprism/default"


@pytest.fixture
def pp(tmp_path, store, monkeypatch):
    import shutil

    from mfilm_server.darkroom import engine
    originals = tmp_path / "originals"
    originals.mkdir()
    fake = FakePhotoPrism(originals)
    cfg = config_mod.Config()
    cfg.photoprism.originals_dir = originals
    cfg.photoprism.export_dir = originals
    conf = tmp_path / "config.toml"                               # the worker reads it through MFILM_CONFIG
    conf.write_text(f'[photoprism]\noriginals_dir = "{originals}"\nexport_dir = "{originals}"\n')
    monkeypatch.setenv("MFILM_CONFIG", str(conf))
    (store.root / "bundles").mkdir(exist_ok=True)
    shutil.copy(core.bundle_path(), store.root / "bundles" / f"{engine.current_bundle().sha256}.bin")
    auth.set_password(store, PW)
    app = dapp.create_app(store, cfg)
    app.state.pp_transport = fake
    with TestClient(app) as c:
        assert c.post(f"{dapp.API}/login", json={"password": PW}, headers=H).status_code == 200
        c.fake, c.originals = fake, originals
        yield c


def library(pp):
    f = pp.fake
    f.add_photo("p1", "trip", "IMG_1", src=DNG)
    f.add_photo("p2", "trip", "IMG_2", kind="jpeg")                    # JPEG only: no RAW
    f.add_photo("p3", "trip", "IMG_3", src=DNG, raw_missing=True)      # RAW record gone, only the sidecar JPEG
    f.add_photo("p4", "trip", "IMG_4", ext=".CR2", src=DNG)            # RAW of a family we have not verified
    f.add_album("al1", "Autumn", ["p1", "p2"])


def test_browse_albums_folders_and_eligibility(pp):
    library(pp)
    inst = pp.get(f"{dapp.API}/photoprism/instances").json()["items"][0]
    assert inst["configured"] and inst["read"]["api"] and inst["read"]["originals"] and inst["output_folder"]
    assert [a["title"] for a in pp.get(f"{P}/albums").json()["items"]] == ["Autumn"]
    assert [f["path"] for f in pp.get(f"{P}/folders").json()["items"]] == ["trip"]
    assert pp.get(f"{P}/folders", params={"parent_id": "../x"}).status_code == 400
    ph = pp.get(f"{P}/photos", params={"source_kind": "folder", "source_uid": "trip"}).json()
    by = {i["photo_uid"]: i for i in ph["items"]}
    assert by["p1"]["eligible"] and by["p1"]["raw"]["name"] == "trip/IMG_1.DNG"
    assert not by["p2"]["eligible"] and "RAW" in by["p2"]["reason"] or "not a photo" in by["p2"]["reason"]
    assert not by["p3"]["eligible"] and "RAW unavailable" in by["p3"]["reason"]    # never the sidecar JPEG
    assert not by["p4"]["eligible"] and "unsupported RAW" in by["p4"]["reason"]
    assert ph["eligible"] == 1
    assert by["p1"]["thumb_url"] and by["p1"]["thumb_hash"]
    tr = pp.get(by["p1"]["thumb_url"])
    assert tr.status_code == 200 and b"PPTHUMB:" in tr.content
    alb = pp.get(f"{P}/photos", params={"source_kind": "album", "source_uid": "al1"}).json()
    assert {i["photo_uid"] for i in alb["items"]} == {"p1", "p2"}
    assert pp.get(f"{P}/photos", params={"source_kind": "x", "source_uid": "y"}).status_code == 422
    assert pp.get(f"{dapp.API}/photoprism/other/albums").status_code == 404


def test_backend_failures_are_reported_not_hidden(pp):
    pp.fake.deny_albums = True
    r = pp.get(f"{P}/albums")
    assert r.status_code == 403 and r.json()["error_code"] == "PHOTOPRISM_PERMISSION"
    assert pp.get(f"{P}/folders").status_code == 200                  # the rest keeps working
    pp.fake.offline = True
    r = pp.get(f"{P}/folders")
    assert r.status_code == 502 and r.json()["error_code"] == "PHOTOPRISM_OFFLINE"


def test_select_snapshots_originals_and_refuses_bad_ones(pp):
    library(pp)
    f = pp.fake
    f.add_photo("p5", "trip", "IMG_5", src=DNG)
    f.photos["p5"]["Files"][0]["Hash"] = "0" * 40                       # PhotoPrism's record disagrees with the disk
    f.add_photo("p6", "trip", "IMG_6", src=DNG)
    f.photos["p6"]["Files"][0]["Name"] = "../../etc/passwd.DNG"         # traversal attempt in a hostile record
    r = pp.post(f"{P}/select", headers=H, json={"photo_uids": ["p1", "p2", "p3", "p5", "p6", "nope"],
                                               "source_kind": "folder", "source_uid": "trip"}).json()
    assert [a["asset_id"] for a in r["assets"]] == ["pp_fp1r"]
    a = r["assets"][0]
    assert a["origin"] == "photoprism" and a["meta"]["model"] == "Canon PowerShot SX510 HS"
    assert a["sha256"] == sha256_file(pp.originals / "trip" / "IMG_1.DNG")[0]
    why = {s["photo_uid"]: s["reason"] for s in r["skipped"]}
    assert set(why) == {"p2", "p3", "p5", "p6", "nope"}
    assert "differs" in why["p5"] and "not readable" in why["p6"] or "unsafe" in why["p6"]
    assert pp.get(f"{dapp.API}/sources/pp_fp1r/thumbnail").status_code == 200
    again = pp.post(f"{P}/select", headers=H, json={"all_eligible": True, "source_kind": "folder", "source_uid": "trip"}).json()
    assert [a["asset_id"] for a in again["assets"]] == ["pp_fp1r"]      # all_eligible, unchanged file is not re-hashed


def test_develop_from_photoprism_leaves_the_original_alone(pp, store):
    library(pp)
    pp.post(f"{P}/select", headers=H, json={"photo_uids": ["p1"], "source_kind": "album", "source_uid": "al1"})
    orig = pp.originals / "trip" / "IMG_1.DNG"
    before = (sha1(orig), orig.stat().st_mtime_ns)
    body = job_body(["pp_fp1r"], recipe(width=800, height=600), source={"kind": "photoprism_album", "source_uid": "al1",
                                                                      "assets": [{"asset_id": "pp_fp1r", "photoprism_photo_uid": "p1"}]})
    jid = pp.post(f"{dapp.API}/jobs", headers=H, json=body).json()["job_id"]
    res = drain(store)
    assert [r.state for r in res] == ["COMMITTED"], [(r.error_code, r.detail) for r in res]
    v = pp.get(f"{dapp.API}/jobs/{jid}").json()
    assert v["state"] == "COMPLETE" and len(renders_on_disk(store)) == 1
    assert (sha1(orig), orig.stat().st_mtime_ns) == before
    assert not [p for p in pp.originals.rglob("*") if p.is_file() and p != orig and "IMG_" not in p.name]
    # a preview of a PhotoPrism-sourced frame uses the same pipeline
    r = pp.post(f"{dapp.API}/previews", headers=H, json={"asset_id": "pp_fp1r", "recipe": recipe(), "max_edge": 640})
    assert r.status_code == 202


def test_original_changed_after_selection_fails_the_item(pp, store):
    library(pp)
    pp.post(f"{P}/select", headers=H, json={"photo_uids": ["p1"], "source_kind": "album", "source_uid": "al1"})
    jid = pp.post(f"{dapp.API}/jobs", headers=H, json=job_body(["pp_fp1r"], recipe(width=800, height=600), source={
        "kind": "photoprism_folder", "source_uid": "trip", "assets": [{"asset_id": "pp_fp1r"}]})).json()["job_id"]
    orig = pp.originals / "trip" / "IMG_1.DNG"
    data = bytearray(orig.read_bytes())
    data[-10] ^= 0xFF
    orig.write_bytes(bytes(data))                                       # someone replaced the file in the library
    drain(store)
    v = pp.get(f"{dapp.API}/jobs/{jid}").json()
    assert v["state"] == "FAILED" and v["items"][0]["error_code"] == "SOURCE_CHANGED"
    assert renders_on_disk(store) == []


# ---- publishing -------------------------------------------------------------------------------------
def publish_job(pp, store, **out):
    library(pp)
    pp.post(f"{P}/select", headers=H, json={"photo_uids": ["p1"], "source_kind": "album", "source_uid": "al1"})
    body = job_body(["pp_fp1r"], recipe(width=800, height=600), source={
        "kind": "photoprism_album", "source_uid": "al1", "assets": [{"asset_id": "pp_fp1r"}]},
        output={"format": "jpeg", "publish": True, **out})
    r = pp.post(f"{dapp.API}/jobs", headers=H, json=body)
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def run_publish(pp, store, runner=None):
    """What the worker does after developing; the fake stands in for PhotoPrism's API and indexer."""
    import subprocess

    from mfilm_server.darkroom import photoprism as ppm
    from mfilm_server.darkroom import publish
    c = db.connect(store.db_path)
    cfg = config_mod.Config().photoprism
    cfg.export_dir = pp.originals
    cfg.index_template = ["index", "{path}"]
    seen = []

    def fake_run(argv, **kw):
        seen.append(argv)
        if runner:
            runner(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")
    try:
        return publish.publish_pending(c, store, cfg, ppm.Client(cfg, transport=pp.fake), run=fake_run), seen
    finally:
        c.close()


def index_into_fake(pp):
    """The indexer: files appear as photos once 'indexed'."""
    def run(argv):
        folder = argv[-1]
        for f in (pp.originals / folder).glob("*.jpg"):
            pp.fake.photos[f"new-{f.stem}"] = {"UID": f"new-{f.stem}", "Type": "image", "Path": folder, "Name": f.stem, "Files": []}
    return run


def test_publish_to_folder_and_new_album_in_stages(pp, store):
    jid = publish_job(pp, store, create_album_name="Autumn — M-Film", photoprism_folder="M-Film/Developed/test")
    drain(store)
    v = pp.get(f"{dapp.API}/jobs/{jid}").json()
    # the worker's own pass already copied the file; this host has no PhotoPrism API configured, so it waits
    assert v["state"] == "PUBLISHING" and v["items"][0]["state"] == "INDEXING"
    s, _ = run_publish(pp, store)                            # API reachable, indexer has not run: photo not found yet
    v = pp.get(f"{dapp.API}/jobs/{jid}").json()
    it = v["items"][0]
    assert s["waiting"] == 1 and it["state"] == "INDEXING" and "not indexed" in it["publish_note"]
    out = pp.originals / it["published_path"]
    assert out.is_file() and out.name.startswith("IMG_1_portra400_") and not list(out.parent.glob(".*"))
    assert not pp.fake.albums.get("a2")
    s, seen = run_publish(pp, store, index_into_fake(pp))
    assert s["completed"] == 1 and seen == [["index", "M-Film/Developed/test"]]
    v = pp.get(f"{dapp.API}/jobs/{jid}").json()
    assert v["state"] == "COMPLETE" and v["items"][0]["photoprism_photo_uid"].startswith("new-IMG_1_portra400_")
    new_album = [a for a in pp.fake.albums.values() if a["Title"] == "Autumn — M-Film"]
    assert len(new_album) == 1 and new_album[0]["members"] == [v["items"][0]["photoprism_photo_uid"]]
    assert v["album_uid"] == new_album[0]["UID"]
    # source RAW and its album are untouched
    assert pp.fake.albums["al1"]["members"] == ["p1", "p2"]
    assert sorted(p.name for p in (pp.originals / "trip").iterdir()) == sorted(["IMG_1.DNG", "IMG_2.jpg", "IMG_3.DNG", "IMG_4.CR2"])
    # running the stage again changes nothing (idempotent): no second album, no second file
    run_publish(pp, store)
    assert len([a for a in pp.fake.albums.values() if a["Title"] == "Autumn — M-Film"]) == 1
    assert len(list(out.parent.glob("*.jpg"))) == 1


def test_publish_into_existing_album_same_as_source_album(pp, store):
    jid = publish_job(pp, store, photoprism_album_uid="al1")
    drain(store)
    run_publish(pp, store, index_into_fake(pp))
    v = pp.get(f"{dapp.API}/jobs/{jid}").json()
    uid = v["items"][0]["photoprism_photo_uid"]
    assert v["state"] == "COMPLETE" and pp.fake.albums["al1"]["members"] == ["p1", "p2", uid]   # appended, not replaced
    assert v["publish"]["folder"].startswith("M-Film/Developed/")                              # default managed folder
    assert (pp.originals / "trip" / "IMG_1.DNG").is_file()


def test_unsafe_destination_is_refused_and_photoprism_outage_keeps_the_render(pp, store):
    library(pp)
    pp.post(f"{P}/select", headers=H, json={"photo_uids": ["p1"], "source_kind": "album", "source_uid": "al1"})
    for bad in ("../outside", "/abs/path", "a/../../b", ".hidden/x"):
        r = pp.post(f"{dapp.API}/jobs", headers=H, json=job_body(["pp_fp1r"], recipe(), source={
            "kind": "photoprism_album", "assets": [{"asset_id": "pp_fp1r"}]},
            output={"format": "jpeg", "publish": True, "photoprism_folder": bad}))
        assert r.status_code == 422 and r.json()["error_code"] == "UNSAFE_PATH", (bad, r.text)
    jid = publish_job(pp, store, photoprism_folder="M-Film/Developed/out")
    drain(store)
    pp.fake.offline = True
    s, _ = run_publish(pp, store, index_into_fake(pp))
    it = pp.get(f"{dapp.API}/jobs/{jid}").json()["items"][0]
    assert it["state"] == "INDEXING" and "OFFLINE" in it["publish_note"] and it["render"]       # render safe, retry pending
    pp.fake.offline = False
    s, _ = run_publish(pp, store)
    assert pp.get(f"{dapp.API}/jobs/{jid}").json()["state"] == "COMPLETE"                      # recovered without re-rendering
    assert len(renders_on_disk(store)) == 1


# ---- camera rolls as sources, publishing a finished render later --------------------------------------
def archived_roll(store, frames=2, unverified=1):
    """A roll the camera pipeline has received: real DNG bytes archived under originals/, catalog rows in place."""
    import hashlib
    c = db.connect(store.db_path)
    c.execute("INSERT INTO devices(id) VALUES ('cam-1')")
    c.execute("INSERT INTO rolls(id, device_id, film_profile_id, profile_bundle_hash, roll_length, expected_frames, camera_state,"
              " manifest_sha256, created_at, state) VALUES ('roll-1','cam-1','portra400',?,12,?,'SEALED','m','2026-11-04T10:00:00Z','INPUTS_COMPLETE')",
              ("b" * 64, frames + unverified))
    data = DNG.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    path = store.original_path("cam-1", "roll-1", "frame-01")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    c.execute("INSERT INTO assets(sha256, bytes, mime, kind, path) VALUES (?,?,?,?,?)",
              (sha, len(data), "image/x-adobe-dng", "original_dng", str(path.relative_to(store.root))))
    aid = c.execute("SELECT id FROM assets WHERE sha256=?", (sha,)).fetchone()[0]
    for i in range(1, frames + unverified + 1):
        ok = i <= frames
        c.execute("INSERT INTO frames(id, device_id, roll_id, ordinal, capture_time, declared_sha256, declared_bytes, source_path,"
                  " original_asset_id, original_state) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (f"frame-{i:02d}", "cam-1", "roll-1", i, "2026-11-04T10:00:00Z", sha, len(data), "A/DCIM/x.DNG",
                   aid if ok else None, "VERIFIED" if ok else "DECLARED"))
    c.close()
    return sha, path


def test_rolls_are_listed_and_their_verified_frames_become_sources(pp, store):
    sha, path = archived_roll(store, frames=1, unverified=1)
    rl = pp.get(f"{dapp.API}/rolls").json()["items"]
    assert rl[0]["roll_id"] == "roll-1" and rl[0]["frames"] == 2 and rl[0]["verified"] == 1
    r = pp.post(f"{dapp.API}/rolls/select", headers=H, json={"device_id": "cam-1", "roll_id": "roll-1"}).json()
    assert [a["origin"] for a in r["assets"]] == ["camera_roll"] and r["assets"][0]["meta"]["model"] == "Canon PowerShot SX510 HS"
    assert r["skipped"][0]["ordinal"] == 2 and "not on the server" in r["skipped"][0]["reason"]
    assert pp.post(f"{dapp.API}/rolls/select", headers=H, json={"device_id": "cam-1", "roll_id": "nope"}).status_code == 404
    aid = r["assets"][0]["asset_id"]
    before = sha256_file(path)[0]
    body = job_body([aid], recipe("cinestill800t", width=800, height=600),
                    source={"kind": "mfilm_roll", "source_uid": "roll-1", "assets": [{"asset_id": aid}]})
    jid = pp.post(f"{dapp.API}/jobs", headers=H, json=body).json()["job_id"]
    drain(store)
    v = pp.get(f"{dapp.API}/jobs/{jid}").json()
    assert v["state"] == "COMPLETE" and sha256_file(path)[0] == before == sha      # the roll's own archive is untouched
    assert pp.get(f"{dapp.API}/sources/{aid}/thumbnail").status_code == 200
    bad = pp.post(f"{dapp.API}/jobs", headers=H, json=job_body([aid], recipe(), source={"kind": "upload", "assets": [{"asset_id": aid}]}))
    assert bad.status_code == 422 and bad.json()["error_code"] == "SOURCE_KIND_MISMATCH"


def test_publish_a_finished_render_later_reuses_it_and_is_idempotent(pp, store):
    library(pp)
    pp.post(f"{P}/select", headers=H, json={"photo_uids": ["p1"], "source_kind": "album", "source_uid": "al1"})
    jid = pp.post(f"{dapp.API}/jobs", headers=H, json=job_body(["pp_fp1r"], recipe(width=800, height=600), source={
        "kind": "photoprism_album", "source_uid": "al1", "assets": [{"asset_id": "pp_fp1r"}]})).json()["job_id"]
    drain(store)
    v = pp.get(f"{dapp.API}/jobs/{jid}").json()
    rid = v["items"][0]["render"]["render_id"]
    assert v["publish"] is None and not [p for p in pp.originals.rglob("*.jpg") if "IMG_1_" in p.name]       # rendered only
    dest = {"photoprism_folder": "M-Film/Developed/later", "create_album_name": "Later"}
    a = pp.post(f"{dapp.API}/renders/{rid}/publish", headers=H, json=dest)
    assert a.status_code == 202 and a.json()["created"]
    b = pp.post(f"{dapp.API}/renders/{rid}/publish", headers=H, json=dest)
    assert b.json()["job_id"] == a.json()["job_id"] and not b.json()["created"]                              # repeat: same job
    res = drain(store)
    assert [x.detail for x in res] == ["reused"] and len(renders_on_disk(store)) == 1                        # no second render
    run_publish(pp, store, index_into_fake(pp))
    done = pp.get(f"{dapp.API}/jobs/{a.json()['job_id']}").json()
    assert done["state"] == "COMPLETE" and done["items"][0]["published_path"].startswith("M-Film/Developed/later/")
    assert [x["Title"] for x in pp.fake.albums.values()].count("Later") == 1
    assert pp.post(f"{dapp.API}/renders/{'0' * 64}/publish", headers=H, json={}).status_code == 404
    assert pp.post(f"{dapp.API}/renders/{rid}/publish", headers=H, json={"photoprism_folder": "../x"}).status_code == 422


def test_photoprism_thumbnails_are_reused_and_synced_on_change(pp):
    library(pp)
    # 1. Select p1 from PhotoPrism and verify its source thumbnail reuses PhotoPrism's preview
    sel = pp.post(f"{P}/select", headers=H, json={"photo_uids": ["p1"], "source_kind": "folder", "source_uid": "trip"}).json()
    v1 = sel["assets"][0]["thumb_v"]
    t1 = pp.get(f"{dapp.API}/sources/pp_fp1r/thumbnail")
    assert t1.status_code == 200 and b":v1" in t1.content
    # 2. Simulate PhotoPrism updating the photo preview (e.g., rotation/sidecar update -> UpdatedAt advances)
    pp.fake.update_preview("p1", updated_at="2026-11-08T20:15:00Z")
    ph = pp.get(f"{P}/photos", params={"source_kind": "folder", "source_uid": "trip"}).json()
    p1_item = next(i for i in ph["items"] if i["photo_uid"] == "p1")
    assert "2026-11-08T20%3A15%3A00Z" in p1_item["thumb_url"]
    tb = pp.get(p1_item["thumb_url"])
    assert tb.status_code == 200 and b":v2" in tb.content
    # 3. Syncing workspace thumbnails or requesting the source thumbnail with sync=1 updates the cached source preview
    sync_res = pp.post(f"{P}/sync-thumbs", headers=H, json={"force": True}).json()
    assert sync_res["synced"] == 1
    v2 = sync_res["items"][0]["thumb_v"]
    assert v2 != v1
    t2 = pp.get(f"{dapp.API}/sources/pp_fp1r/thumbnail")
    assert t2.status_code == 200 and b":v2" in t2.content
    # 4. If PhotoPrism goes offline, the last synced thumbnail remains available from local cache
    pp.fake.offline = True
    t_off = pp.get(f"{dapp.API}/sources/pp_fp1r/thumbnail")
    assert t_off.status_code == 200 and b":v2" in t_off.content
