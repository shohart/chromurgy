# SPDX-License-Identifier: GPL-2.0-only
"""Durable development jobs (docs/web/31): a job is a snapshot of source assets plus one
validated recipe v2; each source is an item with its own state. The full-size render
reads the original RAW (never the preview), runs in the regular worker pass (same
worker.lock and memory budget as camera rolls), and is deduplicated by render_id:
identical source + recipe + engine versions + size never produce a second file."""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import uuid

import jsonschema

from .. import core
from ..bundles import Bundles, BundleUnavailable
from ..develop import DevelopError, develop, recipe_render_id, recipe_seed
from ..ids import sha256_file
from ..store import Store
from . import recipe2

NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
MAX_ATTEMPTS = 3
MAX_ITEMS = 500
TERMINAL = {"BAD_DNG", "BAD_RAW", "UNSUPPORTED_PROFILE", "UNSUPPORTED_RECIPE", "PROFILE_BUNDLE_MISMATCH",
            "OUTPUT_LARGER_THAN_SOURCE", "UNSUPPORTED_DNG_FEATURE", "SOURCE_CHANGED", "SOURCE_MISSING"}
SOURCE_KINDS = {"upload"}                      # implemented; the schema also allows photoprism_* and mfilm_roll
ACTIVE = ("QUEUED", "DECODING", "RENDERING", "VALIDATING")


class JobError(Exception):
    def __init__(self, code: str, detail: str = "", status: int = 422):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.status = code, detail, status


def _job_schema() -> dict:
    doc = json.loads((core.REPO / "contracts" / "v0.5" / "web-darkroom-job.schema.json").read_text())
    doc["properties"]["recipe"] = {"type": "object"}          # validated by recipe2 (the $ref needs a registry)
    return doc


def create_job(conn: sqlite3.Connection, bundle: core.Bundle, request: dict) -> tuple[str, bool]:
    """Returns (job_id, created). Raises JobError / recipe2.RecipeError."""
    try:
        jsonschema.validate(request, _job_schema())
    except jsonschema.ValidationError as e:
        raise JobError("INVALID_JOB", f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}") from None
    src = request["source"]
    if src["kind"] not in SOURCE_KINDS:
        raise JobError("SOURCE_KIND_UNAVAILABLE", f"{src['kind']} is not available yet")
    out = request["output"]
    if out.get("publish"):
        raise JobError("PUBLISH_UNAVAILABLE", "publishing to PhotoPrism is not available yet; use publish=false")
    recipe_in = copy.deepcopy(request["recipe"])
    if "quality" in out:
        recipe_in["render"]["quality"] = out["quality"]
    recipe = recipe2.normalize(recipe_in, bundle)
    rhash = recipe2.recipe_hash(recipe)
    ids = [a["asset_id"] for a in src["assets"]]
    if len(set(ids)) != len(ids):
        raise JobError("DUPLICATE_ASSET", "an asset appears twice in the job")
    if len(ids) > MAX_ITEMS:
        raise JobError("TOO_MANY_ASSETS", f"{len(ids)} > {MAX_ITEMS}", 413)
    rows = []
    for aid in ids:
        r = conn.execute("SELECT * FROM sources WHERE id=?", (aid,)).fetchone()
        if not r:
            raise JobError("UNKNOWN_ASSET", aid, 404)
        if not r["eligible"]:
            raise JobError("ASSET_NOT_ELIGIBLE", f"{aid}: {r['reason']}")
        if r["origin"] != "upload":
            raise JobError("SOURCE_KIND_UNAVAILABLE", f"{aid}: origin {r['origin']}")
        rows.append(r)
    body = json.dumps(request, sort_keys=True)
    key = request.get("idempotency_key")
    if key:
        have = conn.execute("SELECT id, request FROM darkroom_jobs WHERE idempotency_key=?", (key,)).fetchone()
        if have:
            if json.loads(have["request"]) != json.loads(body):
                raise JobError("IDEMPOTENCY_CONFLICT", "this key was used for a different request", 409)
            return have["id"], False
    jid = uuid.uuid4().hex
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT INTO darkroom_jobs(id, idempotency_key, request, recipe, recipe_hash) VALUES (?,?,?,?,?)",
                     (jid, key, body, json.dumps(recipe, sort_keys=True), rhash))
        for i, r in enumerate(rows, 1):
            conn.execute("INSERT INTO darkroom_items(job_id, source_id, source_sha256, ordinal, state) "
                         "VALUES (?,?,?,?, 'QUEUED')", (jid, r["id"], r["sha256"], i))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return jid, True


