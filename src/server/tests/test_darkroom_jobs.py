import io
import json

import pytest
from PIL import Image

from darkroom_fixtures import DNG, DNG2, NEF
from mfilm_server import core, db, worker
from mfilm_server.darkroom import app as dapp
from mfilm_server.ids import sha256_file
from test_darkroom_api import H, client, logged, upload  # noqa: F401  (fixtures)
from test_darkroom_preview import recipe

pytestmark = [pytest.mark.skipif(not core.lib_path().is_file(), reason="needs the built film core"),
              pytest.mark.skipif(not DNG.is_file(), reason="needs a real CHDK DNG")]


def job_body(ids, rec=None, **over):
    b = {"schema_version": 1, "source": {"kind": "upload", "assets": [{"asset_id": i} for i in ids]},
         "recipe": rec or recipe(), "output": {"format": "jpeg", "publish": False}}
    b.update(over)
    return b


def drain(store):
    """One worker pass, in process, like the service does."""
    conn = db.connect(store.db_path)
    try:
        return worker.run(conn, store)
    finally:
        conn.close()


def renders_on_disk(store):
    return sorted(p for p in (store.root / "web-renders").rglob("*.jpg"))


def test_full_size_render_is_deduplicated_and_non_destructive(logged, store):
    src = upload(logged, DNG, "CRW_4211.DNG").json()["source"]
    orig = store.root / "web-originals" / src["sha256"][:2] / f"{src['sha256']}.dng"
    before = sha256_file(orig)[0]
    r = logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([src["asset_id"]], recipe("portra400", width=1600, height=1200)))
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    assert logged.get(f"{dapp.API}/jobs/{jid}").json()["state"] == "QUEUED"
    res = drain(store)
    assert [x.state for x in res] == ["COMMITTED"]
    view = logged.get(f"{dapp.API}/jobs/{jid}").json()
    assert view["state"] == "COMPLETE" and view["items"][0]["render"]["width"] == 1600
    rid = view["items"][0]["render"]["render_id"]
    jpg = logged.get(f"{dapp.API}/renders/{rid}/file")
    assert jpg.status_code == 200 and "CRW_4211_portra400" in jpg.headers["content-disposition"]
    im = Image.open(io.BytesIO(jpg.content))
    assert im.size == (1600, 1200) and im.getexif().get(272) == "Canon PowerShot SX510 HS"   # real camera, not the look
    side = json.loads(next(iter(renders_on_disk(store))).with_suffix(".jpg.json").read_text())
    assert side["recipe_v2"]["camera_look"]["id"] == "neutral" and side["original_sha256"] == src["sha256"]
    assert sha256_file(orig)[0] == before                                       # original untouched
    # the same render again: no second file
    again = logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([src["asset_id"]], recipe("portra400", width=1600, height=1200)))
    assert again.json()["job_id"] != jid
    res2 = drain(store)
    assert [x.detail for x in res2] == ["reused"] and len(renders_on_disk(store)) == 1
    # a new recipe is a new rendition next to the old one
    logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([src["asset_id"]], recipe("cinestill800t", width=1600, height=1200)))
    drain(store)
    assert len(renders_on_disk(store)) == 2
    hist = logged.get(f"{dapp.API}/history", params={"asset_id": src["asset_id"]}).json()["items"]
    assert {h["film"] for h in hist} == {"portra400", "cinestill800t"}
    assert len(hist) == 2


def test_full_size_is_native_size_and_never_upscaled(logged, store):
    src = upload(logged, DNG, "a.dng").json()["source"]
    ok = logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([src["asset_id"]])).json()["job_id"]
    big = logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([src["asset_id"]], recipe("portra400", width=9000, height=6000))).json()["job_id"]
    drain(store)
    a, b = (logged.get(f"{dapp.API}/jobs/{j}").json() for j in (ok, big))
    assert a["state"] == "COMPLETE" and a["items"][0]["render"]["width"] >= 4000     # native decoded size
    assert b["state"] == "FAILED" and b["items"][0]["error_code"] == "OUTPUT_LARGER_THAN_SOURCE"


