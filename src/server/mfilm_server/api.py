# SPDX-License-Identifier: GPL-2.0-only
"""mfilm-receiver: the sync API of docs/09 / contracts/openapi.yaml.

Camera-initiated, resumable, idempotent. A receipt is only ever returned
after the original is hashed, promoted into the archive and the catalog
transaction committed; replaying `complete` returns the same receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse

from . import config as config_mod
from . import camera_renders, contracts, core, db, devices, worker
from .ids import canonical_json, sha256_file
from .store import Store, UnsafePath, safe_id

PROTOCOL_MAJOR = 1
CHUNK_SIZE = 64 * 1024                 # advertised default (docs/09)
MAX_CHUNK = 1024 * 1024
MAX_ASSET_BYTES = 64 * 1024 * 1024     # SX510 HS DNG is ~20 MB
TIFF_MAGIC = (b"II*\x00", b"MM\x00*")


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str = "", retryable: bool = False, **extra):
        self.status, self.code, self.detail, self.retryable, self.extra = status, code, detail, retryable, extra


def create_app(store: Store) -> FastAPI:
    store.init()
    try:
        from .bundles import Bundles
        Bundles(store).ensure_default()
    except core.CoreError:
        pass                          # capabilities will report the error
    app = FastAPI(title="M-Film receiver", version="0.3-draft", docs_url=None, redoc_url=None)

    def conn() -> sqlite3.Connection:
        c = db.connect(store.db_path, threads=True)
        try:
            yield c
        finally:
            c.close()

    c0 = db.connect(store.db_path)
    db.migrate(c0)
    c0.close()

    @app.exception_handler(ApiError)
    async def _api_error(_req, e: ApiError):
        return JSONResponse({"error_code": e.code, "detail": e.detail, "retryable": e.retryable, **e.extra},
                            status_code=e.status)

    def device(authorization: str | None = Header(None), c: sqlite3.Connection = Depends(conn)) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise ApiError(401, "UNAUTHENTICATED", "bearer token required")
        dev = devices.authenticate(c, authorization[7:].strip())
        if not dev:
            raise ApiError(403, "FORBIDDEN", "unknown or revoked token")
        c.execute("UPDATE devices SET last_seen_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (dev,))
        return dev

    def own_roll(c, dev: str, roll_id: str) -> sqlite3.Row:
        try:
            safe_id(roll_id, "roll_id")
        except UnsafePath as e:
            raise ApiError(400, "BAD_ID", str(e)) from None
        row = c.execute("SELECT * FROM rolls WHERE device_id=? AND id=?", (dev, roll_id)).fetchone()
        if not row:
            raise ApiError(404, "UNKNOWN_ROLL", roll_id)
        return row

    @app.get("/v1/health")
    def health():
        return {"status": "ok", "protocol_major": PROTOCOL_MAJOR}

    @app.get("/v1/capabilities")
    def capabilities(dev: str = Depends(device)):
        from .bundles import Bundles
        try:
            b = core.Bundle()
            bundle = {"profile_bundle_hash": b.sha256, "films": b.keys, "film_core_version": core.core_version(),
                      "film_core_abi_version": core.abi_version(),
                      # every bundle the server can develop with exactly (rolls stay frozen to theirs)
                      "profile_bundles": [x["profile_bundle_hash"] for x in Bundles(store).list() if "films" in x]}
        except core.CoreError as e:
            bundle = {"error": e.code}
        return {"protocol_major": PROTOCOL_MAJOR, "device_id": dev, "chunk_size": CHUNK_SIZE,
                "max_chunk_size": MAX_CHUNK, "max_asset_bytes": MAX_ASSET_BYTES,
                "media_roles": ["original_dng", "camera_render"], "return_policies": ["none", "full_jpeg"],
                "transports": ["http"], **bundle}

    @app.put("/v1/rolls/{roll_id}")
    async def put_roll(roll_id: str, request: Request, dev: str = Depends(device), c=Depends(conn)):
        raw = await request.body()
        try:
            doc = contracts.load_roll_manifest(raw)
            for fr in doc["frames"]:
                safe_id(fr["frame_id"], "frame_id")
            safe_id(doc["roll_id"], "roll_id")
        except contracts.ManifestError as e:
            raise ApiError(400, e.code, e.detail) from None
        except UnsafePath as e:
            raise ApiError(400, "BAD_ID", str(e)) from None
        if doc["roll_id"] != roll_id or doc["device_id"] != dev:
            raise ApiError(409, "IDENTITY_MISMATCH", "roll_id/device_id differ from the URL/credential")
        if doc["roll_state"] not in ("SEALED", "READY_FOR_SYNC"):
            raise ApiError(409, "ROLL_NOT_SEALED", doc["roll_state"])
        if any(not fr.get("source_sha256") for fr in doc["frames"]):
            # uploads are identified by their hash; hashless frames only come in through SD/USB card import
            raise ApiError(422, "MANIFEST_HASH_REQUIRED", "every frame needs source_sha256 for network sync")
        msha = hashlib.sha256(canonical_json(doc)).hexdigest()
        known = c.execute("SELECT manifest_sha256 FROM rolls WHERE device_id=? AND id=?", (dev, roll_id)).fetchone()
        if known:
            if known[0] != msha:
                raise ApiError(409, "MANIFEST_CONFLICT", "a different manifest is already committed")
            return JSONResponse({"roll_id": roll_id, "manifest_sha256": msha, "created": False}, status_code=200)
        c.execute("BEGIN IMMEDIATE")
        try:
            c.execute(
                "INSERT INTO rolls(id, device_id, film_profile_id, profile_bundle_hash, render_recipe_id, roll_length,"
                " expected_frames, camera_state, manifest_sha256, created_at, sealed_at, state)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?, 'RECEIVING')",
                (roll_id, dev, doc["film_profile_id"], doc["profile_bundle_hash"].lower(), doc.get("render_recipe_id"),
                 doc["roll_length"], len(doc["frames"]), doc["roll_state"], msha, doc.get("created_at"),
                 doc.get("sealed_at")))
            for fr in doc["frames"]:
                c.execute("INSERT INTO frames(id, device_id, roll_id, ordinal, capture_time, declared_sha256,"
                          " declared_bytes, source_path, original_state) VALUES (?,?,?,?,?,?,?,?, 'DECLARED')",
                          (fr["frame_id"], dev, roll_id, fr["ordinal"], fr.get("captured_at"),
                           fr["source_sha256"].lower(), fr["source_size_bytes"], fr["source_path"]))
            mdest = store.manifest_path(dev, roll_id)
            if not mdest.exists():
                Store.promote(store.stage_bytes(raw), mdest)
            c.execute("COMMIT")
        except sqlite3.IntegrityError as e:
            c.execute("ROLLBACK")
            raise ApiError(409, "FRAME_CONFLICT", str(e)) from None
        except BaseException:
            c.execute("ROLLBACK")
            raise
        return JSONResponse({"roll_id": roll_id, "manifest_sha256": msha, "created": True}, status_code=201)

    def roll_state(c, roll) -> dict:
        frames = c.execute("SELECT id, ordinal, original_state FROM frames WHERE device_id=? AND roll_id=? "
                           "ORDER BY ordinal", (roll["device_id"], roll["id"])).fetchall()
        renders = {r["frame_id"]: r for r in c.execute(
            "SELECT x.id, x.frame_id, x.state, a.sha256, a.bytes FROM renders x JOIN frames f "
            "ON f.device_id=x.device_id AND f.id=x.frame_id LEFT JOIN assets a ON a.id=x.asset_id "
            "WHERE f.device_id=? AND f.roll_id=? AND x.origin='linux'", (roll["device_id"], roll["id"]))}
        cam = {r["frame_id"]: r["id"] for r in c.execute(
            "SELECT x.id, x.frame_id FROM renders x JOIN frames f ON f.device_id=x.device_id AND f.id=x.frame_id "
            "WHERE f.device_id=? AND f.roll_id=? AND x.origin='camera' AND x.state='COMMITTED'",
            (roll["device_id"], roll["id"]))}
        return {"roll_id": roll["id"], "server_state": roll["state"], "film_profile_id": roll["film_profile_id"],
                "frames": [{"frame_id": f["id"], "ordinal": f["ordinal"], "original_state": f["original_state"],
                            "render_id": renders[f["id"]]["id"] if f["id"] in renders else None,
                            "render_state": renders[f["id"]]["state"] if f["id"] in renders else None,
                            "camera_render_id": cam.get(f["id"])}
                           for f in frames]}

    @app.get("/v1/rolls/{roll_id}")
    def get_roll(roll_id: str, dev: str = Depends(device), c=Depends(conn)):
        return roll_state(c, own_roll(c, dev, roll_id))

    def receipt(c, frame_sha: str) -> dict:
        a = c.execute("SELECT id, sha256, bytes FROM assets WHERE sha256=?", (frame_sha,)).fetchone()
        return {"server_asset_id": str(a["id"]), "asset_sha256": a["sha256"], "bytes": a["bytes"], "durable": True}

    def upload_row(c, dev: str, upload_id: str) -> sqlite3.Row:
        row = c.execute("SELECT * FROM uploads WHERE id=? AND device_id=?", (upload_id, dev)).fetchone()
        if not row:
            raise ApiError(404, "UNKNOWN_UPLOAD", upload_id)
        return row

    def part_path(upload_id: str) -> Path:
        return store.root / "incoming" / f"upload-{safe_id(upload_id)}.part"

    @app.post("/v1/uploads", status_code=201)
    async def create_upload(request: Request, dev: str = Depends(device), c=Depends(conn)):
        try:
            body = json.loads(await request.body())
            for k in ("device_id", "roll_id", "frame_id", "media_role", "bytes", "sha256", "media_type"):
                if k not in body:
                    raise KeyError(k)
            sha = str(body["sha256"]).lower()
            nbytes = int(body["bytes"])
        except (ValueError, KeyError, TypeError) as e:
            raise ApiError(400, "BAD_REQUEST", f"upload init: {e}") from None
        if body["device_id"] != dev:
            raise ApiError(409, "IDENTITY_MISMATCH", "device_id differs from the credential")
        if body["media_role"] not in ("original_dng", "camera_render"):
            raise ApiError(422, "UNSUPPORTED_MEDIA_ROLE", body["media_role"])
        if len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha):
            raise ApiError(400, "BAD_REQUEST", "sha256")
        if nbytes < 1 or nbytes > MAX_ASSET_BYTES:
            raise ApiError(413, "TOO_LARGE", f"{nbytes} bytes")
        roll = own_roll(c, dev, body["roll_id"])
        fr = c.execute("SELECT * FROM frames WHERE device_id=? AND roll_id=? AND id=?",
                       (dev, roll["id"], body["frame_id"])).fetchone()
        if not fr:
            raise ApiError(404, "UNKNOWN_FRAME", str(body["frame_id"]))
        if body["media_role"] == "camera_render":
            return init_camera_render(c, dev, roll, fr, body, sha, nbytes)
        if fr["declared_sha256"] != sha or fr["declared_bytes"] != nbytes:
            raise ApiError(409, "DECLARED_IDENTITY_MISMATCH", "sha256/bytes differ from the roll manifest")
        if fr["original_state"] == "VERIFIED":
            done = c.execute("SELECT id FROM uploads WHERE device_id=? AND frame_id=? AND declared_sha256=? "
                             "AND state='COMPLETE'", (dev, fr["id"], sha)).fetchone()
            uid = done["id"] if done else None
            if not uid:     # verified through SD import: a completed pseudo-session keeps the protocol uniform
                uid = uuid.uuid4().hex
                c.execute("INSERT INTO uploads(id, device_id, roll_id, frame_id, media_role, declared_sha256,"
                          " declared_bytes, offset_bytes, state) VALUES (?,?,?,?,?,?,?,?, 'COMPLETE')",
                          (uid, dev, roll["id"], fr["id"], "original_dng", sha, nbytes, nbytes))
            return {"upload_id": uid, "next_offset": nbytes, "chunk_size": CHUNK_SIZE, "state": "COMPLETE"}
        open_ = c.execute("SELECT * FROM uploads WHERE device_id=? AND frame_id=? AND declared_sha256=? "
                          "AND state='OPEN'", (dev, fr["id"], sha)).fetchone()
        if open_:           # resume the existing session
            return {"upload_id": open_["id"], "next_offset": open_["offset_bytes"], "chunk_size": CHUNK_SIZE,
                    "state": "OPEN"}
        uid = uuid.uuid4().hex
        c.execute("INSERT INTO uploads(id, device_id, roll_id, frame_id, media_role, declared_sha256, declared_bytes,"
                  " offset_bytes, state) VALUES (?,?,?,?,?,?,?,0,'OPEN')",
                  (uid, dev, roll["id"], fr["id"], "original_dng", sha, nbytes))
        part_path(uid).touch()
        return {"upload_id": uid, "next_offset": 0, "chunk_size": CHUNK_SIZE, "state": "OPEN"}

    def init_camera_render(c, dev, roll, fr, body, sha, nbytes):
        try:
            meta = camera_renders.check_declared(roll, fr, body)
        except camera_renders.CameraRenderError as e:
            raise ApiError(e.status, e.code, e.detail) from None
        have = camera_renders.existing(c, meta["render_id"])
        if have is not None and have["state"] == "COMMITTED":
            if have["sha256"] != sha:
                raise ApiError(409, "RENDER_CONFLICT", "this render_id already has different pixels")
            done = c.execute("SELECT id FROM uploads WHERE device_id=? AND frame_id=? AND declared_sha256=? AND "
                             "state='COMPLETE'", (dev, fr["id"], sha)).fetchone()
            return {"upload_id": done["id"] if done else None, "next_offset": nbytes, "chunk_size": CHUNK_SIZE,
                    "state": "COMPLETE"}
        open_ = c.execute("SELECT * FROM uploads WHERE device_id=? AND frame_id=? AND declared_sha256=? "
                          "AND media_role='camera_render' AND state='OPEN'", (dev, fr["id"], sha)).fetchone()
        if open_:
            return {"upload_id": open_["id"], "next_offset": open_["offset_bytes"], "chunk_size": CHUNK_SIZE,
                    "state": "OPEN"}
        uid = uuid.uuid4().hex
        c.execute("INSERT INTO uploads(id, device_id, roll_id, frame_id, media_role, declared_sha256, declared_bytes,"
                  " offset_bytes, state, meta) VALUES (?,?,?,?, 'camera_render', ?,?,0,'OPEN',?)",
                  (uid, dev, roll["id"], fr["id"], sha, nbytes, json.dumps(meta, sort_keys=True)))
        part_path(uid).touch()
        return {"upload_id": uid, "next_offset": 0, "chunk_size": CHUNK_SIZE, "state": "OPEN"}

    @app.get("/v1/uploads/{upload_id}")
    def get_upload(upload_id: str, dev: str = Depends(device), c=Depends(conn)):
        u = upload_row(c, dev, upload_id)
        return {"upload_id": u["id"], "state": u["state"], "next_offset": u["offset_bytes"],
                "bytes": u["declared_bytes"]}

    @app.put("/v1/uploads/{upload_id}/chunk")
    async def put_chunk(upload_id: str, request: Request, x_upload_offset: int = Header(...),
                        dev: str = Depends(device), c=Depends(conn)):
        u = upload_row(c, dev, upload_id)
        if u["state"] != "OPEN":
            raise ApiError(409, "UPLOAD_NOT_OPEN", u["state"], next_offset=u["offset_bytes"])
        if x_upload_offset != u["offset_bytes"]:
            raise ApiError(409, "OFFSET_CONFLICT", f"expected {u['offset_bytes']}", next_offset=u["offset_bytes"])
        declared = request.headers.get("content-length")
        if declared is None or not declared.isdigit() or int(declared) > MAX_CHUNK:
            raise ApiError(413, "CHUNK_TOO_LARGE", f"Content-Length required, max {MAX_CHUNK}")
        data = await request.body()
        if len(data) > MAX_CHUNK:
            raise ApiError(413, "CHUNK_TOO_LARGE", f"max {MAX_CHUNK}")
        if not data or u["offset_bytes"] + len(data) > u["declared_bytes"]:
            raise ApiError(409, "CHUNK_PAST_END", "", next_offset=u["offset_bytes"])
        p = part_path(upload_id)
        with open(p, "r+b" if p.exists() else "w+b") as f:
            f.truncate(u["offset_bytes"])        # drop bytes written before a crash but never recorded
            f.seek(u["offset_bytes"])
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        new = u["offset_bytes"] + len(data)
        c.execute("UPDATE uploads SET offset_bytes=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                  "WHERE id=? AND offset_bytes=?", (new, upload_id, u["offset_bytes"]))
        return {"upload_id": upload_id, "next_offset": new}

    @app.post("/v1/uploads/{upload_id}/complete")
    def complete(upload_id: str, dev: str = Depends(device), c=Depends(conn)):
        u = upload_row(c, dev, upload_id)
        if u["state"] == "COMPLETE":
            return receipt(c, u["declared_sha256"])
        if u["state"] != "OPEN":
            raise ApiError(409, "UPLOAD_NOT_OPEN", u["state"])
        if u["offset_bytes"] != u["declared_bytes"]:
            raise ApiError(409, "INCOMPLETE_UPLOAD", "", next_offset=u["offset_bytes"])
        p = part_path(upload_id)
        sha, nbytes = sha256_file(p)
        if sha != u["declared_sha256"] or nbytes != u["declared_bytes"]:
            c.execute("UPDATE uploads SET state='ABORTED' WHERE id=?", (upload_id,))
            p.unlink(missing_ok=True)
            raise ApiError(422, "HASH_MISMATCH", "start a new upload")
        if u["media_role"] == "camera_render":
            try:
                camera_renders.commit(c, store, u, p, sha, nbytes)
            except camera_renders.CameraRenderError as e:
                if e.status == 422:
                    c.execute("UPDATE uploads SET state='ABORTED' WHERE id=?", (upload_id,))
                    p.unlink(missing_ok=True)
                raise ApiError(e.status, e.code, e.detail) from None
            return receipt(c, sha)
        with open(p, "rb") as f:
            if f.read(4) not in TIFF_MAGIC:
                c.execute("UPDATE uploads SET state='ABORTED' WHERE id=?", (upload_id,))
                p.unlink(missing_ok=True)
                raise ApiError(422, "UNSUPPORTED_DNG_FEATURE", "not a TIFF/DNG container")
        dest = store.original_path(dev, u["roll_id"], u["frame_id"])
        c.execute("BEGIN IMMEDIATE")
        try:
            if dest.exists():
                if sha256_file(dest)[0] != sha:
                    raise ApiError(409, "ARCHIVE_HASH_CONFLICT", "")
                p.unlink()
            else:
                os.chmod(p, 0o444)
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.link(p, dest)
                os.unlink(p)
            c.execute("INSERT OR IGNORE INTO assets(sha256, bytes, mime, kind, path) VALUES (?,?,?,?,?)",
                      (sha, nbytes, "image/x-adobe-dng", "original_dng", str(dest.relative_to(store.root))))
            aid = c.execute("SELECT id FROM assets WHERE sha256=?", (sha,)).fetchone()[0]
            c.execute("UPDATE frames SET original_asset_id=?, original_state='VERIFIED', error_code=NULL "
                      "WHERE device_id=? AND id=?", (aid, dev, u["frame_id"]))
            c.execute("UPDATE uploads SET state='COMPLETE' WHERE id=?", (upload_id,))
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        return receipt(c, sha)

    @app.post("/v1/rolls/{roll_id}/finalize")
    def finalize(roll_id: str, dev: str = Depends(device), c=Depends(conn)):
        roll = own_roll(c, dev, roll_id)
        missing = [r[0] for r in c.execute("SELECT id FROM frames WHERE device_id=? AND roll_id=? AND "
                                           "original_state!='VERIFIED' ORDER BY ordinal", (dev, roll_id))]
        if missing:
            raise ApiError(409, "ORIGINALS_MISSING", f"{len(missing)} frames", missing_frames=missing)
        already = roll["state"] == "INPUTS_COMPLETE"
        if not already:
            c.execute("UPDATE rolls SET state='INPUTS_COMPLETE' WHERE device_id=? AND id=?", (dev, roll_id))
        try:
            q = worker.enqueue_roll(c, roll_id, dev)
        except core.CoreError as e:
            raise ApiError(503, e.code, e.detail, retryable=True) from None
        return JSONResponse({"roll_id": roll_id, "queued": q["queued"], "frames": q["frames"]},
                            status_code=200 if already and q["queued"] == 0 else 202)

    @app.get("/v1/rolls/{roll_id}/renders")
    def list_renders(roll_id: str, origin: str = "linux", dev: str = Depends(device), c=Depends(conn)):
        roll = own_roll(c, dev, roll_id)
        if origin not in ("linux", "camera", "all"):
            raise ApiError(400, "BAD_REQUEST", "origin must be linux, camera or all")
        out = []
        for r in c.execute(
                "SELECT x.id, x.frame_id, x.origin, f.ordinal, a.sha256, a.bytes, a.path FROM renders x JOIN frames f "
                "ON f.device_id=x.device_id AND f.id=x.frame_id JOIN assets a ON a.id=x.asset_id "
                "WHERE f.device_id=? AND f.roll_id=? AND (?='all' OR x.origin=?) "
                "AND x.state IN ('COMMITTED','PUBLISHED') ORDER BY f.ordinal, x.origin DESC",
                (dev, roll["id"], origin, origin)):
            side = (store.root / r["path"]).with_suffix(".jpg.json")
            meta = json.loads(side.read_text()) if side.is_file() else {}
            out.append({"render_id": r["id"], "frame_id": r["frame_id"], "ordinal": r["ordinal"],
                        "sha256": r["sha256"], "bytes": r["bytes"], "width": meta.get("output_width"),
                        "height": meta.get("output_height"),
                        "film_profile_id": meta.get("film_profile_id") or meta.get("recipe", {}).get("film_profile_id"),
                        "profile_bundle_hash": meta.get("profile_bundle_hash")
                        or meta.get("recipe", {}).get("profile_bundle_hash"), "origin": r["origin"]})
        return out

    @app.get("/v1/renders/{render_id}/file")
    def render_file(render_id: str, dev: str = Depends(device), c=Depends(conn)):
        r = c.execute("SELECT a.path, a.sha256 FROM renders x JOIN assets a ON a.id=x.asset_id "
                      "WHERE x.id=? AND x.device_id=? AND x.state IN ('COMMITTED','PUBLISHED')",
                      (render_id, dev)).fetchone()
        if not r:
            raise ApiError(404, "UNKNOWN_RENDER", render_id)
        return FileResponse(store.root / r["path"], media_type="image/jpeg",
                            headers={"X-Asset-SHA256": r["sha256"]})

    return app


def main(argv: list[str] | None = None) -> int:
    import argparse

    import uvicorn
    ap = argparse.ArgumentParser(prog="mfilm-receiver")
    ap.add_argument("--config")
    ap.add_argument("--data-dir")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (LAN only; never expose to the Internet)")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    cfg = config_mod.load(a.config)
    store = Store(Path(a.data_dir or os.environ.get("MFILM_DATA_DIR") or cfg.data_dir))
    uvicorn.run(create_app(store), host=a.host, port=a.port, log_level="info", access_log=False)
    return 0
