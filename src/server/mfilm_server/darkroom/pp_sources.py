# SPDX-License-Identifier: GPL-2.0-only
"""PhotoPrism photos as Darkroom sources (docs/web/29): resolve a photo to its RAW original on the
read-only originals mount, snapshot its identity (size, mtime, SHA-256, PhotoPrism SHA-1) and register
it as an immutable source. Never copies, moves or modifies the original."""
from __future__ import annotations

import json
import os
import sqlite3
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


def snapshot(conn: sqlite3.Connection, store: Store, cfg: Cfg, detail: dict) -> tuple[sqlite3.Row | None, str | None]:
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
    have = conn.execute("SELECT * FROM sources WHERE id=?", (aid,)).fetchone()
    snap = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
    if have and json.loads(have["provenance"]).get("snapshot") == snap:
        return have, None                                   # unchanged since last selection
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
    meta.pop("is_dng", None)
    meta["warnings"] = []
    prov = {"origin": "photoprism", "photo_uid": detail["UID"], "file_uid": f["UID"], "file_name": f["Name"],
            "photoprism_sha1": f["Hash"], "snapshot": snap}
    conn.execute("INSERT INTO sources(id, sha256, origin, filename, format, bytes, path, meta, provenance) "
                 "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET sha256=excluded.sha256, bytes=excluded.bytes,"
                 " meta=excluded.meta, provenance=excluded.provenance",
                 (aid, sha, "photoprism", sources.display_name(Path(f["Name"]).name), fmt, nbytes, f"pp:{f['Name']}",
                  json.dumps(meta, sort_keys=True), json.dumps(prov, sort_keys=True)))
    return conn.execute("SELECT * FROM sources WHERE id=?", (aid,)).fetchone(), None


def source_file(store: Store, cfg: Cfg, row: sqlite3.Row) -> Path:
    """Where the original of a source lives. Raises FileNotFoundError / PPError."""
    if row["origin"] == "photoprism":
        root = pp.originals_root(cfg)
        if not root:
            raise FileNotFoundError("photoprism originals are not configured")
        return pp.local_original(root, row["path"][3:])
    return store.root / row["path"]
