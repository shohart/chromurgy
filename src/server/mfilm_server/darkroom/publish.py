# SPDX-License-Identifier: GPL-2.0-only
"""Publishing finished web renders to PhotoPrism (docs/web/32).

Per item: STAGED -> PUBLISHING (verified atomic copy into the chosen folder below originals)
-> INDEXING (index the folder, then find the new photo's UID by exact folder + name)
-> ALBUM_LINKING (add that UID to the chosen/new manual album) -> COMPLETE.
Each stage is idempotent and retried on the next worker pass; rendering is never redone and a
failure here never loses the render. Only the new JPEG is written: PhotoPrism records, the
source RAW and earlier renditions are never touched."""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

from ..config import PhotoPrism as Cfg
from ..ids import sha256_file
from ..store import Store, UnsafePath, confine
from . import photoprism as pp

NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
MAX_PUB_ATTEMPTS = 60            # worker passes; ~30 min at the 30 s service interval, then FAILED (render kept)


def out_name(filename: str, film: str, rid: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).stem)[:60] or "frame"
    return f"{stem}_{re.sub(r'[^A-Za-z0-9]', '', film)[:24]}_{rid[:8]}.jpg"      # never the RAW's base name: no RAW/JPEG stack


def index_argv(cfg: Cfg, folder: str) -> list[str] | None:
    if cfg.index_template:
        return [a.replace("{path}", folder) for a in cfg.index_template]
    if cfg.index_command and cfg.index_command[-1] == cfg.subdir:
        return [*cfg.index_command[:-1], folder]
    return None


def _note(conn, iid: int, state: str, note: str | None = None, **cols) -> None:
    sets = "".join(f", {k}=?" for k in cols)
    conn.execute(f"UPDATE darkroom_items SET state=?, pub_note=?{sets} WHERE id=?", (state, note, *cols.values(), iid))


def _bump(conn, it, note: str) -> None:
    n = it["pub_attempts"] + 1
    if n >= MAX_PUB_ATTEMPTS:
        conn.execute(f"UPDATE darkroom_items SET state='FAILED', error_code='PUBLISH_FAILED', error_detail=?, "
                     f"pub_attempts=?, finished_at={NOW} WHERE id=?", (note[:500], n, it["id"]))
    else:
        conn.execute("UPDATE darkroom_items SET pub_note=?, pub_attempts=? WHERE id=?", (note[:500], n, it["id"]))


def copy_verified(src: Path, dest: Path, sha: str) -> None:
    """Dot-name first (PhotoPrism skips hidden files), re-hash, then atomic rename on the same filesystem."""
    if dest.is_file() and sha256_file(dest)[0] == sha:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.part")
    shutil.copyfile(src, tmp)
    if sha256_file(tmp)[0] != sha:
        tmp.unlink(missing_ok=True)
        raise OSError("copy verification failed")
    os.replace(tmp, dest)


def publish_pending(conn: sqlite3.Connection, store: Store, cfg: Cfg, client: pp.Client | None = None,
                    run=subprocess.run) -> dict:
    """One publication pass over every item of publishing jobs. Never raises for PhotoPrism trouble."""
    rows = conn.execute(
        "SELECT i.*, j.publish, j.id AS jid, j.album_uid AS job_album, w.path AS rpath, w.sha256 AS rsha, w.recipe, s.filename "
        "FROM darkroom_items i JOIN darkroom_jobs j ON j.id=i.job_id JOIN web_renders w ON w.id=i.render_id "
        "JOIN sources s ON s.id=i.source_id WHERE j.publish IS NOT NULL AND i.state IN "
        "('STAGED','PUBLISHING','INDEXING','ALBUM_LINKING') ORDER BY i.job_id, i.ordinal").fetchall()
    summary = {"items": len(rows), "completed": 0, "waiting": 0, "failed": 0}
    if not rows:
        return summary
    if not cfg.export_dir or not cfg.export_dir.is_dir():
        for it in rows:
            _bump(conn, it, "photoprism.export_dir is not available on this host")
        summary["waiting"] = len(rows)
        return summary
    try:
        client = client or pp.Client(cfg)
    except pp.PPError as e:
        client = None
        api_err = f"{e.code}: {e.detail}"
    else:
        api_err = ""
    indexed: set[tuple[str, str]] = set()
    for it in rows:
        pubset = json.loads(it["publish"])
        folder = pubset["folder"]
        film = json.loads(it["recipe"])["film"]["id"]
        name = out_name(it["filename"], film, it["render_id"])
        rel = f"{folder}/{name}"
        try:
            dest = confine(cfg.export_dir, rel)
            # 1. file
            if it["state"] in ("STAGED", "PUBLISHING"):
                _note(conn, it["id"], "PUBLISHING", None, pub_path=rel)
                copy_verified(store.root / it["rpath"], dest, it["rsha"])
                _note(conn, it["id"], "INDEXING", None)
                it = {**dict(it), "state": "INDEXING"}
            # 2. index + reconcile the new photo's UID by exact folder + name
            if it["state"] == "INDEXING":
                if (it["jid"], folder) not in indexed:
                    argv = index_argv(cfg, folder)
                    if argv:
                        p = run(argv, capture_output=True, text=True, timeout=3600, check=False)
                        if p.returncode != 0:
                            raise RuntimeError(f"index command failed: {(p.stderr or p.stdout)[-300:]}")
                    indexed.add((it["jid"], folder))
                if client is None:
                    raise RuntimeError(api_err)
                uid = find_photo(client, folder, Path(name).stem)
                if not uid:
                    raise LookupError("not indexed by PhotoPrism yet")
                _note(conn, it["id"], "ALBUM_LINKING", None, pp_photo_uid=uid)
                it = {**dict(it), "state": "ALBUM_LINKING", "pp_photo_uid": uid}
            # 3. album
            if it["state"] == "ALBUM_LINKING":
                album = pubset.get("album_uid") or it["job_album"]
                if not album and pubset.get("create_album_name"):
                    if client is None:
                        raise RuntimeError(api_err)
                    album = client.create_album(pubset["create_album_name"])
                    conn.execute("UPDATE darkroom_jobs SET album_uid=? WHERE id=? AND album_uid IS NULL", (album, it["jid"]))
                    album = conn.execute("SELECT album_uid FROM darkroom_jobs WHERE id=?", (it["jid"],)).fetchone()[0]
                if album:
                    if client is None:
                        raise RuntimeError(api_err)
                    client.add_to_album(album, [it["pp_photo_uid"]])
                conn.execute(f"UPDATE darkroom_items SET state='COMPLETE', pub_note=NULL, finished_at={NOW} WHERE id=?", (it["id"],))
                summary["completed"] += 1
        except (UnsafePath, ValueError) as e:
            conn.execute(f"UPDATE darkroom_items SET state='FAILED', error_code='UNSAFE_PATH', error_detail=?, finished_at={NOW} "
                         "WHERE id=?", (str(e)[:300], it["id"]))
            summary["failed"] += 1
        except (OSError, RuntimeError, LookupError, subprocess.SubprocessError, pp.PPError) as e:
            _bump(conn, it, f"{e.code}: {e.detail}" if isinstance(e, pp.PPError) else f"{type(e).__name__}: {e}")
            summary["waiting"] += 1
    return summary


def find_photo(client: pp.Client, folder: str, stem: str) -> str | None:
    off = 0
    while True:
        page = client.photos(folder=folder, count=200, offset=off)
        for ph in page:
            if ph.get("Name") == stem and ph.get("Path") == folder:
                return ph["UID"]
        if len(page) < 200:
            return None
        off += 200
