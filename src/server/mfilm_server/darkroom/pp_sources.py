# SPDX-License-Identifier: GPL-2.0-only
"""PhotoPrism photos as Darkroom sources (docs/web/29): resolve a photo to its RAW original on the
read-only originals mount, snapshot its identity (size, mtime, SHA-256, PhotoPrism SHA-1) and register
it as an immutable source. Never copies, moves or modifies the original."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from ..config import PhotoPrism as Cfg
from ..ids import sha256_file
from ..store import Store
from . import photoprism as pp
from . import sources


def asset_id(file_uid: str) -> str:
    return f"pp_{file_uid}"


def classify(detail: dict) -> tuple[dict | None, str | None]:
    """(raw file, None) or (None, reason) for the browser's eligibility badge. No disk access."""
    return pp.raw_file_of(detail)


def pp_thumb_paths(store: Store, thumb_hash: str, size: str = "tile_500") -> tuple[Path, Path]:
    d = store.root / "web-previews" / "pp-thumb"
    return d / f"{thumb_hash}-{size}.jpg", d / f"{thumb_hash}-{size}.json"


def sync_thumb_file(store: Store, client: pp.Client | None, thumb_hash: str, updated_at: str = "",
                    size: str = "tile_500", force: bool = False) -> tuple[Path, str]:
    """Fetch and cache a PhotoPrism thumbnail on disk, re-fetching whenever updated_at changes or force=True."""
    if not isinstance(thumb_hash, str) or len(thumb_hash) != 40 or not thumb_hash.isalnum():
        raise pp.PPError("BAD_THUMB_HASH", str(thumb_hash), 400)
    if size not in pp.THUMB_SIZES:
        raise pp.PPError("BAD_THUMB_SIZE", size, 400)
    jpg_path, meta_path = pp_thumb_paths(store, thumb_hash, size)
    meta: dict = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            meta = {}
    need_sync = (force or not jpg_path.is_file() or not meta
                 or (bool(updated_at) and meta.get("updated_at") != updated_at))
    if need_sync and client is not None:
        try:
            data = client.thumb(thumb_hash, size=size)
            jpg_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_jpg = jpg_path.with_suffix(f".{os.getpid()}.tmp")
            tmp_jpg.write_bytes(data)
            os.replace(tmp_jpg, jpg_path)
            meta = {"thumb_hash": thumb_hash, "updated_at": updated_at or meta.get("updated_at", ""),
                    "sha1": hashlib.sha1(data, usedforsecurity=False).hexdigest(), "synced_at": time.time()}
            tmp_meta = meta_path.with_suffix(f".{os.getpid()}.tmp")
            tmp_meta.write_text(json.dumps(meta, sort_keys=True))
            os.replace(tmp_meta, meta_path)
        except pp.PPError:
            if not jpg_path.is_file():
                raise
    if not jpg_path.is_file():
        raise pp.PPError("THUMB_UNAVAILABLE", thumb_hash, 404)
    ver = hashlib.sha1(f"{thumb_hash}:{meta.get('updated_at', '')}:{meta.get('sha1', '')}".encode(),
                       usedforsecurity=False).hexdigest()[:16]
    return jpg_path, ver


def _copy_to_source_thumb(store: Store, sha: str, src_jpg: Path) -> None:
    td = sources.thumb_path(store, sha)
    td.parent.mkdir(parents=True, exist_ok=True)
    tmp = td.with_suffix(f".{os.getpid()}.tmp")
    shutil.copyfile(src_jpg, tmp)
    os.replace(tmp, td)


