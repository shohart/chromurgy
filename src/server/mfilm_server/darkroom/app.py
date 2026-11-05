# SPDX-License-Identifier: GPL-2.0-only
"""mfilm-web: the Web Darkroom backend-for-frontend (docs/web/33, contracts/v0.5/openapi-web-darkroom.yaml).

A separate app from the camera receiver (mfilm-receiver): different port, a
different credential (operator login, not device tokens), same store/catalog."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from .. import config as config_mod
from .. import core, db
from ..bundles import Bundles
from ..store import Store, UnsafePath, safe_id
from . import auth, catalog, engine, jobs, preview, recipe2, sources

API = "/api/v1/darkroom"
COOKIE = "mfilm_session"
CSRF_HEADER = "x-mfilm-csrf"
MAX_UPLOAD_BYTES = int(os.environ.get("MFILM_WEB_MAX_UPLOAD_MB", "512")) << 20
MAX_CHUNK = 8 << 20
CHUNK_SIZE = 4 << 20
MAX_OPEN_UPLOADS = 200
STATIC = Path(__file__).with_name("static")


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str = "", **extra):
        self.status, self.code, self.detail, self.extra = status, code, detail, extra


def create_app(store: Store, cfg: config_mod.Config | None = None) -> FastAPI:
    store.init()
    cfg = cfg or config_mod.Config()
    @contextlib.asynccontextmanager
    async def lifespan(_app):
        yield
        if "l" in lane:
            lane["l"].close()

    lane: dict[str, preview.PreviewLane] = {}
    app = FastAPI(title="M-Film Web Darkroom", version="0.5-draft", docs_url=None, redoc_url=None, lifespan=lifespan)
    c0 = db.connect(store.db_path)
    db.migrate(c0)
    c0.close()
    try:
        if not Bundles(store).has(engine.current_bundle().sha256):
            Bundles(store).ensure_default()
    except core.CoreError:
        pass
    app.state.store, app.state.cfg = store, cfg
    def get_lane() -> preview.PreviewLane:          # started on first use: spawning costs a process
        if "l" not in lane:
            lane["l"] = preview.PreviewLane(workers=int(os.environ.get("MFILM_WEB_PREVIEW_WORKERS", "1")))
        return lane["l"]


    def conn() -> sqlite3.Connection:
        c = db.connect(store.db_path, threads=True)
        try:
            yield c
        finally:
            c.close()

    @app.exception_handler(ApiError)
    async def _err(_req, e: ApiError):
        return JSONResponse({"error_code": e.code, "detail": e.detail, **e.extra}, status_code=e.status)

    def session(request: Request, authorization: str | None = Header(None), c=Depends(conn)) -> str:
        tok = request.cookies.get(COOKIE)
        via_cookie = bool(tok)
        if not tok and authorization and authorization.startswith("Bearer "):
            tok = authorization[7:].strip()
        if not auth.valid_session(c, tok):
            raise ApiError(401, "UNAUTHENTICATED", "log in first")
        if via_cookie and request.method not in ("GET", "HEAD") and request.headers.get(CSRF_HEADER) != "1":
            raise ApiError(403, "CSRF", f"missing {CSRF_HEADER} header")
        return tok

    def bundle() -> core.Bundle:
        try:
            return engine.current_bundle()
        except core.CoreError as e:
            raise ApiError(503, e.code, e.detail) from None

    # ---- shell ---------------------------------------------------------------------------------
    @app.get("/darkroom")
    def ui():
        f = STATIC / "index.html"
        if not f.is_file():
            raise ApiError(404, "NO_UI", "static/index.html is missing")
        return FileResponse(f, media_type="text/html", headers={"Cache-Control": "no-store",
                            "Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; "
                                                       "style-src 'self' 'unsafe-inline'"})

    @app.get("/darkroom/static/{name}")
    def static_file(name: str):
        try:
            p = (STATIC / safe_id(name, "name")).resolve()
        except UnsafePath:
            raise ApiError(404, "NOT_FOUND") from None
        if STATIC.resolve() not in p.parents or not p.is_file():
            raise ApiError(404, "NOT_FOUND")
        return FileResponse(p, headers={"Cache-Control": "no-cache"})

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        try:
            b = engine.current_bundle()
            return {"status": "ok", "film_core": core.core_version(), "films": len(b.keys),
                    "login_configured": auth.configured(store)}
        except core.CoreError as e:
            return JSONResponse({"status": "unavailable", "error_code": e.code}, status_code=503)

    # ---- login ---------------------------------------------------------------------------------
    @app.post(f"{API}/login")
    async def login(request: Request, response: Response, c=Depends(conn)):
        if not auth.configured(store):
            raise ApiError(503, "LOGIN_NOT_CONFIGURED", "run: mfilmctl web-passwd")
        try:
            pw = (json.loads(await request.body()) or {}).get("password", "")
        except ValueError:
            pw = ""
        if request.headers.get(CSRF_HEADER) != "1":
            raise ApiError(403, "CSRF", f"missing {CSRF_HEADER} header")
        if not isinstance(pw, str) or not await run_in_threadpool(auth.check_password, store, pw):
            await asyncio.sleep(0.7)
            raise ApiError(401, "BAD_CREDENTIALS", "wrong password")
        tok = auth.new_session(c)
        response.set_cookie(COOKIE, tok, httponly=True, samesite="strict", secure=request.url.scheme == "https",
                            max_age=auth.SESSION_HOURS * 3600, path="/")
        return {"ok": True}

    @app.post(f"{API}/logout")
    def logout(response: Response, tok: str = Depends(session), c=Depends(conn)):
        auth.end_session(c, tok)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get(f"{API}/session")
    def whoami(_t: str = Depends(session)):
        return {"ok": True}

    # ---- catalog and recipe --------------------------------------------------------------------
    @app.get(f"{API}/catalog")
    def get_catalog(_t: str = Depends(session)):
        return catalog.build(bundle())

    @app.post(f"{API}/recipe/validate")
    async def validate_recipe(request: Request, _t: str = Depends(session)):
        try:
            body = json.loads(await request.body())
        except ValueError:
            raise ApiError(400, "BAD_REQUEST", "JSON body required") from None
        try:
            r = recipe2.normalize(body, bundle())
        except recipe2.RecipeError as e:
            raise ApiError(422, e.code, e.detail) from None
        return {"recipe": r, "recipe_hash": recipe2.recipe_hash(r)}

    # ---- RAW upload (resumable, chunked) -------------------------------------------------------
    def part(upload_id: str) -> Path:
        return store.root / "incoming" / f"web-{safe_id(upload_id)}.part"

    @app.post(f"{API}/sources/uploads", status_code=201)
    async def upload_init(request: Request, _t: str = Depends(session), c=Depends(conn)):
        try:
            body = json.loads(await request.body())
            name, size = str(body["filename"]), int(body["size_bytes"])
            sha = str(body.get("sha256") or "").lower() or None
        except (ValueError, KeyError, TypeError):
            raise ApiError(400, "BAD_REQUEST", "filename and size_bytes required") from None
        if sha and (len(sha) != 64 or any(ch not in "0123456789abcdef" for ch in sha)):
            raise ApiError(400, "BAD_REQUEST", "sha256")
        if size < 1 or size > MAX_UPLOAD_BYTES:
            raise ApiError(413, "TOO_LARGE", f"{size} bytes (limit {MAX_UPLOAD_BYTES})")
        label = sources.display_name(name)
        if Path(label).suffix.lower() not in sources.SUPPORTED_EXT:
            raise ApiError(422, "UNSUPPORTED_EXTENSION", f"{label}: expected .dng or .nef")
        if sha:                                   # already archived: nothing to send
            have = c.execute("SELECT * FROM sources WHERE id=?", (sources.source_id(sha),)).fetchone()
            if have and have["bytes"] == size:
                uid = uuid.uuid4().hex
                c.execute("INSERT INTO web_uploads(id, filename, declared_bytes, declared_sha256, offset_bytes, state,"
                          " source_id) VALUES (?,?,?,?,?, 'COMPLETE', ?)", (uid, label, size, sha, size, have["id"]))
                return {"upload_id": uid, "next_offset": size, "chunk_size": CHUNK_SIZE, "state": "COMPLETE",
                        "duplicate": True, "source": sources.row_public(have)}
        if c.execute("SELECT count(*) FROM web_uploads WHERE state='OPEN'").fetchone()[0] >= MAX_OPEN_UPLOADS:
            raise ApiError(429, "TOO_MANY_UPLOADS", "finish or abandon open uploads first")
        free = os.statvfs(store.root).f_bavail * os.statvfs(store.root).f_frsize
        if free < size * 3:
            raise ApiError(507, "DISK_FULL", f"{free >> 20} MiB free")
        uid = uuid.uuid4().hex
        c.execute("INSERT INTO web_uploads(id, filename, declared_bytes, declared_sha256, state) VALUES (?,?,?,?, 'OPEN')",
                  (uid, label, size, sha))
        part(uid).touch()
        return {"upload_id": uid, "next_offset": 0, "chunk_size": CHUNK_SIZE, "state": "OPEN"}

    def upload_row(c, uid: str) -> sqlite3.Row:
        try:
            safe_id(uid, "upload_id")
        except UnsafePath:
            raise ApiError(404, "UNKNOWN_UPLOAD", "") from None
        row = c.execute("SELECT * FROM web_uploads WHERE id=?", (uid,)).fetchone()
        if not row:
            raise ApiError(404, "UNKNOWN_UPLOAD", uid)
        return row

    @app.get(f"{API}/sources/uploads/{{upload_id}}")
    def upload_status(upload_id: str, _t: str = Depends(session), c=Depends(conn)):
        u = upload_row(c, upload_id)
        return {"upload_id": u["id"], "state": u["state"], "next_offset": u["offset_bytes"],
                "size_bytes": u["declared_bytes"], "error_code": u["error_code"], "source_id": u["source_id"]}

    @app.put(f"{API}/sources/uploads/{{upload_id}}/chunk")
    async def upload_chunk(upload_id: str, request: Request, x_upload_offset: int = Header(...),
                           _t: str = Depends(session), c=Depends(conn)):
        u = upload_row(c, upload_id)
        if u["state"] != "OPEN":
            raise ApiError(409, "UPLOAD_NOT_OPEN", u["state"], next_offset=u["offset_bytes"])
        if x_upload_offset != u["offset_bytes"]:
            raise ApiError(409, "OFFSET_CONFLICT", f"expected {u['offset_bytes']}", next_offset=u["offset_bytes"])
        declared = request.headers.get("content-length")
        if declared is None or not declared.isdigit() or int(declared) > MAX_CHUNK:
            raise ApiError(413, "CHUNK_TOO_LARGE", f"Content-Length required, max {MAX_CHUNK}")
        data = await request.body()
        if not data or len(data) > MAX_CHUNK or u["offset_bytes"] + len(data) > u["declared_bytes"]:
            raise ApiError(409, "CHUNK_PAST_END", "", next_offset=u["offset_bytes"])
        p = part(upload_id)

        def write() -> None:                          # blocking I/O + fsync: off the event loop
            with open(p, "r+b" if p.exists() else "w+b") as f:
                f.truncate(u["offset_bytes"])
                f.seek(u["offset_bytes"])
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        await run_in_threadpool(write)
        new = u["offset_bytes"] + len(data)
        c.execute("UPDATE web_uploads SET offset_bytes=?, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                  "WHERE id=? AND offset_bytes=?", (new, upload_id, u["offset_bytes"]))
        return {"upload_id": upload_id, "next_offset": new}

    @app.post(f"{API}/sources/uploads/{{upload_id}}/complete")
    def upload_complete(upload_id: str, _t: str = Depends(session), c=Depends(conn)):
        u = upload_row(c, upload_id)
        if u["state"] == "COMPLETE":
            return {"source": sources.row_public(c.execute("SELECT * FROM sources WHERE id=?", (u["source_id"],)).fetchone())}
        if u["state"] != "OPEN":
            raise ApiError(409, "UPLOAD_NOT_OPEN", u["state"])
        if u["offset_bytes"] != u["declared_bytes"]:
            raise ApiError(409, "INCOMPLETE_UPLOAD", "", next_offset=u["offset_bytes"])
        p = part(upload_id)
        from ..ids import sha256_file
        sha, _n = sha256_file(p)
        if u["declared_sha256"] and sha != u["declared_sha256"]:
            p.unlink(missing_ok=True)
            c.execute("UPDATE web_uploads SET state='ABORTED', error_code='HASH_MISMATCH' WHERE id=?", (upload_id,))
            raise ApiError(422, "HASH_MISMATCH", "start a new upload")
        try:
            row, dup = sources.commit_upload(c, store, p, u["filename"])
        except sources.SourceError as e:
            p.unlink(missing_ok=True)
            c.execute("UPDATE web_uploads SET state='ABORTED', error_code=? WHERE id=?", (e.code, upload_id))
            raise ApiError(e.status, e.code, e.detail) from None
        c.execute("UPDATE web_uploads SET state='COMPLETE', source_id=? WHERE id=?", (row["id"], upload_id))
        return {"source": sources.row_public(row), "duplicate": dup}

    # ---- source catalog ------------------------------------------------------------------------
    @app.get(f"{API}/sources")
    def list_sources(origin: str | None = None, count: int = 100, offset: int = 0,
                     _t: str = Depends(session), c=Depends(conn)):
        count = max(1, min(count, 500))
        rows = c.execute("SELECT * FROM sources WHERE (?1 IS NULL OR origin=?1) ORDER BY created_at DESC, id "
                         "LIMIT ?2 OFFSET ?3", (origin, count, max(0, offset))).fetchall()
        total = c.execute("SELECT count(*) FROM sources WHERE (?1 IS NULL OR origin=?1)", (origin,)).fetchone()[0]
        return {"total": total, "items": [sources.row_public(r) for r in rows]}

    # ---- previews (docs/web/31) ----------------------------------------------------------------
    def source_row(c, asset_id: str) -> sqlite3.Row:
        row = c.execute("SELECT * FROM sources WHERE id=?", (asset_id,)).fetchone()
        if not row:
            raise ApiError(404, "UNKNOWN_ASSET", asset_id)
        if not row["eligible"]:
            raise ApiError(422, "ASSET_NOT_ELIGIBLE", row["reason"] or "")
        return row

    @app.get(f"{API}/sources/{{asset_id}}")
    def get_source(asset_id: str, _t: str = Depends(session), c=Depends(conn)):
        try:
            safe_id(asset_id, "asset_id")
        except UnsafePath:
            raise ApiError(404, "UNKNOWN_ASSET", "") from None
        row = c.execute("SELECT * FROM sources WHERE id=?", (asset_id,)).fetchone()
        if not row:
            raise ApiError(404, "UNKNOWN_ASSET", asset_id)
        return sources.row_public(row)

    @app.post(f"{API}/previews", status_code=202)
    async def create_preview(request: Request, _t: str = Depends(session), c=Depends(conn)):
        try:
            body = json.loads(await request.body())
            asset_id, kind = str(body["asset_id"]), body.get("kind", "treated")
            max_edge = int(body.get("max_edge", 1280))
            stream = str(body.get("stream") or "default")[:64]
        except (ValueError, KeyError, TypeError):
            raise ApiError(400, "BAD_REQUEST", "asset_id and recipe required") from None
        if kind not in ("treated", "before") or not 320 <= max_edge <= 2048:
            raise ApiError(422, "INVALID_REQUEST", "kind: treated|before, max_edge: 320..2048")
        row = source_row(c, asset_id)
        b = bundle()
        v2 = v1 = None
        if kind == "treated":
            try:
                v2 = recipe2.normalize(body.get("recipe"), b)
            except recipe2.RecipeError as e:
                raise ApiError(422, e.code, e.detail) from None
            v1 = recipe2.to_v1(v2)
        rhash = recipe2.recipe_hash(v2) if v2 else "before"
        key = preview.preview_key(sha=row["sha256"], kind=kind, recipe_hash=rhash, max_edge=max_edge,
                                  bundle_hash=b.sha256)
        meta = json.loads(row["meta"])
        job = {"root": str(store.root), "src_path": str(store.root / row["path"]), "sha": row["sha256"], "kind": kind,
               "v1": v1, "max_edge": max_edge, "key": key, "recipe_hash": rhash,
               "wb": preview.wb_mode(v2) if v2 else "daylight", "captured_at": meta.get("captured_at"),
               "seed_ids": ("web", "web", row["sha256"])}
        get_lane().submit(job, f"{stream}:{kind}")
        return {"preview_id": key, "recipe_hash": rhash, "status_url": f"{API}/previews/{key}",
                "image_url": f"{API}/previews/{key}/image", **get_lane().status(store.root, key)}

    def preview_key_ok(pid: str) -> str:
        if len(pid) != 64 or any(ch not in "0123456789abcdef" for ch in pid):
            raise ApiError(404, "UNKNOWN_PREVIEW", "")
        return pid

    @app.get(f"{API}/previews/{{preview_id}}")
    def preview_status(preview_id: str, _t: str = Depends(session)):
        key = preview_key_ok(preview_id)
        st = get_lane().status(store.root, key)
        if st["status"] == "UNKNOWN":
            raise ApiError(404, "UNKNOWN_PREVIEW", key)
        return {"preview_id": key, **st}

    @app.get(f"{API}/previews/{{preview_id}}/image")
    def preview_image(preview_id: str, _t: str = Depends(session)):
        key = preview_key_ok(preview_id)
        f = store.root / "web-previews" / "img" / f"{key}.jpg"
        if not f.is_file():
            raise ApiError(404, "PREVIEW_NOT_READY", key)
        return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    # ---- jobs and renders (docs/web/31) --------------------------------------------------------
    def job_id_ok(jid: str) -> str:
        if len(jid) != 32 or any(ch not in "0123456789abcdef" for ch in jid):
            raise ApiError(404, "UNKNOWN_JOB", "")
        return jid

    @app.post(f"{API}/jobs", status_code=202)
    async def create_job(request: Request, response: Response, _t: str = Depends(session), c=Depends(conn)):
        try:
            body = json.loads(await request.body())
        except ValueError:
            raise ApiError(400, "BAD_REQUEST", "JSON body required") from None
        try:
            jid, created = jobs.create_job(c, bundle(), body)
        except recipe2.RecipeError as e:
            raise ApiError(422, e.code, e.detail) from None
        except jobs.JobError as e:
            raise ApiError(e.status, e.code, e.detail) from None
        if not created:
            response.status_code = 200
        return {**jobs.job_view(c, jid, items=False), "status_url": f"{API}/jobs/{jid}", "created": created}

    @app.get(f"{API}/jobs")
    def list_jobs(count: int = 50, offset: int = 0, _t: str = Depends(session), c=Depends(conn)):
        ids = [r[0] for r in c.execute("SELECT id FROM darkroom_jobs ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
                                       (max(1, min(count, 200)), max(0, offset)))]
        return {"total": c.execute("SELECT count(*) FROM darkroom_jobs").fetchone()[0],
                "items": [jobs.job_view(c, i, items=False) for i in ids]}

    @app.get(f"{API}/jobs/{{job_id}}")
    def get_job(job_id: str, _t: str = Depends(session), c=Depends(conn)):
        v = jobs.job_view(c, job_id_ok(job_id))
        if not v:
            raise ApiError(404, "UNKNOWN_JOB", job_id)
        return v

    @app.post(f"{API}/jobs/{{job_id}}/cancel", status_code=202)
    def cancel_job(job_id: str, _t: str = Depends(session), c=Depends(conn)):
        if not jobs.job_view(c, job_id_ok(job_id), items=False):
            raise ApiError(404, "UNKNOWN_JOB", job_id)
        return {"cancelled_queued_items": jobs.cancel(c, job_id)}

    @app.post(f"{API}/jobs/{{job_id}}/retry", status_code=202)
    def retry_job(job_id: str, _t: str = Depends(session), c=Depends(conn)):
        if not jobs.job_view(c, job_id_ok(job_id), items=False):
            raise ApiError(404, "UNKNOWN_JOB", job_id)
        return {"requeued_items": jobs.retry(c, job_id)}

    def render_row(c, render_id: str) -> sqlite3.Row:
        if len(render_id) != 64 or any(ch not in "0123456789abcdef" for ch in render_id):
            raise ApiError(404, "UNKNOWN_RENDER", "")
        r = c.execute("SELECT w.*, s.filename FROM web_renders w JOIN sources s ON s.id=w.source_id WHERE w.id=?",
                      (render_id,)).fetchone()
        if not r:
            raise ApiError(404, "UNKNOWN_RENDER", render_id)
        return r

    def download_name(filename: str, rid: str, film: str) -> str:
        stem = Path(filename).stem
        return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in f"{stem}_{film}_{rid[:8]}") + ".jpg"

    @app.get(f"{API}/renders/{{render_id}}/file")
    def render_file(render_id: str, _t: str = Depends(session), c=Depends(conn)):
        r = render_row(c, render_id)
        film = json.loads(r["recipe"])["film"]["id"]
        return FileResponse(store.root / r["path"], media_type="image/jpeg",
                            filename=download_name(r["filename"], r["id"], film),
                            headers={"X-Asset-SHA256": r["sha256"], "Cache-Control": "private"})

    @app.get(f"{API}/jobs/{{job_id}}/zip")
    def job_zip(job_id: str, _t: str = Depends(session), c=Depends(conn)):
        import tempfile
        import zipfile

        from starlette.background import BackgroundTask
        job_id_ok(job_id)
        rows = c.execute("SELECT w.*, s.filename FROM darkroom_items i JOIN web_renders w ON w.id=i.render_id "
                         "JOIN sources s ON s.id=i.source_id WHERE i.job_id=? AND i.state='COMPLETE' "
                         "ORDER BY i.ordinal", (job_id,)).fetchall()
        if not rows:
            raise ApiError(404, "NOTHING_TO_DOWNLOAD", "no finished frames in this job")
        fd, tmp = tempfile.mkstemp(prefix="web-zip-", dir=store.root / "incoming")
        used: set[str] = set()
        with os.fdopen(fd, "wb") as fh, zipfile.ZipFile(fh, "w", zipfile.ZIP_STORED) as z:   # JPEGs do not compress
            for r in rows:
                name = download_name(r["filename"], r["id"], json.loads(r["recipe"])["film"]["id"])
                while name in used:
                    name = "dup_" + name
                used.add(name)
                z.write(store.root / r["path"], name)
        return FileResponse(tmp, media_type="application/zip", filename=f"mfilm-{job_id[:8]}.zip",
                            background=BackgroundTask(lambda: Path(tmp).unlink(missing_ok=True)))

    @app.get(f"{API}/history")
    def history(asset_id: str | None = None, count: int = 100, offset: int = 0,
                _t: str = Depends(session), c=Depends(conn)):
        rows = c.execute(
            "SELECT w.id, w.source_id, w.recipe_hash, w.recipe, w.width, w.height, w.bytes, w.sha256, w.created_at, s.filename "
            "FROM web_renders w JOIN sources s ON s.id=w.source_id WHERE (?1 IS NULL OR w.source_id=?1) "
            "ORDER BY w.created_at DESC, w.id LIMIT ?2 OFFSET ?3", (asset_id, max(1, min(count, 500)), max(0, offset)))
        out = []
        for r in rows:
            rc = json.loads(r["recipe"])
            out.append({"render_id": r["id"], "asset_id": r["source_id"], "filename": r["filename"],
                        "film": rc["film"]["id"], "camera_look": rc["camera_look"]["id"],
                        "optical": rc["optical"]["preset_id"], "recipe_hash": r["recipe_hash"], "width": r["width"],
                        "height": r["height"], "bytes": r["bytes"], "sha256": r["sha256"], "created_at": r["created_at"]})
        return {"items": out}

    return app


def main(argv: list[str] | None = None) -> int:
    import argparse

    import uvicorn
    ap = argparse.ArgumentParser(prog="mfilm-web")
    ap.add_argument("--config")
    ap.add_argument("--data-dir")
    ap.add_argument("--host", default="127.0.0.1", help="bind address (LAN only unless behind an HTTPS proxy)")
    ap.add_argument("--port", type=int, default=8766)
    a = ap.parse_args(argv)
    cfg = config_mod.load(a.config)
    store = Store(Path(a.data_dir or os.environ.get("MFILM_DATA_DIR") or cfg.data_dir))
    uvicorn.run(create_app(store, cfg), host=a.host, port=a.port, log_level="info", access_log=False)
    return 0