def test_batch_cancel_retry_zip_and_idempotency(logged, store):
    a = upload(logged, DNG, "a.dng").json()["source"]["asset_id"]
    b = upload(logged, DNG2 if DNG2.is_file() else DNG, "b.dng").json()["source"]["asset_id"]
    body = job_body([a, b] if a != b else [a], recipe(width=800, height=600), idempotency_key="k-1")
    first = logged.post(f"{dapp.API}/jobs", headers=H, json=body)
    second = logged.post(f"{dapp.API}/jobs", headers=H, json=body)
    assert second.status_code == 200 and second.json()["job_id"] == first.json()["job_id"] and not second.json()["created"]
    clash = logged.post(f"{dapp.API}/jobs", headers=H, json={**body, "recipe": recipe("cinestill800t")})
    assert clash.status_code == 409 and clash.json()["error_code"] == "IDEMPOTENCY_CONFLICT"
    jid = first.json()["job_id"]
    assert logged.post(f"{dapp.API}/jobs/{jid}/cancel", headers=H).json()["cancelled_queued_items"] == first.json()["total"]
    assert logged.get(f"{dapp.API}/jobs/{jid}").json()["state"] == "CANCELLED"
    assert drain(store) == []                                                      # nothing runs after cancel
    assert logged.post(f"{dapp.API}/jobs/{jid}/retry", headers=H).json()["requeued_items"] == first.json()["total"]
    assert all(r.state == "COMMITTED" for r in drain(store))
    v = logged.get(f"{dapp.API}/jobs/{jid}").json()
    assert v["state"] == "COMPLETE"
    z = logged.get(f"{dapp.API}/jobs/{jid}/zip")
    import zipfile
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert z.status_code == 200 and len(names) == v["total"] and all(n.endswith(".jpg") for n in names)


def test_job_validation(logged):
    src = upload(logged, DNG, "a.dng").json()["source"]["asset_id"]
    cases = [
        (job_body([]), 422, "INVALID_JOB"),
        (job_body(["nope"]), 404, "UNKNOWN_ASSET"),
        (job_body([src, src]), 422, "DUPLICATE_ASSET"),
        (job_body([src], source={"kind": "photoprism_album", "assets": [{"asset_id": src}]}), 422, "SOURCE_KIND_UNAVAILABLE"),
        (job_body([src], output={"format": "jpeg", "publish": True}), 422, "PUBLISH_UNAVAILABLE"),
    ]
    for body, status, code in cases:
        r = logged.post(f"{dapp.API}/jobs", headers=H, json=body)
        assert (r.status_code, r.json()["error_code"]) == (status, code), r.text
    bad = recipe()
    bad["camera_look"]["id"] = "fujifilm_s5_pro"
    r = logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([src], bad))
    assert r.status_code == 422 and r.json()["error_code"] == "UNSUPPORTED_CAMERA_LOOK"
    assert logged.get(f"{dapp.API}/jobs/zzz").status_code == 404


@pytest.mark.skipif(NEF is None or not NEF.is_file(), reason="needs a real NEF")
def test_nef_full_render_carries_nikon_exif(logged, store):
    src = upload(logged, NEF, "DSC_0174.NEF").json()["source"]
    jid = logged.post(f"{dapp.API}/jobs", headers=H, json=job_body([src["asset_id"]], recipe("portra400", width=1500, height=1000))).json()["job_id"]
    drain(store)
    v = logged.get(f"{dapp.API}/jobs/{jid}").json()
    assert v["state"] == "COMPLETE", v
    im = Image.open(io.BytesIO(logged.get(f"{dapp.API}/renders/{v['items'][0]['render']['render_id']}/file").content))
    ex = im.getexif()
    assert im.size == (1500, 1000) and ex.get(271) == "NIKON CORPORATION" and ex.get(272) == "NIKON D5100"
    assert ex.get_ifd(0x8769).get(34855) == 400