def snapshot(conn: sqlite3.Connection, store: Store, cfg: Cfg, detail: dict,
             client: pp.Client | None = None) -> tuple[sqlite3.Row | None, str | None]:
    """Register one photo's RAW as a source. Returns (row, None) or (None, reason)."""
    f, why = classify(detail)
    if not f:
        return None, why
    root = pp.originals_root(cfg)
    if not root or not root.is_dir():
        return None, "originals are not readable from this host (photoprism.originals_dir)"
    aid = asset_id(f["UID"])
    try:
        path = pp.local_original(root, f["Name"])
        st = path.stat()
    except (pp.PPError, OSError) as e:
        return None, f"original not readable: {getattr(e, 'detail', e)}"
    if st.st_size != f["Size"]:
        return None, f"on-disk size {st.st_size} differs from PhotoPrism's record {f['Size']}"
    th, upd = pp.thumb_info(detail=detail)
    have = conn.execute("SELECT * FROM sources WHERE id=?", (aid,)).fetchone()
    snap = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
    if have:
        old_prov = json.loads(have["provenance"] or "{}")
        if old_prov.get("snapshot") == snap:
            if (th and old_prov.get("pp_thumb_hash") != th) or (upd and old_prov.get("pp_updated_at") != upd):
                old_prov["pp_thumb_hash"] = th or old_prov.get("pp_thumb_hash")
                old_prov["pp_updated_at"] = upd
                old_prov["pp_checked_at"] = time.time()
                conn.execute("UPDATE sources SET provenance=? WHERE id=?",
                             (json.dumps(old_prov, sort_keys=True), aid))
                if client is not None and old_prov.get("pp_thumb_hash"):
                    try:
                        jp, _ = sync_thumb_file(store, client, old_prov["pp_thumb_hash"], updated_at=upd, force=True)
                        _copy_to_source_thumb(store, have["sha256"], jp)
                    except pp.PPError:
                        pass
                have = conn.execute("SELECT * FROM sources WHERE id=?", (aid,)).fetchone()
            return have, None                               # unchanged since last selection
    sha1 = pp.sha1_file(path)
    if sha1 != f["Hash"]:
        return None, "file content differs from PhotoPrism's record (re-index needed?)"
    sha, nbytes = sha256_file(path)
    tpart = store.root / "incoming" / f"pp-{aid}.thumb"
    res = sources.probe(path, tpart)
    if not res["ok"]:
        tpart.unlink(missing_ok=True)
        return None, f"{res['code']}: {res.get('detail', '')}"[:300]
    meta = res["meta"]
    fmt = meta["format"]
    if fmt not in ("dng", "nef"):
        tpart.unlink(missing_ok=True)
        return None, f"{meta.get('make')} {meta.get('model')}: only DNG and Nikon NEF are verified"
    if meta.pop("has_thumb", False) and tpart.is_file():
        td = sources.thumb_path(store, sha)
        td.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tpart, td)
    tpart.unlink(missing_ok=True)
    if client is not None and (th or f.get("Hash")):
        try:
            jp, _ = sync_thumb_file(store, client, th or f["Hash"], updated_at=upd)
            _copy_to_source_thumb(store, sha, jp)
        except pp.PPError:
            pass
    meta.pop("is_dng", None)
    meta["warnings"] = []
    prov = {"origin": "photoprism", "photo_uid": detail["UID"], "file_uid": f["UID"], "file_name": f["Name"],
            "photoprism_sha1": f["Hash"], "pp_thumb_hash": th or f["Hash"], "pp_updated_at": upd,
            "pp_checked_at": time.time(), "snapshot": snap}
    conn.execute("INSERT INTO sources(id, sha256, origin, filename, format, bytes, path, meta, provenance) "
                 "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET sha256=excluded.sha256, bytes=excluded.bytes,"
                 " meta=excluded.meta, provenance=excluded.provenance",
                 (aid, sha, "photoprism", sources.display_name(Path(f["Name"]).name), fmt, nbytes, f"pp:{f['Name']}",
                  json.dumps(meta, sort_keys=True), json.dumps(prov, sort_keys=True)))
    return conn.execute("SELECT * FROM sources WHERE id=?", (aid,)).fetchone(), None


def sync_source_thumb(conn: sqlite3.Connection, store: Store, row: sqlite3.Row,
                      client: pp.Client | None, force: bool = False) -> Path | None:
    """Ensure a PhotoPrism-backed source's thumbnail is synced from PhotoPrism and up to date."""
    prov = json.loads(row["provenance"] or "{}")
    photo_uid = prov.get("photo_uid")
    th = prov.get("pp_thumb_hash") or prov.get("photoprism_sha1")
    upd = prov.get("pp_updated_at", "")
    checked_at = float(prov.get("pp_checked_at") or 0.0)
    if client is not None and photo_uid and (force or not prov.get("pp_thumb_hash") or (time.time() - checked_at) > 2.0):
        try:
            det = client.photo(photo_uid)
            new_th, new_upd = pp.thumb_info(detail=det)
            if new_th:
                if new_th != prov.get("pp_thumb_hash") or new_upd != prov.get("pp_updated_at"):
                    force = True
                th, upd = new_th, new_upd
                prov["pp_thumb_hash"] = th
                prov["pp_updated_at"] = upd
                prov["pp_checked_at"] = time.time()
                conn.execute("UPDATE sources SET provenance=? WHERE id=?",
                             (json.dumps(prov, sort_keys=True), row["id"]))
        except pp.PPError:
            pass
    if client is not None and th:
        try:
            jp, _ = sync_thumb_file(store, client, th, updated_at=upd, size="tile_500", force=force)
            _copy_to_source_thumb(store, row["sha256"], jp)
            return jp
        except pp.PPError:
            pass
    fallback = sources.thumb_path(store, row["sha256"])
    return fallback if fallback.is_file() else None


def source_file(store: Store, cfg: Cfg, row: sqlite3.Row) -> Path:
    """Where the original of a source lives. Raises FileNotFoundError / PPError."""
    if row["origin"] == "photoprism":
        root = pp.originals_root(cfg)
        if not root:
            raise FileNotFoundError("photoprism originals are not configured")
        return pp.local_original(root, row["path"][3:])
    return store.root / row["path"]
