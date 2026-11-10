# SPDX-License-Identifier: GPL-2.0-only
"""MFilmCommandBus: typed application service facade for MCP and Web Darkroom (docs/38, docs/43)."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .. import config as config_mod
from .. import core, db
from ..darkroom import (
    analysis,
    catalog,
    combos,
    cropping,
    engine,
    grades,
    grades_catalog,
    jobs,
    photoprism,
    pp_sources,
    preview,
    publish,
    recipe2,
    sources,
    wb,
)
from ..store import Store
from . import drafts
from .errors import (
    AssetNotFoundError,
    ConflictRevisionError,
    JobUnknownError,
    McpDomainError,
    PhotoPrismUnavailableError,
    PublishNotApprovedError,
    QuotaExceededError,
    RecipeInvalidError,
    RenderFailedError,
    UnknownProfileError,
)

MCP_ADAPTER_VERSION = "0.8.0"
RECIPE_SCHEMA_VERSION = 2


class MFilmCommandBus:
    def __init__(
        self,
        store: Store,
        config: config_mod.Config | None = None,
        bundle: core.Bundle | None = None
    ):
        self.store = store
        self.config = config or config_mod.Config()
        self._bundle = bundle
        # Ensure database is migrated
        conn = self.get_connection()
        db.migrate(conn)
        conn.close()

    @property
    def bundle(self) -> core.Bundle:
        if self._bundle is None:
            self._bundle = engine.current_bundle()
        return self._bundle

    def get_connection(self) -> sqlite3.Connection:
        conn = db.connect(self.store.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _wb_lookup(self, name: str) -> dict[str, Any] | None:
        conn = self.get_connection()
        try:
            return wb.lookup(conn, name)
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 1. System status
    # -------------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        conn = self.get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT count(*) FROM sources")
            source_count = c.fetchone()[0]
            c.execute("SELECT count(*) FROM darkroom_jobs")
            job_count = c.fetchone()[0]
            c.execute("SELECT count(*) FROM mcp_drafts")
            draft_count = c.fetchone()[0]
        finally:
            conn.close()

        cat = catalog.build(self.bundle)
        pp_cfg = self.config.photoprism
        pp_ready = bool(pp_cfg and (pp_cfg.url or pp_cfg.export_dir or pp_cfg.originals_dir))

        return {
            "mcp_adapter_version": MCP_ADAPTER_VERSION,
            "recipe_schema_version": RECIPE_SCHEMA_VERSION,
            "renderer_build": "native-c",
            "catalog_bundle_version": self.bundle.sha256[:16],
            "service_health": "OK",
            "photoprism": {
                "configured": pp_ready,
                "instance_id": getattr(pp_cfg, "instance_id", None) if pp_ready else None,
                "web_folder": pp_cfg.web_folder if pp_ready else None
            },
            "counts": {
                "sources": source_count,
                "jobs": job_count,
                "drafts": draft_count,
                "camera_looks": len(cat.get("camera_looks", [])),
                "film_stocks": len(cat.get("films", [])),
                "curated_combos": len(combos.document().get("presets", [])),
                "color_grades": len(grades_catalog.CATALOG_PRESETS)
            }
        }

    # -------------------------------------------------------------------------
    # 2. Source & asset discovery
    # -------------------------------------------------------------------------
    def list_sources(
        self,
        kind: str | None = None,
        cursor: str | None = None,
        limit: int = 50
    ) -> dict[str, Any]:
        limit = max(1, min(100, limit))
        conn = self.get_connection()
        try:
            query = "SELECT DISTINCT origin FROM sources"
            params: list[Any] = []
            if kind:
                origin = {"mfilm_library": "camera_roll", "roll": "camera_roll", "upload": "upload", "photoprism": "photoprism"}.get(kind, kind)
                query += " WHERE origin = ?"
                params.append(origin)
            cur = conn.cursor()
            cur.execute(query, params)
            origins = [r[0] for r in cur.fetchall()]

            items = []
            for o in origins:
                cur.execute("SELECT count(*) FROM sources WHERE origin = ?", (o,))
                cnt = cur.fetchone()[0]
                k = {"upload": "upload", "photoprism": "photoprism", "camera_roll": "roll"}.get(o, o)
                items.append({
                    "id": f"src_{o}",
                    "kind": k,
                    "title": o.capitalize().replace("_", " "),
                    "asset_count": cnt
                })
            return {"items": items, "total": len(items)}
        finally:
            conn.close()

    def search_assets(
        self,
        source: str,
        query: str | None = None,
        album_uid: str | None = None,
        folder_id: str | None = None,
        camera_model: str | None = None,
        format: str | None = None,
        cursor: str | None = None,
        limit: int = 50
    ) -> dict[str, Any]:
        limit = max(1, min(100, limit))
        origin = {"mfilm_library": "camera_roll", "roll": "camera_roll", "upload": "upload", "photoprism": "photoprism"}.get(source, source)
        conn = self.get_connection()
        try:
            sql = "SELECT id, sha256, origin, filename, format, bytes, eligible, reason, meta FROM sources WHERE 1=1"
            params: list[Any] = []

            if origin != "all":
                sql += " AND origin = ?"
                params.append(origin)

            if format:
                sql += " AND format = ?"
                params.append(format.lower())

            if query:
                sql += " AND (filename LIKE ? OR meta LIKE ?)"
                q_like = f"%{query}%"
                params.extend([q_like, q_like])

            if cursor:
                sql += " AND id > ?"
                params.append(cursor)

            sql += " ORDER BY id ASC LIMIT ?"
            params.append(limit + 1)

            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()

            has_more = len(rows) > limit
            items_raw = rows[:limit]
            next_cursor = items_raw[-1]["id"] if has_more and items_raw else None

            results = []
            for r in items_raw:
                meta = json.loads(r["meta"] or "{}")
                if camera_model and camera_model.lower() not in (meta.get("model") or "").lower():
                    continue
                results.append({
                    "asset_id": r["id"],
                    "sha256": r["sha256"],
                    "filename": r["filename"],
                    "format": r["format"],
                    "bytes": r["bytes"],
                    "eligible": bool(r["eligible"]),
                    "reason": r["reason"],
                    "origin": r["origin"],
                    "meta": {
                        "model": meta.get("model"),
                        "width": meta.get("width"),
                        "height": meta.get("height"),
                        "iso": meta.get("iso"),
                        "baseline_ev": meta.get("baseline_ev", 0.0),
                        "auto_exposure_ev": meta.get("auto_exposure_ev"),
                        "has_thumb": bool(meta.get("has_thumb"))
                    }
                })

            return {
                "items": results,
                "count": len(results),
                "next_cursor": next_cursor
            }
        finally:
            conn.close()

    def inspect_asset(self, asset_id: str) -> dict[str, Any]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, sha256, origin, filename, format, bytes, eligible, reason, meta FROM sources WHERE id = ?", (asset_id,))
            r = cur.fetchone()
            if not r:
                raise AssetNotFoundError(asset_id)

            meta = json.loads(r["meta"] or "{}")
            return {
                "asset_id": r["id"],
                "sha256": r["sha256"],
                "origin": r["origin"],
                "filename": r["filename"],
                "format": r["format"],
                "bytes": r["bytes"],
                "eligible": bool(r["eligible"]),
                "reason": r["reason"],
                "meta": meta,
                "supported_edit_features": {
                    "exposure_compensation": True,
                    "white_balance": True,
                    "camera_looks": True,
                    "film_stocks": True,
                    "optical_effects": True,
                    "color_grades": True,
                    "crop_and_rotate": True
                }
            }
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 3. Creative options & schema
    # -------------------------------------------------------------------------
    def list_creative_options(
        self,
        type: str | None = None,
        query: str | None = None,
        cursor: str | None = None,
        limit: int = 100
    ) -> dict[str, Any]:
        limit = max(1, min(200, limit))
        cat = catalog.build(self.bundle)
        items: list[dict[str, Any]] = []

        q = query.lower() if query else None

        # Camera Looks
        if not type or type == "camera_look":
            for cl in cat.get("camera_looks", []):
                if q and q not in cl["id"].lower() and q not in cl.get("label", "").lower():
                    continue
                items.append({
                    "id": cl["id"],
                    "type": "camera_look",
                    "label": cl.get("label", cl["id"]),
                    "category": cl.get("category", "camera_look"),
                    "version": cl.get("version", "1"),
                    "supported": cl.get("supported", True)
                })

        # Film Stocks
        if not type or type == "film":
            for f in cat.get("films", []):
                if q and q not in f["id"].lower() and q not in f.get("name", "").lower():
                    continue
                items.append({
                    "id": f["id"],
                    "type": "film",
                    "label": f.get("name", f["id"]),
                    "category": f.get("category", "film_stock"),
                    "group": f.get("group", ""),
                    "version": "1"
                })

        # Optical Effects
        if not type or type == "optical":
            for ox in cat.get("optical_effects", []):
                if q and q not in ox["id"].lower() and q not in ox.get("name", "").lower():
                    continue
                items.append({
                    "id": ox["id"],
                    "type": "optical",
                    "label": ox.get("name", ox["id"]),
                    "category": ox.get("category", "optical"),
                    "params": ox.get("params", [])
                })

        # Curated Combos
        if not type or type == "combo":
            for cb in combos.list_view(self.bundle):
                cid = cb.get("id", "")
                clabel = cb.get("name", cid)
                if q and q not in cid.lower() and q not in clabel.lower():
                    continue
                items.append({
                    "id": cid,
                    "type": "combo",
                    "label": clabel,
                    "category": "combo",
                    "provenance": cb.get("provenance", {}),
                    "camera_look": cb.get("camera_look", {}),
                    "film_stock": cb.get("film", {}),
                    "optical_effects": cb.get("optical", {})
                })

        # Color Grades
        if not type or type == "grade":
            for gr in grades_catalog.CATALOG_PRESETS:
                gid = gr["id"]
                gname = gr.get("name", gid)
                if q and q not in gid.lower() and q not in gname.lower():
                    continue
                items.append({
                    "id": gid,
                    "type": "grade",
                    "label": gname,
                    "category": gr.get("category", "creative_color_grade"),
                    "style_tags": gr.get("tags", []),
                    "params": gr.get("parameters", {})
                })

        return {
            "items": items[:limit],
            "total": len(items)
        }

    def get_recipe_schema(self, schema_version: int = 2) -> dict[str, Any]:
        schema_path = Path(__file__).resolve().parent.parent.parent.parent / "contracts" / "render-recipe-v2.schema.json"
        if schema_path.is_file():
            try:
                return json.loads(schema_path.read_text())
            except Exception:
                pass
        return {
            "schema_version": 2,
            "type": "object",
            "required": ["schema_version", "camera_look", "film"],
            "properties": {
                "schema_version": {"type": "integer", "enum": [2]},
                "camera_look": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}, "strength": {"type": "number", "minimum": 0, "maximum": 1}}},
                "film": {"type": "object", "required": ["stock"], "properties": {"stock": {"type": "string"}, "strength": {"type": "number", "minimum": 0, "maximum": 1}}},
                "optical": {"type": "object", "properties": {"stack": {"type": "array", "items": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}, "strength": {"type": "number"}}}}}},
                "color_grade": {"type": "object", "properties": {"mode": {"type": "string"}, "preset_id": {"type": "string"}, "strength": {"type": "number"}}},
                "tone": {"type": "object", "properties": {"brightness": {"type": "number"}, "contrast": {"type": "number"}, "develop": {"type": "number"}, "filter": {"type": "string"}}},
                "wb": {"type": "string"},
                "seed": {"type": "integer"}
            }
        }

    # -------------------------------------------------------------------------
    # 4. PhotoPrism destinations
    # -------------------------------------------------------------------------
    def list_photoprism_destinations(
        self,
        instance_id: str | None = None,
        kind: str = "album",
        query: str | None = None,
        cursor: str | None = None
    ) -> dict[str, Any]:
        pp_cfg = self.config.photoprism
        if not pp_cfg or not (pp_cfg.url or pp_cfg.import_dir or pp_cfg.originals_dir):
            raise PhotoPrismUnavailableError("PhotoPrism is not configured on this server")

        client = photoprism.Client(pp_cfg.url, pp_cfg.token) if pp_cfg.url and pp_cfg.token else None
        items: list[dict[str, Any]] = []

        if kind == "album":
            albums = photoprism.list_albums(client)
            for a in albums:
                title = a.get("Title") or a.get("title") or "Unnamed Album"
                uid = a.get("UID") or a.get("uid") or ""
                if query and query.lower() not in title.lower():
                    continue
                items.append({
                    "kind": "album",
                    "album_uid": uid,
                    "title": title,
                    "writable": True
                })
        elif kind == "folder":
            folders = photoprism.list_folders(self.store, pp_cfg, client)
            for f in folders:
                name = f if isinstance(f, str) else f.get("name", "")
                if query and query.lower() not in name.lower():
                    continue
                items.append({
                    "kind": "folder",
                    "folder_id": name,
                    "title": name,
                    "writable": True
                })

        return {
            "items": items,
            "count": len(items)
        }

    # -------------------------------------------------------------------------
    # 5. Recipe drafts
    # -------------------------------------------------------------------------
    def create_draft(
        self,
        asset_id: str,
        preset_id: str | None = None,
        recipe: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        conn = self.get_connection()
        try:
            return drafts.create_draft(conn, self.bundle, asset_id, preset_id=preset_id, recipe=recipe)
        finally:
            conn.close()

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        conn = self.get_connection()
        try:
            return drafts.get_draft(conn, draft_id)
        finally:
            conn.close()

    def update_draft(
        self,
        draft_id: str,
        expected_revision: int,
        patch: dict[str, Any]
    ) -> dict[str, Any]:
        conn = self.get_connection()
        try:
            return drafts.update_draft(conn, self.bundle, draft_id, expected_revision, patch)
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 6. Previews & comparisons
    # -------------------------------------------------------------------------
    def _resolve_source_path(self, asset_id: str) -> tuple[Path, sqlite3.Row]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM sources WHERE id = ?", (asset_id,))
            row = cur.fetchone()
            if not row:
                raise AssetNotFoundError(asset_id)

            origin = row["origin"]
            if origin == "photoprism":
                p = pp_sources.source_file(self.store, self.config.photoprism, row)
                if not p or not p.is_file():
                    raise AssetNotFoundError(asset_id, f"PhotoPrism source file missing: {row['filename']}")
                return p, row
            else:
                p = self.store.root / "sources" / row["path"]
                if not p.is_file():
                    p = Path(row["path"])
                if not p.is_file():
                    raise AssetNotFoundError(asset_id, f"Source RAW file missing: {row['filename']}")
                return p, row
        finally:
            conn.close()

    def render_preview(
        self,
        draft_id: str,
        revision: int,
        max_side: int = 1024,
        format: str = "jpeg"
    ) -> dict[str, Any]:
        draft = self.get_draft(draft_id)
        if draft["revision"] != revision:
            raise ConflictRevisionError(draft_id, expected=revision, actual=draft["revision"])

        max_side = max(128, min(1536, max_side))
        norm_r = draft["recipe"]
        v1 = recipe2.to_v1(norm_r)

        src_path, row = self._resolve_source_path(draft["asset_id"])

        wb_m = preview.wb_mode(norm_r)
        pkey = preview.preview_key(
            sha=row["sha256"],
            kind="treated",
            recipe_hash=draft["recipe_hash"],
            max_edge=max_side,
            bundle_hash=self.bundle.sha256,
            wb=wb_m,
            rotate=norm_r.get("rotate"),
            crop=norm_r.get("crop")
        )
        job = {
            "root": str(self.store.root),
            "src_path": str(src_path),
            "sha": row["sha256"],
            "kind": "treated",
            "v2": norm_r,
            "v1": v1,
            "max_edge": max_side,
            "key": pkey,
            "recipe_hash": draft["recipe_hash"],
            "captured_at": None,
            "wb": wb_m,
            "rotate": norm_r.get("rotate", 0),
            "crop": norm_r.get("crop"),
            "seed_ids": ("mcp", "preview", row["sha256"])
        }

        res = preview.render(job)
        if res.get("failed"):
            raise RenderFailedError(res.get("detail", "Preview rendering failed"))

        out_file = self.store.root / "web-previews" / "img" / f"{pkey}.jpg"
        if not out_file.is_file():
            raise RenderFailedError(f"Preview image missing at {out_file}")

        img_bytes = out_file.read_bytes()
        img_b64 = base64.b64encode(img_bytes).decode("ascii")

        meta_info = {
            "draft_id": draft_id,
            "revision": revision,
            "asset_id": draft["asset_id"],
            "recipe_hash": draft["recipe_hash"],
            "source_sha256": row["sha256"],
            "width": res.get("width"),
            "height": res.get("height"),
            "format": format.lower(),
            "cached": bool(res.get("cached", False)),
            "elapsed_s": res.get("elapsed_s")
        }

        return {
            "content": [
                {
                    "type": "image",
                    "data": img_b64,
                    "mimeType": "image/jpeg"
                },
                {
                    "type": "text",
                    "text": json.dumps(meta_info, indent=2)
                }
            ],
            "structuredContent": meta_info,
            "isError": False
        }

    def compare_drafts(
        self,
        draft_ids: list[str],
        max_side: int = 720,
        layout: str = "separate"
    ) -> dict[str, Any]:
        if len(draft_ids) < 2 or len(draft_ids) > 4:
            raise QuotaExceededError("mfilm_compare_drafts accepts between 2 and 4 drafts")

        max_side = max(128, min(1536, max_side))
        content: list[dict[str, Any]] = []
        variants: list[dict[str, Any]] = []

        for did in draft_ids:
            d = self.get_draft(did)
            pv = self.render_preview(did, d["revision"], max_side=max_side)
            # Find the image block
            img_block = next((c for c in pv["content"] if c["type"] == "image"), None)
            if img_block:
                content.append({
                    "type": "text",
                    "text": f"--- Variant Draft: {did} (rev {d['revision']}) | Look: {d['recipe'].get('camera_look', {}).get('id')} | Film: {d['recipe'].get('film', {}).get('stock')} | Hash: {d['recipe_hash'][:12]} ---"
                })
                content.append(img_block)
            variants.append({
                "draft_id": did,
                "revision": d["revision"],
                "recipe_hash": d["recipe_hash"],
                "camera_look": d["recipe"].get("camera_look", {}).get("id"),
                "film_stock": d["recipe"].get("film", {}).get("stock")
            })

        return {
            "content": content,
            "structuredContent": {"variants": variants},
            "isError": False
        }

    # -------------------------------------------------------------------------
    # 7. Durable Development & Jobs
    # -------------------------------------------------------------------------
    def start_development(
        self,
        draft_id: str,
        revision: int,
        idempotency_key: str,
        output: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        draft = self.get_draft(draft_id)
        if draft["revision"] != revision:
            raise ConflictRevisionError(draft_id, expected=revision, actual=draft["revision"])

        src_path, row = self._resolve_source_path(draft["asset_id"])

        origin = row["origin"]
        kind = {"upload": "upload", "photoprism": "photoprism_folder", "camera_roll": "mfilm_roll"}.get(origin, "upload")

        out_spec = {
            "format": "jpeg",
            "quality": 95,
            "publish": False,
            **(output or {})
        }

        req = {
            "schema_version": 1,
            "source": {
                "kind": kind,
                "assets": [{"asset_id": row["id"]}]
            },
            "recipe": draft["recipe"],
            "output": out_spec,
            "idempotency_key": idempotency_key
        }

        conn = self.get_connection()
        try:
            jid, created = jobs.create_job(
                conn,
                self.bundle,
                req,
                self.config.photoprism.web_folder if self.config.photoprism else "M-Film/Developed",
                self._wb_lookup
            )
            view = jobs.job_view(conn, jid, items=True) or {}
            return {
                "job_id": jid,
                "created": created,
                "state": view.get("state", "QUEUED"),
                "recipe_hash": draft["recipe_hash"],
                "items_count": len(view.get("items", []))
            }
        finally:
            conn.close()

    def get_job(self, job_id: str) -> dict[str, Any]:
        conn = self.get_connection()
        try:
            view = jobs.job_view(conn, job_id, items=True)
            if not view:
                raise JobUnknownError(job_id)

            # Check if there are rendered outputs
            render_ids = [it.get("render_id") for it in view.get("items", []) if it.get("render_id")]
            return {
                "job_id": job_id,
                "state": view.get("state"),
                "counts": view.get("counts", {}),
                "items": view.get("items", []),
                "render_ids": render_ids,
                "cancel_requested": bool(view.get("cancel_requested", 0))
            }
        finally:
            conn.close()

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        conn = self.get_connection()
        try:
            cancelled = jobs.cancel(conn, job_id)
            view = jobs.job_view(conn, job_id, items=False) or {}
            return {
                "job_id": job_id,
                "cancelled": bool(cancelled),
                "state": view.get("state")
            }
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # 8. Publication to PhotoPrism
    # -------------------------------------------------------------------------
    def publish_render(
        self,
        render_id: str,
        destination: dict[str, Any],
        idempotency_key: str,
        approval_token: str | None = None
    ) -> dict[str, Any]:
        pp_cfg = self.config.photoprism
        if not pp_cfg or not (pp_cfg.url or pp_cfg.import_dir or pp_cfg.originals_dir):
            raise PhotoPrismUnavailableError("PhotoPrism is not configured on this server")

        folder_id = destination.get("folder_id")
        if not folder_id:
            raise McpDomainError("INVALID_DESTINATION", "destination.folder_id is required")

        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM web_renders WHERE id = ?", (render_id,))
            r = cur.fetchone()
            if not r:
                raise McpDomainError("RENDER_NOT_FOUND", f"Render '{render_id}' not found")

            cur.execute("SELECT * FROM sources WHERE id = ?", (r["source_id"],))
            src = cur.fetchone()
            if not src:
                raise AssetNotFoundError(r["source_id"])

            kind = {"upload": "upload", "photoprism": "photoprism_folder", "camera_roll": "mfilm_roll"}.get(src["origin"], "upload")
            dest_spec = {
                "photoprism_folder": folder_id,
                "photoprism_album_uid": destination.get("album_uid")
            }
            recipe = json.loads(r["recipe"])
            quality = recipe.get("render", {}).get("quality", 95)

            req = {
                "schema_version": 1,
                "source": {
                    "kind": kind,
                    "assets": [{"asset_id": src["id"]}]
                },
                "recipe": recipe,
                "output": {
                    "format": "jpeg",
                    "quality": quality,
                    "publish": True,
                    **dest_spec
                },
                "idempotency_key": idempotency_key
            }

            jid, created = jobs.create_job(
                conn,
                self.bundle,
                req,
                pp_cfg.web_folder or "M-Film/Developed",
                self._wb_lookup
            )
            view = jobs.job_view(conn, jid, items=True) or {}
            return {
                "publication_job_id": jid,
                "created": created,
                "render_id": render_id,
                "state": view.get("state", "PUBLISHING"),
                "destination": destination
            }
        finally:
            conn.close()
