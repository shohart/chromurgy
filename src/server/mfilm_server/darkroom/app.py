# SPDX-License-Identifier: GPL-2.0-only
"""mfilm-web: the Web Darkroom backend-for-frontend (docs/web/33, contracts/v0.5/openapi-web-darkroom.yaml).

A separate app from the camera receiver (mfilm-receiver): different port, a
different credential (operator login, not device tokens), same store/catalog."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
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
from . import wb as wbmod
from . import auth, catalog, cropping, engine, jobs, pp_sources, preview, recipe2, rolls, sources
from . import photoprism as pp

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
    wb_lookup = wbmod.lookup(store.root)
    wb_users = wbmod.UserProfiles(store.root)
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
            r = recipe2.normalize(body, bundle(), wb_lookup)
        except recipe2.RecipeError as e:
            raise ApiError(422, e.code, e.detail) from None
        return {"recipe": r, "recipe_hash": recipe2.recipe_hash(r)}

    # ---- white-balance profiles (built-in library + imports) ------------------------------------------
    def wb_public(p: dict) -> dict:
        return {k: p.get(k) for k in ("id", "name", "kelvin", "tint", "gains", "group", "source", "builtin")}

    @app.get(f"{API}/wb-profiles")
    def get_wb_profiles(_t: str = Depends(session)):
        return {"builtin": [wb_public(p) for p in wbmod.builtins()], "imported": [wb_public(p) for p in wb_users.list()],
                "formats": [".json", ".csv", ".xmp", ".lrtemplate", ".pp3"], "reference_kelvin": wbmod.REFERENCE_K,
                "kelvin_range": list(wbmod.K_RANGE), "tint_range": list(wbmod.TINT_RANGE)}

    @app.post(f"{API}/wb-profiles")
    async def import_wb_profiles(request: Request, filename: str = "profile.json", _t: str = Depends(session)):
        data = await request.body()
        try:
            found = wbmod.parse_import(sources.display_name(filename), data)
            added = [wb_public(wb_users.add(p, sources.display_name(filename))) for p in found]
        except wbmod.WBError as e:
            raise ApiError(422, "INVALID_WB_PROFILE", str(e)) from None
        return {"added": added}

    @app.delete(f"{API}/wb-profiles/{{pid:path}}")
    def delete_wb_profile(pid: str, _t: str = Depends(session)):
        if not wb_users.delete(pid):
            raise ApiError(404, "UNKNOWN_WB_PROFILE", pid)
        return {"deleted": pid}

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
        for stale in c.execute("SELECT id FROM web_uploads WHERE state='OPEN' AND updated_at < "
                               "strftime('%Y-%m-%dT%H:%M:%fZ','now','-24 hours')").fetchall():
            part(stale[0]).unlink(missing_ok=True)          # abandoned uploads expire (docs/web/30)
            c.execute("UPDATE web_uploads SET state='ABORTED', error_code='EXPIRED' WHERE id=?", (stale[0],))
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

    @app.get(f"{API}/sources/{{asset_id}}/thumbnail")
    def source_thumbnail(asset_id: str, _t: str = Depends(session), c=Depends(conn)):
        row = source_row(c, asset_id)
        f = sources.thumb_path(store, row["sha256"])
        if not f.is_file():
            raise ApiError(404, "NO_THUMBNAIL", "this RAW has no embedded preview")
        return FileResponse(f, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

    @app.post(f"{API}/previews", status_code=202)
    async def create_preview(request: Request, _t: str = Depends(session), c=Depends(conn)):
        try:
            body = json.loads(await request.body())
            asset_id, kind = str(body["asset_id"]), body.get("kind", "treated")
            max_edge = int(body.get("max_edge", 1280))
            stream = str(body.get("stream") or "default")[:64]
            wb_req = body.get("white_balance", "daylight")
            crop_req = cropping.normalize_crop(body.get("crop"))
            rotate_req = cropping.normalize_rotate(body.get("rotate"))
        except cropping.CropError as e:
            raise ApiError(422, "INVALID_CROP", str(e)) from None
        except (ValueError, KeyError, TypeError):
            raise ApiError(400, "BAD_REQUEST", "asset_id and recipe required") from None
        if wb_req not in ("daylight", "as-shot"):
            raise ApiError(422, "INVALID_REQUEST", "white_balance: daylight|as-shot")
        if kind not in ("treated", "before") or not 320 <= max_edge <= 2048:
            raise ApiError(422, "INVALID_REQUEST", "kind: treated|before, max_edge: 320..2048")
        row = source_row(c, asset_id)
        b = bundle()
        v2 = v1 = None
        if kind == "treated":
            try:
                v2 = recipe2.normalize(body.get("recipe"), b, wb_lookup)
            except recipe2.RecipeError as e:
                raise ApiError(422, e.code, e.detail) from None
            v1 = recipe2.to_v1(v2)
        rhash = recipe2.recipe_hash(v2) if v2 else "before"
        wb = preview.wb_mode(v2) if v2 else wb_req       # the wipe's two sides share one baseline white balance
        crop = (v2.get("extensions") or {}).get("crop") if v2 else crop_req   # a treated preview crops as its recipe says
        rotate = (v2.get("extensions") or {}).get("rotate") if v2 else rotate_req
        key = preview.preview_key(sha=row["sha256"], kind=kind, recipe_hash=rhash, max_edge=max_edge,
                                  bundle_hash=b.sha256, wb=wb, crop=crop, rotate=rotate)
        meta = json.loads(row["meta"])
        job = {"root": str(store.root), "src_path": str(pp_sources.source_file(store, cfg.photoprism, row)), "sha": row["sha256"], "kind": kind,
               "v1": v1, "max_edge": max_edge, "key": key, "recipe_hash": rhash,
               "wb": wb, "crop": crop, "rotate": rotate, "captured_at": meta.get("captured_at"),
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

    # ---- PhotoPrism source browsing (docs/web/29) ----------------------------------------------------
    INSTANCE = "default"                              # one configured instance; clients never supply a URL

    def pp_client() -> pp.Client:
        try:
            return pp.Client(cfg.photoprism, transport=app.state.pp_transport) if getattr(app.state, "pp_transport", None) \
                else pp.Client(cfg.photoprism)
        except pp.PPError as e:
            raise ApiError(e.status, e.code, e.detail) from None

    def pp_call(fn, *args, **kw):
        try:
            return fn(*args, **kw)
        except pp.PPError as e:
            raise ApiError(e.status, e.code, e.detail) from None

    def instance_ok(inst: str) -> None:
        if inst != INSTANCE:
            raise ApiError(404, "UNKNOWN_INSTANCE", inst)

    @app.get(f"{API}/photoprism/instances")
    def pp_instances(_t: str = Depends(session)):
        p = cfg.photoprism
        info = {"id": INSTANCE, "name": "PhotoPrism", "configured": bool(p.url and p.token_file) or
                bool(getattr(app.state, "pp_transport", None)),
                "read": {"api": None, "originals": None}, "write": {"folder": None, "index": bool(p.index_template or p.index_command),
                                                                    "albums": None},
                "output_folder": p.web_folder}
        if not info["configured"]:
            info["error"] = "PHOTOPRISM_NOT_CONFIGURED"
            return {"items": [info]}
        try:
            c = pp_client().config()
            info["version"], info["readonly"] = c.get("version"), bool(c.get("readonly"))
            info["read"]["api"] = True
        except (pp.PPError, ApiError) as e:
            info["read"]["api"] = False
            info["error"] = getattr(e, "code", "ERROR")
        root = pp.originals_root(p)
        info["read"]["originals"] = bool(root and root.is_dir())
        info["write"]["folder"] = bool(p.export_dir and p.export_dir.is_dir())
        return {"items": [info]}

    @app.get(f"{API}/photoprism/{{inst}}/albums")
    def pp_albums(inst: str, q: str = "", count: int = 100, offset: int = 0, _t: str = Depends(session)):
        instance_ok(inst)
        return {"items": pp_call(pp_client().albums, q, max(1, min(count, 500)), max(0, offset))}

    @app.get(f"{API}/photoprism/{{inst}}/folders")
    def pp_folders(inst: str, parent_id: str = "", _t: str = Depends(session)):
        instance_ok(inst)
        if parent_id.startswith("/") or ".." in parent_id.split("/") or "\0" in parent_id:
            raise ApiError(400, "UNSAFE_PATH", parent_id)
        return {"parent": parent_id, "items": pp_call(pp_client().folders, parent_id)}

    def pp_page(client, source_kind: str, source_uid: str, count: int, offset: int) -> list[dict]:
        if source_kind == "album":
            return pp_call(client.photos, album_uid=source_uid, count=count, offset=offset)
        if source_kind == "folder":
            if source_uid.startswith("/") or ".." in source_uid.split("/"):
                raise ApiError(400, "UNSAFE_PATH", source_uid)
            return pp_call(client.photos, folder=source_uid, count=count, offset=offset)
        raise ApiError(422, "INVALID_REQUEST", "source_kind: album|folder")

    @app.get(f"{API}/photoprism/{{inst}}/photos")
    def pp_photos(inst: str, source_kind: str, source_uid: str, count: int = 60, offset: int = 0,
                  _t: str = Depends(session)):
        instance_ok(inst)
        client = pp_client()
        page = pp_page(client, source_kind, source_uid, max(1, min(count, 200)), max(0, offset))
        out = []
        for ph in page:
            item = {"photo_uid": ph["UID"], "name": ph.get("Name"), "type": ph.get("Type"), "taken_at": ph.get("TakenAt"),
                    "folder": ph.get("Path")}
            if ph.get("Type") == "raw" or ph.get("Type") in ("image", "live"):
                f, why = pp_sources.classify(pp_call(client.photo, ph["UID"]))
            else:
                f, why = None, f"{ph.get('Type')} is not a photo with a RAW original"
            item.update(eligible=bool(f), reason=why, raw={"name": f["Name"], "bytes": f["Size"]} if f else None)
            out.append(item)
        return {"count": len(out), "offset": offset, "next_offset": offset + len(page) if len(page) == count else None,
                "eligible": sum(1 for i in out if i["eligible"]), "items": out}

    @app.post(f"{API}/photoprism/{{inst}}/select")
    async def pp_select(inst: str, request: Request, _t: str = Depends(session)):
        """Snapshot the chosen photos' RAW originals (identity, hash, metadata) as sources."""
        instance_ok(inst)
        try:
            body = json.loads(await request.body())
            uids = [str(u) for u in body.get("photo_uids", [])]
            kind, suid = body.get("source_kind"), str(body.get("source_uid", ""))
            select_all = bool(body.get("all_eligible"))
        except (ValueError, AttributeError, TypeError):
            raise ApiError(400, "BAD_REQUEST", "JSON body required") from None

        def work():
            c = db.connect(store.db_path)
            try:
                client = pp_client()
                todo = list(uids)
                if select_all:
                    off = 0
                    while len(todo) < 2000:
                        page = pp_page(client, kind, suid, 200, off)
                        todo += [p["UID"] for p in page if p["UID"] not in todo]
                        if len(page) < 200:
                            break
                        off += 200
                if not todo or len(todo) > 2000:
                    raise ApiError(422, "INVALID_REQUEST", "1..2000 photos")
                assets, skipped = [], []
                for uid in todo:
                    try:
                        row, why = pp_sources.snapshot(c, store, cfg.photoprism, client.photo(uid))
                    except pp.PPError as e:
                        row, why = None, f"{e.code}: {e.detail}"
                    if row:
                        assets.append(sources.row_public(row))
                    else:
                        skipped.append({"photo_uid": uid, "reason": why})
                return {"assets": assets, "skipped": skipped, "source": {"kind": kind, "uid": suid}}
            finally:
                c.close()
        return await run_in_threadpool(work)

    # ---- M-Film camera rolls as sources -------------------------------------------------------------
    @app.get(f"{API}/rolls")
    def get_rolls(_t: str = Depends(session), c=Depends(conn)):
        return {"items": rolls.list_rolls(c)}

    @app.post(f"{API}/rolls/select")
    async def roll_select(request: Request, _t: str = Depends(session)):
        try:
            body = json.loads(await request.body())
            device, roll = str(body["device_id"]), str(body["roll_id"])
            only = [str(x) for x in body["frame_ids"]] if body.get("frame_ids") else None
        except (ValueError, KeyError, TypeError):
            raise ApiError(400, "BAD_REQUEST", "device_id and roll_id required") from None

        def work():
            c = db.connect(store.db_path)
            try:
                r = c.execute("SELECT * FROM rolls WHERE device_id=? AND id=?", (device, roll)).fetchone()
                if not r:
                    raise ApiError(404, "UNKNOWN_ROLL", roll)
                assets, skipped = [], []
                for f in rolls.roll_frames(c, device, roll):
                    if only is not None and f["id"] not in only:
                        continue
                    row, why = rolls.snapshot(c, store, device, roll, f, r["film_profile_id"])
                    if row:
                        assets.append(sources.row_public(row))
                    else:
                        skipped.append({"frame_id": f["id"], "ordinal": f["ordinal"], "reason": why})
                return {"assets": assets, "skipped": skipped, "source": {"kind": "mfilm_roll", "uid": roll}}
            finally:
                c.close()
        return await run_in_threadpool(work)

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
            jid, created = jobs.create_job(c, bundle(), body, cfg.photoprism.web_folder, wb_lookup)
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

    @app.post(f"{API}/renders/{{render_id}}/publish", status_code=202)
    async def publish_render(render_id: str, request: Request, _t: str = Depends(session), c=Depends(conn)):
        """Publish a finished render later (docs/web/32): a job over the same source and recipe whose render
        is reused byte for byte, so only the publication stages run. Repeating the same request is a no-op."""
        r = render_row(c, render_id)
        try:
            out = json.loads(await request.body() or b"{}")
        except ValueError:
            raise ApiError(400, "BAD_REQUEST", "JSON body required") from None
        src = c.execute("SELECT * FROM sources WHERE id=?", (r["source_id"],)).fetchone()
        kind = {"upload": "upload", "photoprism": "photoprism_folder", "camera_roll": "mfilm_roll"}[src["origin"]]
        dest = {k: out[k] for k in ("photoprism_folder", "photoprism_album_uid", "create_album_name") if out.get(k)}
        recipe = json.loads(r["recipe"])
        req = {"schema_version": 1, "source": {"kind": kind, "assets": [{"asset_id": src["id"]}]}, "recipe": recipe,
               "output": {"format": "jpeg", "quality": recipe["render"]["quality"], "publish": True, **dest},
               "idempotency_key": "pub-" + hashlib.sha256(f"{render_id}{json.dumps(dest, sort_keys=True)}".encode()).hexdigest()[:40]}
        try:
            jid, created = jobs.create_job(c, bundle(), req, cfg.photoprism.web_folder, wb_lookup)
        except recipe2.RecipeError as e:
            raise ApiError(422, e.code, e.detail) from None
        except jobs.JobError as e:
            raise ApiError(e.status, e.code, e.detail) from None
        return {**jobs.job_view(c, jid, items=False), "status_url": f"{API}/jobs/{jid}", "created": created}

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
                        "optical": rc["optical"]["preset_id"], "crop": (rc.get("extensions") or {}).get("crop"), "recipe_hash": r["recipe_hash"], "width": r["width"],
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
