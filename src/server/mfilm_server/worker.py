# SPDX-License-Identifier: GPL-2.0-only
"""Development queue (docs/08 steps 4-7): enqueue sealed, verified rolls and
develop their frames with the shared film core into the render archive.

States: renders/jobs use QUEUED -> RUNNING -> COMMITTED, or FAILED_RETRYABLE
(re-queued up to MAX_ATTEMPTS) / FAILED_TERMINAL. A crash leaves RUNNING
jobs behind; recover_stale() puts them back in the queue.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import core
from .develop import DevelopError, default_recipe, develop, recipe_render_id, recipe_seed
from .ids import canonical_json, sha256_file
from .store import Store, safe_id

MAX_ATTEMPTS = 3
TERMINAL_CODES = {"BAD_DNG", "UNSUPPORTED_PROFILE", "UNSUPPORTED_RECIPE", "PROFILE_BUNDLE_MISMATCH",
                  "OUTPUT_LARGER_THAN_SOURCE", "UNSUPPORTED_DNG_FEATURE"}
NOW = "strftime('%Y-%m-%dT%H:%M:%fZ','now')"


class QueueError(Exception):
    pass


def find_roll(conn: sqlite3.Connection, roll_id: str, device_id: str | None = None) -> sqlite3.Row:
    q, args = "SELECT * FROM rolls WHERE id=?", [roll_id]
    if device_id:
        q, args = q + " AND device_id=?", args + [device_id]
    rows = conn.execute(q, args).fetchall()
    if not rows:
        raise QueueError(f"unknown roll {roll_id}")
    if len(rows) > 1:
        raise QueueError(f"roll {roll_id} exists for several devices; pass --device")
    return rows[0]


def enqueue_roll(conn: sqlite3.Connection, roll_id: str, device_id: str | None = None,
                 recipe_overrides: dict | None = None) -> dict:
    """Queue one canonical linux rendition per verified frame. Idempotent."""
    roll = find_roll(conn, roll_id, device_id)
    if roll["state"] != "INPUTS_COMPLETE":
        raise QueueError(f"roll {roll_id} is {roll['state']}: not every original is verified yet")
    recipe = default_recipe(roll["film_profile_id"], roll["profile_bundle_hash"])
    recipe["recipe_id"] = roll["render_recipe_id"] or recipe["recipe_id"]
    for k, v in (recipe_overrides or {}).items():
        recipe[k] = v
    recipe_json = canonical_json(recipe).decode()
    recipe_key = hashlib.sha256(recipe_json.encode()).hexdigest()
    frames = conn.execute(
        "SELECT f.id, a.sha256 FROM frames f JOIN assets a ON a.id=f.original_asset_id "
        "WHERE f.device_id=? AND f.roll_id=? AND f.original_state='VERIFIED' ORDER BY f.ordinal",
        (roll["device_id"], roll["id"])).fetchall()
    added = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT OR IGNORE INTO recipes(id, json, core_revision, bundle_hash) VALUES (?,?,?,?)",
                     (recipe_key, recipe_json, core.core_version(), roll["profile_bundle_hash"]))
        for fr in frames:
            seed = recipe_seed(recipe, roll["device_id"], roll["id"], fr["id"])
            rid = recipe_render_id(fr["sha256"], recipe, roll["profile_bundle_hash"], seed)
            cur = conn.execute(
                "INSERT OR IGNORE INTO renders(id, device_id, frame_id, recipe_id, output_spec, origin, state) "
                "VALUES (?,?,?,?,?, 'linux', 'QUEUED')",
                (rid, roll["device_id"], fr["id"], recipe_key, json.dumps(recipe["output_spec"], sort_keys=True)))
            if cur.rowcount:
                conn.execute("INSERT INTO jobs(render_id, state) VALUES (?, 'QUEUED')", (rid,))
                added += 1
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return {"device_id": roll["device_id"], "roll_id": roll["id"], "frames": len(frames), "queued": added}


def recover_stale(conn: sqlite3.Connection) -> int:
    """Jobs left RUNNING by a dead worker go back to the queue (single-worker deployment)."""
    conn.execute("BEGIN IMMEDIATE")
    n = conn.execute("UPDATE jobs SET state='QUEUED' WHERE state='RUNNING'").rowcount
    conn.execute("UPDATE renders SET state='QUEUED' WHERE state='RUNNING'")
    conn.execute("COMMIT")
    return n


@dataclass
class JobResult:
    job_id: int
    render_id: str
    state: str
    error_code: str | None = None
    detail: str | None = None


def _claim(conn: sqlite3.Connection, skip: set[int] = frozenset()) -> sqlite3.Row | None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        job = None
        for row in conn.execute("SELECT * FROM jobs WHERE state='QUEUED' ORDER BY id"):
            if row["id"] not in skip:
                job = row
                break
        if job:
            conn.execute(f"UPDATE jobs SET state='RUNNING', attempt=attempt+1, started_at={NOW} WHERE id=?",
                         (job["id"],))
            conn.execute("UPDATE renders SET state='RUNNING' WHERE id=?", (job["render_id"],))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone() if job else None


def _finish(conn, job, state: str, code: str | None = None, asset_id: int | None = None) -> None:
    render_state = {"COMMITTED": "COMMITTED", "FAILED_TERMINAL": "FAILED_TERMINAL"}.get(state, "QUEUED")
    job_state = state
    if state == "FAILED_RETRYABLE" and job["attempt"] >= MAX_ATTEMPTS:
        job_state = render_state = "FAILED_TERMINAL"
    elif state == "FAILED_RETRYABLE":
        job_state = "QUEUED"
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"UPDATE jobs SET state=?, error_code=?, finished_at={NOW} WHERE id=?",
                     (job_state, code, job["id"]))
        conn.execute("UPDATE renders SET state=?, asset_id=COALESCE(?, asset_id) WHERE id=?",
                     (render_state, asset_id, job["render_id"]))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def run_one(conn: sqlite3.Connection, store: Store, bundle: core.Bundle,
            skip: set[int] = frozenset()) -> JobResult | None:
    job = _claim(conn, skip)
    if not job:
        return None
    r = conn.execute(
        "SELECT r.*, rc.json AS recipe_json, f.roll_id, f.capture_time, a.path AS original_path, a.sha256 AS original_sha256 "
        "FROM renders r JOIN recipes rc ON rc.id=r.recipe_id "
        "JOIN frames f ON f.device_id=r.device_id AND f.id=r.frame_id JOIN assets a ON a.id=f.original_asset_id "
        "WHERE r.id=?", (job["render_id"],)).fetchone()
    recipe = json.loads(r["recipe_json"])
    dest_dir = store.root / "renders" / safe_id(r["device_id"]) / safe_id(r["roll_id"])
    dest = dest_dir / f"{r['id']}.jpg"
    try:
        if not dest.exists():
            work = store.root / "incoming" / f"render-{r['id']}"
            work.mkdir(exist_ok=True)
            out = work / f"{r['id']}.jpg"
            prov = develop(store.root / r["original_path"], out, profile=None, recipe=recipe,
                           device_id=r["device_id"], roll_id=r["roll_id"], frame_id=r["frame_id"], bundle=bundle,
                           captured_at=r["capture_time"])
            if prov["render_id"] != r["id"] or prov["original_sha256"] != r["original_sha256"]:
                raise DevelopError("RENDER_IDENTITY_MISMATCH", f"{prov['render_id']} != {r['id']}")
            side = out.with_suffix(".jpg.json")
            prov["output"] = str(dest.relative_to(store.root))
            side.write_text(json.dumps(prov, indent=2) + "\n")
            stale = dest.with_suffix(".jpg.json")
            if stale.exists():            # a crash between the two promotions
                stale.unlink()
            Store.promote(side, dest.with_suffix(".jpg.json"))
            Store.promote(out, dest)          # the JPEG last: its presence means the pair is complete
            os.rmdir(work)
        sha, nbytes = sha256_file(dest)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT OR IGNORE INTO assets(sha256, bytes, mime, kind, path) VALUES (?,?,?,?,?)",
                     (sha, nbytes, "image/jpeg", "render_jpeg", str(dest.relative_to(store.root))))
        asset_id = conn.execute("SELECT id FROM assets WHERE sha256=?", (sha,)).fetchone()[0]
        conn.execute("COMMIT")
        _finish(conn, job, "COMMITTED", asset_id=asset_id)
        return JobResult(job["id"], r["id"], "COMMITTED")
    except (DevelopError, core.CoreError) as e:
        state = "FAILED_TERMINAL" if e.code in TERMINAL_CODES else "FAILED_RETRYABLE"
        _finish(conn, job, state, e.code)
        return JobResult(job["id"], r["id"], state, e.code, e.detail)
    except OSError as e:
        _finish(conn, job, "FAILED_RETRYABLE", "IO_ERROR")
        return JobResult(job["id"], r["id"], "FAILED_RETRYABLE", "IO_ERROR", str(e))


def run(conn: sqlite3.Connection, store: Store, *, max_jobs: int | None = None) -> list[JobResult]:
    recover_stale(conn)
    bundle = core.Bundle()
    done: list[JobResult] = []
    tried: set[int] = set()           # a retryable failure waits for the next run
    while max_jobs is None or len(done) < max_jobs:
        res = run_one(conn, store, bundle, tried)
        if res is None:
            break
        tried.add(res.job_id)
        done.append(res)
    return done
