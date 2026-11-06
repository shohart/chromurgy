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
