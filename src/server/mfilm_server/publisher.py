# SPDX-License-Identifier: GPL-2.0-only
"""PhotoPrism publication (docs/11): only committed, verified linux renders are
copied into PhotoPrism's library, atomically, once per destination.

Files are written under a dot-name first (PhotoPrism skips hidden files),
re-hashed, then renamed into place. Copy + rename instead of hard links,
because the library usually lives on a network share (CIFS/NFS).
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import PhotoPrism
from .ids import sha256_file
from .store import Store, safe_id

NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"


class PublishError(Exception):
    pass


@dataclass
class Published:
    render_id: str
    path: str
    status: str             # EXPORTED | ALREADY | FAILED
    detail: str | None = None


def _film_short(conn, key: str) -> str:
    """'Portra400' from profiles/films.json, else the key itself."""
    import json
    from . import core
    meta = core.bundle_path().with_name("films.json")
    try:
        for f in json.loads(meta.read_text())["films"]:
            if f["key"] == key:
                key = f["short"]
                break
    except (OSError, ValueError, KeyError):
        pass
    return re.sub(r"[^A-Za-z0-9]", "", key) or "film"


def roll_folder(roll: sqlite3.Row, film_short: str) -> str:
    day = (roll["created_at"] or roll["sealed_at"] or roll["received_at"] or "")[:10] or "undated"
    return f"{day}_{film_short}_{safe_id(roll['id'])[:8]}"


def publish_roll(conn: sqlite3.Connection, store: Store, pp: PhotoPrism, roll_id: str,
                 device_id: str | None = None) -> list[Published]:
    if not pp.export_dir:
        raise PublishError("photoprism.export_dir is not configured")
    if not pp.export_dir.is_dir():
        raise PublishError(f"export_dir does not exist: {pp.export_dir}")
    q, args = "SELECT * FROM rolls WHERE id=?", [roll_id]
    if device_id:
        q, args = q + " AND device_id=?", args + [device_id]
    rolls = conn.execute(q, args).fetchall()
    if len(rolls) != 1:
        raise PublishError(f"roll {roll_id}: {len(rolls)} matches")
    roll = rolls[0]
    dest_root = pp.export_dir / pp.subdir / roll_folder(roll, _film_short(conn, roll["film_profile_id"]))
    destination = f"photoprism:{pp.export_dir}"
    rows = conn.execute(
        "SELECT r.id, f.ordinal, a.path, a.sha256 FROM renders r "
        "JOIN frames f ON f.device_id=r.device_id AND f.id=r.frame_id JOIN assets a ON a.id=r.asset_id "
        "WHERE f.device_id=? AND f.roll_id=? AND r.origin='linux' AND r.state IN ('COMMITTED','PUBLISHED') "
        "ORDER BY f.ordinal", (roll["device_id"], roll["id"])).fetchall()
    out: list[Published] = []
    for r in rows:
        done = conn.execute("SELECT status FROM publications WHERE render_id=? AND destination=?",
                            (r["id"], destination)).fetchone()
        target = dest_root / f"{r['ordinal']:02d}_{r['id'][:12]}.jpg"
        if done and done["status"] in ("EXPORTED", "INDEXED") and target.is_file():
            out.append(Published(r["id"], str(target), "ALREADY"))
            continue
        try:
            src = store.root / r["path"]
            if sha256_file(src)[0] != r["sha256"]:
                raise PublishError("archived render does not match its hash")
            dest_root.mkdir(parents=True, exist_ok=True)
            if not (target.is_file() and sha256_file(target)[0] == r["sha256"]):
                tmp = dest_root / f".{target.name}.part"
                shutil.copyfile(src, tmp)
                if sha256_file(tmp)[0] != r["sha256"]:
                    tmp.unlink()
                    raise PublishError("copy verification failed")
                os.replace(tmp, target)
            status = "EXPORTED"
        except (OSError, PublishError) as e:
            status = "FAILED"
            out.append(Published(r["id"], str(target), status, str(e)))
        else:
            out.append(Published(r["id"], str(target), status))
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO publications(render_id, destination, status) VALUES (?,?,?) "
                     "ON CONFLICT(render_id, destination) DO UPDATE SET status=excluded.status",
                     (r["id"], destination, status))
        if status == "EXPORTED":
            conn.execute("UPDATE renders SET state='PUBLISHED' WHERE id=?", (r["id"],))
        conn.execute("COMMIT")
    return out


def run_index(conn: sqlite3.Connection, pp: PhotoPrism, render_ids: list[str]) -> tuple[bool, str]:
    """Run the configured index command (argv list, no shell); mark INDEXED on success."""
    if not pp.index_command:
        return False, "no index_command configured (PhotoPrism will index on its own schedule)"
    p = subprocess.run(pp.index_command, capture_output=True, text=True, timeout=3600)
    if p.returncode != 0:
        return False, (p.stderr or p.stdout)[-2000:]
    destination = f"photoprism:{pp.export_dir}"
    conn.execute("BEGIN IMMEDIATE")
    for rid in render_ids:
        conn.execute("UPDATE publications SET status='INDEXED' WHERE render_id=? AND destination=? "
                     "AND status='EXPORTED'", (rid, destination))
    conn.execute("COMMIT")
    return True, p.stdout[-2000:]