def job_state(counts: dict[str, int]) -> str:
    n = sum(counts.values())
    if not n:
        return "EMPTY"
    done = counts.get("COMPLETE", 0) + counts.get("STAGED", 0)
    if any(counts.get(s) for s in ACTIVE):
        return "RUNNING" if (n - counts.get("QUEUED", 0)) else "QUEUED"
    if counts.get("CANCELLED", 0) and counts["CANCELLED"] + done == n:
        return "CANCELLED" if not done else "PARTIAL"
    if counts.get("FAILED", 0) == n:
        return "FAILED"
    if counts.get("FAILED", 0) or counts.get("CANCELLED", 0):
        return "PARTIAL"
    return "COMPLETE"


def job_view(conn: sqlite3.Connection, job_id: str, *, items: bool = True) -> dict | None:
    j = conn.execute("SELECT * FROM darkroom_jobs WHERE id=?", (job_id,)).fetchone()
    if not j:
        return None
    counts = {r[0]: r[1] for r in conn.execute("SELECT state, count(*) FROM darkroom_items WHERE job_id=? GROUP BY 1",
                                              (job_id,))}
    recipe = json.loads(j["recipe"])
    view = {"job_id": j["id"], "state": job_state(counts), "counts": counts, "total": sum(counts.values()),
            "cancel_requested": bool(j["cancel_requested"]), "created_at": j["created_at"],
            "recipe_hash": j["recipe_hash"], "film": recipe["film"]["id"], "camera_look": recipe["camera_look"]["id"],
            "idempotency_key": j["idempotency_key"]}
    if items:
        view["recipe"] = recipe
        view["items"] = [{
            "item_id": r["id"], "asset_id": r["source_id"], "filename": r["filename"], "ordinal": r["ordinal"],
            "state": r["state"], "attempt": r["attempt"], "error_code": r["error_code"],
            "error_detail": r["error_detail"],
            "render": None if not r["render_id"] else {
                "render_id": r["render_id"], "width": r["width"], "height": r["height"], "bytes": r["bytes"],
                "sha256": r["rsha"]}}
            for r in conn.execute(
                "SELECT i.*, s.filename, w.width, w.height, w.bytes, w.sha256 AS rsha FROM darkroom_items i "
                "JOIN sources s ON s.id=i.source_id LEFT JOIN web_renders w ON w.id=i.render_id "
                "WHERE i.job_id=? ORDER BY i.ordinal", (job_id,))]
    return view


def cancel(conn: sqlite3.Connection, job_id: str) -> int:
    """Cooperative: queued items stop now, running ones finish; nothing committed is deleted."""
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("UPDATE darkroom_jobs SET cancel_requested=1 WHERE id=?", (job_id,))
    n = conn.execute(f"UPDATE darkroom_items SET state='CANCELLED', finished_at={NOW} "
                     "WHERE job_id=? AND state='QUEUED'", (job_id,)).rowcount
    conn.execute("COMMIT")
    return n


def retry(conn: sqlite3.Connection, job_id: str) -> int:
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("UPDATE darkroom_jobs SET cancel_requested=0 WHERE id=?", (job_id,))
    n = conn.execute("UPDATE darkroom_items SET state='QUEUED', attempt=0, error_code=NULL, error_detail=NULL, "
                     "finished_at=NULL WHERE job_id=? AND state IN ('FAILED','CANCELLED')", (job_id,)).rowcount
    conn.execute("COMMIT")
    return n


