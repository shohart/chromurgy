# SPDX-License-Identifier: GPL-2.0-only
"""Camera rolls as Darkroom sources (docs/web/27 'M-Film Rolls'): the archived, hash-verified originals of
rolls received from a camera, re-developable with any recipe without touching the roll's own history.
The DNG stays where the camera pipeline archived it; only a source row pointing at it is added."""
from __future__ import annotations

import json
import os
import sqlite3

from ..store import Store
from . import sources


def list_rolls(conn: sqlite3.Connection) -> list[dict]:
    return [{"device_id": r["device_id"], "roll_id": r["id"], "film_profile_id": r["film_profile_id"],
             "created_at": r["created_at"], "state": r["state"], "roll_length": r["roll_length"],
             "frames": r["frames"], "verified": r["verified"]}
            for r in conn.execute(
                "SELECT r.*, (SELECT count(*) FROM frames f WHERE f.device_id=r.device_id AND f.roll_id=r.id) AS frames, "
                "(SELECT count(*) FROM frames f WHERE f.device_id=r.device_id AND f.roll_id=r.id AND f.original_state='VERIFIED') "
                "AS verified FROM rolls r ORDER BY COALESCE(r.created_at, r.received_at) DESC")]


def roll_frames(conn: sqlite3.Connection, device_id: str, roll_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT f.id, f.ordinal, f.capture_time, f.original_state, a.sha256, a.bytes, a.path FROM frames f "
        "LEFT JOIN assets a ON a.id=f.original_asset_id WHERE f.device_id=? AND f.roll_id=? ORDER BY f.ordinal",
        (device_id, roll_id)).fetchall()


def snapshot(conn: sqlite3.Connection, store: Store, device_id: str, roll_id: str, frame: sqlite3.Row,
             roll_film: str) -> tuple[sqlite3.Row | None, str | None]:
    """Register one verified frame as a source. (row, None) or (None, reason)."""
    if frame["original_state"] != "VERIFIED" or not frame["path"]:
        return None, f"original {frame['original_state'].lower()}: not on the server yet"
    sid = f"rl_{frame['sha256'][:32]}"
    have = conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
    if have:
        return have, None
    path = store.root / frame["path"]
    if not path.is_file():
        return None, "archived original is missing from disk"
    tpart = store.root / "incoming" / f"roll-{sid}.thumb"
    res = sources.probe(path, tpart)
    if not res["ok"]:
        tpart.unlink(missing_ok=True)
        return None, f"{res['code']}: {res.get('detail', '')}"[:300]
    meta = res["meta"]
    if meta.pop("has_thumb", False) and tpart.is_file():
        td = sources.thumb_path(store, frame["sha256"])
        td.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tpart, td)
    tpart.unlink(missing_ok=True)
    meta.pop("is_dng", None)
    meta["warnings"] = []
    meta["roll_film"] = roll_film
    prov = {"origin": "camera_roll", "device_id": device_id, "roll_id": roll_id, "frame_id": frame["id"],
            "ordinal": frame["ordinal"], "asset_sha256": frame["sha256"]}
    conn.execute("INSERT OR IGNORE INTO sources(id, sha256, origin, filename, format, bytes, path, meta, provenance) "
                 "VALUES (?,?,?,?,?,?,?,?,?)",
                 (sid, frame["sha256"], "camera_roll", f"{roll_id[:8]}_{frame['ordinal']:02d}.dng", meta["format"],
                  frame["bytes"], frame["path"], json.dumps(meta, sort_keys=True), json.dumps(prov, sort_keys=True)))
    return conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone(), None
