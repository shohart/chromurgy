# SPDX-License-Identifier: GPL-2.0-only
"""mfilm-web: the Web Darkroom backend-for-frontend (docs/web/33, contracts/v0.5/openapi-web-darkroom.yaml).

A separate app from the camera receiver (mfilm-receiver): different port, a
different credential (operator login, not device tokens), same store/catalog."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from .. import config as config_mod
from .. import core, db
from ..bundles import Bundles
from ..store import Store, UnsafePath, safe_id
from . import auth, catalog, engine, recipe2, sources

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
    app = FastAPI(title="M-Film Web Darkroom", version="0.5-draft", docs_url=None, redoc_url=None)
    c0 = db.connect(store.db_path)
    db.migrate(c0)
    c0.close()
    try:
        if not Bundles(store).has(engine.current_bundle().sha256):
            Bundles(store).ensure_default()
    except core.CoreError:
        pass
    app.state.store, app.state.cfg = store, cfg

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
        if not isinstance(pw, str) or not auth.check_password(store, pw):
            time.sleep(0.7)
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
        with open(p, "r+b" if p.exists() else "w+b") as f:
            f.truncate(u["offset_bytes"])
            f.seek(u["offset_bytes"])
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
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