def recover_stale(conn: sqlite3.Connection) -> int:
    """Items left mid-render by a dead worker go back to the queue (only call with the worker lock held)."""
    conn.execute("BEGIN IMMEDIATE")
    n = conn.execute("UPDATE darkroom_items SET state='QUEUED' WHERE state IN ('DECODING','RENDERING','VALIDATING')").rowcount
    conn.execute("COMMIT")
    return n


def _exif_extra(meta: dict) -> dict:
    ifd0, exif = {}, {}
    if meta.get("make"):
        ifd0[0x010F] = meta["make"]
    if meta.get("model"):
        ifd0[0x0110] = meta["model"]
    if meta.get("iso"):
        exif[0x8827] = int(meta["iso"])
    for tag, k in ((0x829A, "exposure_s"), (0x829D, "aperture"), (0x920A, "focal_mm")):
        if meta.get(k):
            exif[tag] = float(meta[k])
    return {"ifd0": ifd0, "exif": exif}


def _set(conn, item_id: int, state: str, **cols) -> None:
    sets = ", ".join(f"{k}=?" for k in cols)
    conn.execute(f"UPDATE darkroom_items SET state=?{', ' + sets if sets else ''} WHERE id=?",
                 (state, *cols.values(), item_id))


def _claim(conn: sqlite3.Connection, skip: set[int]) -> sqlite3.Row | None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        item = None
        for r in conn.execute("SELECT i.*, j.cancel_requested FROM darkroom_items i JOIN darkroom_jobs j ON j.id=i.job_id "
                              "WHERE i.state='QUEUED' ORDER BY i.id"):
            if r["id"] in skip:
                continue
            if r["cancel_requested"]:
                _set(conn, r["id"], "CANCELLED", finished_at=None)
                continue
            item = r
            break
        if item:
            conn.execute(f"UPDATE darkroom_items SET state='DECODING', attempt=attempt+1, started_at={NOW}, "
                         "error_code=NULL, error_detail=NULL WHERE id=?", (item["id"],))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return item


