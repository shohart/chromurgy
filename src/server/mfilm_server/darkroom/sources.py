# SPDX-License-Identifier: GPL-2.0-only
"""Source catalog (docs/web/30): immutable RAW originals, content-addressed.

A source is one RAW file that has passed the decoder. Browser uploads land in
web-originals/<sha[:2]>/<sha256>.<fmt> (read-only, never overwritten, never
deleted); PhotoPrism- and roll-backed sources are added by their own modules and
point at the file where it already lives."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import unicodedata
from pathlib import Path

from ..ids import sha256_file
from ..store import Store

INSPECT = Path(__file__).with_name("_inspect.py")
PROBE_TIMEOUT_S = 120
SUPPORTED_EXT = {".dng", ".nef"}          # others only after decoder/corpus verification (docs/web/30)


class SourceError(Exception):
    def __init__(self, code: str, detail: str = "", status: int = 422):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.status = code, detail, status


def display_name(name: str) -> str:
    """Untrusted client file name -> safe label (never used as a physical path)."""
    name = unicodedata.normalize("NFC", name.replace("\\", "/").rsplit("/", 1)[-1])
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:200] or "unnamed"


def probe(path: Path, thumb_out: Path | None = None) -> dict:
    """Run the decoder probe in an isolated child; returns {ok, meta} or {ok False, code, detail}."""
    try:
        p = subprocess.run([sys.executable, "-I", str(INSPECT), str(path), *([str(thumb_out)] if thumb_out else [])], capture_output=True, text=True,
                           timeout=PROBE_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": "DECODER_TIMEOUT", "detail": f"no result in {PROBE_TIMEOUT_S} s"}
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "code": "DECODER_CRASH", "detail": f"exit {p.returncode}: {p.stderr[-300:]}"}


def thumb_path(store: Store, sha: str) -> Path:
    return store.root / "web-previews" / "thumb" / f"{sha}.jpg"


def source_id(sha: str) -> str:
    return f"up_{sha[:32]}"


def row_public(r: sqlite3.Row) -> dict:
    return {"asset_id": r["id"], "sha256": r["sha256"], "origin": r["origin"], "filename": r["filename"],
            "format": r["format"], "bytes": r["bytes"], "eligible": bool(r["eligible"]), "reason": r["reason"],
            "meta": json.loads(r["meta"]), "created_at": r["created_at"]}


def commit_upload(conn: sqlite3.Connection, store: Store, part: Path, filename: str) -> tuple[sqlite3.Row, bool]:
    """Validate a fully received upload and archive it. Returns (source row, duplicate).
    The .part file is consumed on success and on a duplicate, kept for the caller to remove otherwise."""
    ext = Path(filename).suffix.lower()
    sha, nbytes = sha256_file(part)
    sid = source_id(sha)
    have = conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
    if have:
        part.unlink(missing_ok=True)
        return have, True
    tpart = part.with_suffix(".thumb")
    res = probe(part, tpart)
    if not res["ok"]:
        tpart.unlink(missing_ok=True)
        raise SourceError(res["code"], res.get("detail", ""))
    meta = res["meta"]
    fmt = meta["format"]
    if fmt not in ("dng", "nef"):
        tpart.unlink(missing_ok=True)
        raise SourceError("UNSUPPORTED_RAW", f"{meta.get('make')} {meta.get('model')}: only DNG and Nikon NEF are verified")
    warnings = []
    if ext not in SUPPORTED_EXT:
        tpart.unlink(missing_ok=True)
        raise SourceError("UNSUPPORTED_EXTENSION", f"{ext or '(none)'}: expected .dng or .nef")
    if ext != f".{fmt}":
        warnings.append(f"extension {ext} but the content is {fmt.upper()}")
    meta["warnings"] = warnings
    meta.pop("is_dng", None)
    dest = store.root / "web-originals" / sha[:2] / f"{sha}.{fmt}"
    if meta.pop("has_thumb", False) and tpart.is_file():
        tdest = thumb_path(store, sha)
        tdest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tpart, tdest)
    tpart.unlink(missing_ok=True)
    if not dest.exists():
        Store.promote(part, dest)
    else:
        part.unlink(missing_ok=True)
    conn.execute("INSERT OR IGNORE INTO sources(id, sha256, origin, filename, format, bytes, path, meta, provenance)"
                 " VALUES (?,?,?,?,?,?,?,?,?)",
                 (sid, sha, "upload", display_name(filename), fmt, nbytes, str(dest.relative_to(store.root)),
                  json.dumps(meta, sort_keys=True), json.dumps({"origin": "upload", "input_filename": display_name(filename)})))
    return conn.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone(), False
