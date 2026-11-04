# SPDX-License-Identifier: GPL-2.0-only
"""`mfilmctl import-card`: ingest sealed rolls from a mounted SD card (docs/04, docs/08).

Never modifies or deletes anything on the card. Idempotent: re-importing the
same card adds nothing. A conflicting manifest for a known roll is refused.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import contracts
from .ids import canonical_json, sha256_file
from .store import Store, UnsafePath, confine, safe_id

MFILM_DIR = Path("CHDK") / "MFILM" / "ROLLS"
IMPORTABLE_CAMERA_STATES = ("SEALED", "READY_FOR_SYNC")
TIFF_MAGIC = (b"II*\x00", b"MM\x00*")


@dataclass
class FrameResult:
    frame_id: str
    ordinal: int
    status: str                 # IMPORTED | ALREADY_ARCHIVED | ERROR | WOULD_IMPORT
    error_code: str | None = None
    detail: str | None = None


@dataclass
class RollResult:
    manifest: str
    status: str                 # IMPORTED | INCOMPLETE | SKIPPED | CONFLICT | INVALID | UNCHANGED | DRY_RUN
    device_id: str | None = None
    roll_id: str | None = None
    detail: str | None = None
    frames: list[FrameResult] = field(default_factory=list)


def card_source(card_root: Path, source_path: str) -> Path:
    """Map a camera path like 'A/DCIM/100CANON/IMG_0001.DNG' into the mounted card."""
    rel = source_path.replace("\\", "/")
    if rel.startswith("A/"):
        rel = rel[2:]
    return confine(card_root, rel)


def _check_dng_header(path: Path) -> None:
    with open(path, "rb") as f:
        head = f.read(4)
    if head not in TIFF_MAGIC:
        raise ValueError("not a TIFF/DNG container")


def find_manifests(card_root: Path) -> list[Path]:
    base = card_root / MFILM_DIR
    return sorted(base.glob("*/manifest.json")) if base.is_dir() else []


def import_card(card_root: Path, store: Store, conn: sqlite3.Connection, *, dry_run: bool = False) -> list[RollResult]:
    card_root = Path(card_root)
    return [_import_roll(card_root, m, store, conn, dry_run) for m in find_manifests(card_root)]


def _import_roll(card_root: Path, mpath: Path, store: Store, conn: sqlite3.Connection, dry_run: bool) -> RollResult:
    res = RollResult(manifest=str(mpath.relative_to(card_root)), status="INVALID")
    raw = mpath.read_bytes()
    try:
        doc = contracts.load_roll_manifest(raw)
        device_id = safe_id(doc["device_id"], "device_id")
        roll_id = safe_id(doc["roll_id"], "roll_id")
        for fr in doc["frames"]:
            safe_id(fr["frame_id"], "frame_id")
    except (contracts.ManifestError, UnsafePath) as e:
        res.detail = str(e)
        return res
    res.device_id, res.roll_id = device_id, roll_id
    if doc["roll_state"] not in IMPORTABLE_CAMERA_STATES:
        res.status, res.detail = "SKIPPED", f"roll_state={doc['roll_state']} (not sealed)"
        return res

    manifest_sha = hashlib.sha256(canonical_json(doc)).hexdigest()
    known = conn.execute("SELECT manifest_sha256, state FROM rolls WHERE device_id=? AND id=?",
                         (device_id, roll_id)).fetchone()
    if known and known["manifest_sha256"] != manifest_sha:
        res.status, res.detail = "CONFLICT", "a different manifest for this roll is already archived"
        return res

    # verify + stage every frame before touching the DB
    staged: list[tuple[dict, Path | None, Path, str]] = []   # frame, part, dest, status
    hashes: dict[str, str] = {}     # frame_id -> sha256 (declared, or computed here for hashless WRITTEN frames)
    for fr in sorted(doc["frames"], key=lambda f: f["ordinal"]):
        fres = FrameResult(frame_id=fr["frame_id"], ordinal=fr["ordinal"], status="ERROR")
        res.frames.append(fres)
        try:
            src = card_source(card_root, fr["source_path"])
            dest = store.original_path(device_id, roll_id, fr["frame_id"])
        except UnsafePath as e:
            fres.error_code, fres.detail = "UNSAFE_SOURCE_PATH", str(e)
            continue
        want = (fr.get("source_sha256") or "").lower() or None   # None: camera did not hash (WRITTEN)
        if dest.exists():
            have, _ = sha256_file(dest)
            if want is None:            # hashless frame: the card copy (or, if gone, the archive) decides
                want = sha256_file(src)[0] if src.is_file() else have
            if have == want:
                hashes[fr["frame_id"]] = have
                fres.status = "ALREADY_ARCHIVED"
                staged.append((fr, None, dest, fres.status))
            else:
                fres.error_code = "ARCHIVE_HASH_CONFLICT"
            continue
        if not src.is_file():
            fres.error_code, fres.detail = "SOURCE_MISSING", fr["source_path"]
            continue
        if src.stat().st_size != fr["source_size_bytes"]:
            fres.error_code = "SOURCE_SIZE_MISMATCH"
            fres.detail = f"{src.stat().st_size} != {fr['source_size_bytes']}"
            continue
        try:
            _check_dng_header(src)
        except ValueError as e:
            fres.error_code, fres.detail = "UNSUPPORTED_DNG_FEATURE", str(e)
            continue
        if dry_run:
            have, _ = sha256_file(src)
            if want is not None and have != want:
                fres.error_code = "SOURCE_HASH_MISMATCH"
                continue
            fres.status = "WOULD_IMPORT"
            continue
        part = store.stage_copy(src)
        have, nbytes = sha256_file(part)   # hash the staged copy, not the card
        if (want is not None and have != want) or nbytes != fr["source_size_bytes"]:
            part.unlink()
            fres.error_code = "SOURCE_HASH_MISMATCH"
            continue
        hashes[fr["frame_id"]] = have
        fres.status = "IMPORTED"
        staged.append((fr, part, dest, fres.status))

    if dry_run:
        res.status = "DRY_RUN"
        return res

    complete = len(staged) == len(doc["frames"])
    if not complete and any(not fr.get("source_sha256") and fr["frame_id"] not in hashes for fr in doc["frames"]):
        # a hashless frame that could not be read now has no identity to declare: wait for a complete card
        res.status, res.detail = "INCOMPLETE", "unhashed frame(s) missing on the card"
        for _, part, _, _ in staged:
            if part is not None and part.exists():
                part.unlink()
        return res
    if known and not any(p for _, p, _, _ in staged) and (known["state"] == "INPUTS_COMPLETE" or not complete):
        res.status = "UNCHANGED" if complete else "INCOMPLETE"
        return res

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT OR IGNORE INTO devices(id) VALUES (?)", (device_id,))
        conn.execute("UPDATE devices SET last_seen_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (device_id,))
        conn.execute(
            """INSERT OR IGNORE INTO rolls(id, device_id, film_profile_id, profile_bundle_hash, render_recipe_id,
                   roll_length, expected_frames, camera_state, manifest_sha256, created_at, sealed_at, state)
               VALUES (?,?,?,?,?,?,?,?,?,?,?, 'RECEIVING')""",
            (roll_id, device_id, doc["film_profile_id"], doc["profile_bundle_hash"].lower(),
             doc.get("render_recipe_id"), doc["roll_length"], len(doc["frames"]), doc["roll_state"],
             manifest_sha, doc.get("created_at"), doc.get("sealed_at")))
        for fr in doc["frames"]:
            conn.execute(
                """INSERT OR IGNORE INTO frames(id, device_id, roll_id, ordinal, capture_time, declared_sha256,
                       declared_bytes, source_path, original_state) VALUES (?,?,?,?,?,?,?,?, 'DECLARED')""",
                (fr["frame_id"], device_id, roll_id, fr["ordinal"], fr.get("captured_at"),
                 hashes.get(fr["frame_id"]) or fr["source_sha256"].lower(), fr["source_size_bytes"],
                 fr["source_path"]))
        # Originals are promoted before COMMIT: on rollback they stay in the
        # archive as orphans, and the next import adopts them as
        # ALREADY_ARCHIVED after re-hashing (never overwritten).
        for fr, part, dest, _ in staged:
            if part is not None:
                Store.promote(part, dest)
            rel = str(dest.relative_to(store.root))
            sha = hashes[fr["frame_id"]]
            conn.execute("INSERT OR IGNORE INTO assets(sha256, bytes, mime, kind, path) VALUES (?,?,?,?,?)",
                         (sha, fr["source_size_bytes"], "image/x-adobe-dng", "original_dng", rel))
            asset_id = conn.execute("SELECT id FROM assets WHERE sha256=?", (sha,)).fetchone()[0]
            conn.execute("UPDATE frames SET original_asset_id=?, original_state='VERIFIED', error_code=NULL "
                         "WHERE device_id=? AND id=?", (asset_id, device_id, fr["frame_id"]))
        if complete:
            conn.execute("UPDATE rolls SET state='INPUTS_COMPLETE' WHERE device_id=? AND id=?", (device_id, roll_id))
        mdest = store.manifest_path(device_id, roll_id)
        if not mdest.exists():
            Store.promote(store.stage_bytes(raw), mdest)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        for _, part, _, _ in staged:
            if part is not None and part.exists():
                part.unlink()
        raise
    res.status = "IMPORTED" if complete else "INCOMPLETE"
    return res


def as_dict(results: list[RollResult]) -> list[dict]:
    return [asdict(r) for r in results]