def run_one(conn: sqlite3.Connection, store: Store, bundles: Bundles, skip: set[int] = frozenset()):
    """Develop one queued item. Returns (item_id, render_id|None, state, error_code, detail) or None."""
    item = _claim(conn, set(skip))
    if not item:
        return None
    iid = item["id"]
    job = conn.execute("SELECT * FROM darkroom_jobs WHERE id=?", (item["job_id"],)).fetchone()
    src = conn.execute("SELECT * FROM sources WHERE id=?", (item["source_id"],)).fetchone()
    try:
        recipe = json.loads(job["recipe"])
        rd = recipe["render"]
        v1 = recipe2.to_v1(recipe, width=int(rd.get("width") or 0), height=int(rd.get("height") or 0))
        bundle = bundles.get(v1["profile_bundle_hash"])
        path = store.root / src["path"]
        if not path.is_file():
            raise DevelopError("SOURCE_MISSING", src["path"])
        seed = recipe_seed(v1, "web", "web", src["sha256"])
        rid = recipe_render_id(src["sha256"], v1, bundle.sha256, seed)
        have = conn.execute("SELECT * FROM web_renders WHERE id=?", (rid,)).fetchone()
        if have and (store.root / have["path"]).is_file():
            _set(conn, iid, "COMPLETE", render_id=rid, finished_at=None)
            conn.execute(f"UPDATE darkroom_items SET finished_at={NOW} WHERE id=?", (iid,))
            return iid, rid, "COMPLETE", None, "reused"
        if sha256_file(path)[0] != src["sha256"]:
            raise DevelopError("SOURCE_CHANGED", "the archived original no longer matches its hash")
        conn.execute("UPDATE darkroom_items SET state='RENDERING' WHERE id=?", (iid,))
        work = store.root / "incoming" / f"web-render-{rid}"
        work.mkdir(exist_ok=True)
        out = work / f"{rid}.jpg"
        meta = json.loads(src["meta"])
        prov = develop(path, out, profile=None, recipe=v1, device_id="web", roll_id="web", frame_id=src["sha256"],
                       bundle=bundle, captured_at=_iso(meta.get("captured_at")), exif_extra=_exif_extra(meta))
        if prov["render_id"] != rid:
            raise DevelopError("RENDER_IDENTITY_MISMATCH", f"{prov['render_id']} != {rid}")
        conn.execute("UPDATE darkroom_items SET state='VALIDATING' WHERE id=?", (iid,))
        prov.update({"source": {"origin": src["origin"], "asset_id": src["id"], "sha256": src["sha256"],
                                "filename": src["filename"], "meta": meta},
                     "recipe_v2": recipe, "recipe_v2_hash": job["recipe_hash"], "job_id": job["id"]})
        dest = store.root / "web-renders" / rid[:2] / f"{rid}.jpg"
        prov["output"] = str(dest.relative_to(store.root))
        (work / f"{rid}.jpg.json").write_text(json.dumps(prov, indent=2, ensure_ascii=False) + "\n")
        dest.parent.mkdir(parents=True, exist_ok=True)
        for stale in (dest, dest.with_suffix(".jpg.json")):         # a crash between the two promotions
            if stale.exists():
                os.chmod(stale, 0o644)
                stale.unlink()
        Store.promote(work / f"{rid}.jpg.json", dest.with_suffix(".jpg.json"))
        Store.promote(out, dest)                                       # the JPEG last: its presence = pair complete
        os.rmdir(work)
        sha, nbytes = sha256_file(dest)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT OR IGNORE INTO web_renders(id, source_id, recipe_hash, recipe, path, sha256, bytes, width,"
                     " height) VALUES (?,?,?,?,?,?,?,?,?)",
                     (rid, src["id"], job["recipe_hash"], job["recipe"], str(dest.relative_to(store.root)), sha, nbytes,
                      prov["output_width"], prov["output_height"]))
        _set(conn, iid, "COMPLETE", render_id=rid)
        conn.execute(f"UPDATE darkroom_items SET finished_at={NOW} WHERE id=?", (iid,))
        conn.execute("COMMIT")
        return iid, rid, "COMPLETE", None, None
    except BundleUnavailable as e:
        return _fail(conn, iid, item["attempt"] + 1, e.code, str(e), terminal=True)
    except (DevelopError, core.CoreError) as e:
        return _fail(conn, iid, item["attempt"] + 1, e.code, e.detail, terminal=e.code in TERMINAL)
    except OSError as e:
        return _fail(conn, iid, item["attempt"] + 1, "IO_ERROR", str(e), terminal=False)


def _fail(conn, iid: int, attempt: int, code: str, detail: str, *, terminal: bool):
    final = terminal or attempt >= MAX_ATTEMPTS
    if conn.in_transaction:
        conn.execute("ROLLBACK")
    _set(conn, iid, "FAILED" if final else "QUEUED", error_code=code, error_detail=detail[:500])
    if final:
        conn.execute(f"UPDATE darkroom_items SET finished_at={NOW} WHERE id=?", (iid,))
    return iid, None, "FAILED_TERMINAL" if final else "FAILED_RETRYABLE", code, detail


def _iso(exif_stamp: str | None) -> str | None:
    """'2015:11:10 23:42:23' (EXIF, local time) -> ISO text develop() can parse."""
    if not exif_stamp or len(exif_stamp) < 19:
        return None
    return f"{exif_stamp[:4]}-{exif_stamp[5:7]}-{exif_stamp[8:10]}T{exif_stamp[11:19]}"
