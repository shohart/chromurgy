# SPDX-License-Identifier: GPL-2.0-only
"""Development queue (docs/08 steps 4-7): enqueue sealed, verified rolls and
develop their frames with the shared film core into the render archive.

States: renders/jobs use QUEUED -> RUNNING -> COMMITTED, or FAILED_RETRYABLE
(re-queued up to MAX_ATTEMPTS) / FAILED_TERMINAL. A crash leaves RUNNING
jobs behind; recover_stale() puts them back in the queue. A job whose exact
profile bundle is not archived is parked in WAITING_FOR_INPUTS (no attempt
spent) and re-queued once that bundle is added (docs/12: pause, never drift).
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import core
from .bundles import Bundles, BundleUnavailable
from .develop import DevelopError, default_recipe, develop, recipe_render_id, recipe_seed
from .ids import canonical_json, sha256_file
from .store import Store, safe_id

MAX_ATTEMPTS = 3
TERMINAL_CODES = {"BAD_DNG", "UNSUPPORTED_PROFILE", "UNSUPPORTED_RECIPE", "PROFILE_BUNDLE_MISMATCH",
                  "OUTPUT_LARGER_THAN_SOURCE", "UNSUPPORTED_DNG_FEATURE",
                  "RENDER_IDENTITY_MISMATCH"}   # core changed since enqueue: re-queue (mfilmctl develop), never retry
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


LOOK_KEYS = ("grain_scale", "halation_scale", "softness_scale")


def build_recipe(roll: sqlite3.Row, *, profile: str | None = None, bundle_hash: str | None = None,
                 look: dict | None = None, exposure_ev: float | None = None,
                 user_seed: int | None = None) -> dict:
    """The roll's own recipe, or a reprocess variant of it.

    Unchanged arguments give exactly the roll's recipe (same render ids, so a
    repeat is a no-op). Any change gets a recipe_id derived from the change,
    hence a new grain seed and new renditions next to the old ones.
    """
    profile = profile or roll["film_profile_id"]
    bundle_hash = (bundle_hash or roll["profile_bundle_hash"]).lower()
    recipe = default_recipe(profile, bundle_hash)
    change = {}
    if profile != roll["film_profile_id"]:
        change["film_profile_id"] = profile
    if bundle_hash != roll["profile_bundle_hash"].lower():
        change["profile_bundle_hash"] = bundle_hash
    for k, v in (look or {}).items():
        if k not in LOOK_KEYS:
            raise QueueError(f"unknown look control {k}")
        if v is not None and float(v) != recipe["look_controls"][k]:
            change[k] = recipe["look_controls"][k] = float(v)
    if exposure_ev is not None and float(exposure_ev) != recipe["exposure_compensation_ev"]:
        change["exposure_compensation_ev"] = recipe["exposure_compensation_ev"] = float(exposure_ev)
    if user_seed is not None and int(user_seed) != recipe["user_seed"]:
        change["user_seed"] = recipe["user_seed"] = int(user_seed)
    if change:
        recipe["recipe_id"] = f"reprocess-{profile}-{hashlib.sha256(canonical_json(change)).hexdigest()[:12]}"
    else:
        recipe["recipe_id"] = roll["render_recipe_id"] or recipe["recipe_id"]
    return recipe


def enqueue_roll(conn: sqlite3.Connection, roll_id: str, device_id: str | None = None,
                 recipe: dict | None = None) -> dict:
    """Queue one linux rendition per verified frame (the roll's recipe by default). Idempotent."""
    roll = find_roll(conn, roll_id, device_id)
    if roll["state"] != "INPUTS_COMPLETE":
        raise QueueError(f"roll {roll_id} is {roll['state']}: not every original is verified yet")
    recipe = recipe or build_recipe(roll)
    bundle_hash = recipe["profile_bundle_hash"]
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
                     (recipe_key, recipe_json, core.core_version(), bundle_hash))
        for fr in frames:
            seed = recipe_seed(recipe, roll["device_id"], roll["id"], fr["id"])
            rid = recipe_render_id(fr["sha256"], recipe, bundle_hash, seed)
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
    return {"device_id": roll["device_id"], "roll_id": roll["id"], "frames": len(frames), "queued": added,
            "recipe_id": recipe["recipe_id"], "film_profile_id": recipe["film_profile_id"],
            "profile_bundle_hash": bundle_hash}


def recover_stale(conn: sqlite3.Connection) -> int:
    """Jobs left RUNNING by a dead worker go back to the queue (call only while no worker process is running: run() does, before its children start)."""
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


def park_and_unpark(conn: sqlite3.Connection, bundles: Bundles) -> tuple[list[JobResult], int]:
    """Park queued jobs whose bundle is missing; re-queue parked ones whose bundle arrived."""
    rows = conn.execute(
        "SELECT j.id, j.render_id, j.state, rc.bundle_hash FROM jobs j JOIN renders r ON r.id=j.render_id "
        "JOIN recipes rc ON rc.id=r.recipe_id WHERE j.state IN ('QUEUED','WAITING_FOR_INPUTS')").fetchall()
    parked: list[JobResult] = []
    unparked = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for j in rows:
            have = bundles.has(j["bundle_hash"])
            if j["state"] == "QUEUED" and not have:
                conn.execute("UPDATE jobs SET state='WAITING_FOR_INPUTS', error_code='PROFILE_BUNDLE_UNAVAILABLE' "
                             "WHERE id=?", (j["id"],))
                conn.execute("UPDATE renders SET state='WAITING_FOR_INPUTS' WHERE id=?", (j["render_id"],))
                parked.append(JobResult(j["id"], j["render_id"], "WAITING_FOR_INPUTS", "PROFILE_BUNDLE_UNAVAILABLE",
                                        j["bundle_hash"]))
            elif j["state"] == "WAITING_FOR_INPUTS" and have:
                conn.execute("UPDATE jobs SET state='QUEUED', error_code=NULL WHERE id=?", (j["id"],))
                conn.execute("UPDATE renders SET state='QUEUED' WHERE id=?", (j["render_id"],))
                unparked += 1
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return parked, unparked


def run_one(conn: sqlite3.Connection, store: Store, bundles: Bundles,
            skip: set[int] = frozenset()) -> JobResult | None:
    job = _claim(conn, skip)
    if not job:
        return None
    r = conn.execute(
        "SELECT r.*, rc.json AS recipe_json, rc.bundle_hash, f.roll_id, f.capture_time, a.path AS original_path, a.sha256 AS original_sha256 "
        "FROM renders r JOIN recipes rc ON rc.id=r.recipe_id "
        "JOIN frames f ON f.device_id=r.device_id AND f.id=r.frame_id JOIN assets a ON a.id=f.original_asset_id "
        "WHERE r.id=?", (job["render_id"],)).fetchone()
    recipe = json.loads(r["recipe_json"])
    dest_dir = store.root / "renders" / safe_id(r["device_id"]) / safe_id(r["roll_id"])
    dest = dest_dir / f"{r['id']}.jpg"
    try:
        bundle = bundles.get(r["bundle_hash"])
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
    except BundleUnavailable as e:            # removed between park check and claim
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE jobs SET state='WAITING_FOR_INPUTS', attempt=attempt-1, error_code=? WHERE id=?",
                     (e.code, job["id"]))
        conn.execute("UPDATE renders SET state='WAITING_FOR_INPUTS' WHERE id=?", (r["id"],))
        conn.execute("COMMIT")
        return JobResult(job["id"], r["id"], "WAITING_FOR_INPUTS", e.code, e.sha)
    except (DevelopError, core.CoreError) as e:
        state = "FAILED_TERMINAL" if e.code in TERMINAL_CODES else "FAILED_RETRYABLE"
        _finish(conn, job, state, e.code)
        return JobResult(job["id"], r["id"], state, e.code, e.detail)
    except OSError as e:
        _finish(conn, job, "FAILED_RETRYABLE", "IO_ERROR")
        return JobResult(job["id"], r["id"], "FAILED_RETRYABLE", "IO_ERROR", str(e))


def _drain_web(conn: sqlite3.Connection, store: Store, bundles: Bundles, tried: set[int], cfg=None) -> JobResult | None:
    """Web Darkroom items share the camera queue's lock, memory budget and process model."""
    from .darkroom import jobs as web_jobs
    res = web_jobs.run_one(conn, store, bundles, {-i for i in tried if i < 0}, cfg)
    if res is None:
        return None
    iid, rid, state, code, detail = res
    return JobResult(-iid, rid or "", "COMMITTED" if state == "COMPLETE" else state, code, detail)


def _drain(conn: sqlite3.Connection, store: Store, bundles: Bundles, budget) -> list[JobResult]:
    """Develop queued jobs until none is left or the shared budget is spent."""
    done: list[JobResult] = []
    tried: set[int] = set()           # a retryable failure waits for the next run (in this process)
    while True:
        if budget is not None:
            with budget.get_lock():
                if budget.value <= 0:
                    break
                budget.value -= 1
        res = run_one(conn, store, bundles, tried) or _drain_web(conn, store, bundles, tried)
        if res is None:
            if budget is not None:
                with budget.get_lock():
                    budget.value += 1
            break
        tried.add(res.job_id)
        done.append(res)
    return done


def _child(root: str, budget, out) -> None:
    from . import db
    store = Store(Path(root))
    conn = db.connect(store.db_path)
    try:
        out.put([r.__dict__ for r in _drain(conn, store, Bundles(store), budget)])
    except BaseException as e:          # report, never hang the parent
        out.put({"error": repr(e)})
        raise
    finally:
        conn.close()


class WorkerBusy(Exception):
    """Another worker pass holds this data directory."""


def run(conn: sqlite3.Connection, store: Store, *, max_jobs: int | None = None, jobs: int = 1) -> list[JobResult]:
    """One worker pass. jobs > 1 develops that many frames at once in child
    processes (each ~0.9 GB at full size: size it by memory, not cores).
    Only one pass runs per data directory at a time (an exclusive lock on
    <data>/worker.lock; raises WorkerBusy otherwise): stale RUNNING jobs are
    recovered at the start of a pass, which is only safe when no other pass
    is developing them (the service worker and camera-sync --run collided on
    2026-11-04 and developed three frames twice)."""
    import fcntl
    lock = open(store.root / "worker.lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise WorkerBusy("another worker pass is running on this data directory") from None
    try:
        res = _run_locked(conn, store, max_jobs=max_jobs, jobs=jobs)
        _publish_web(conn, store)
        return res
    finally:
        lock.close()


def _publish_web(conn: sqlite3.Connection, store: Store) -> None:
    """Web Darkroom publication stage (copy, index, album link) after the developing."""
    import sys

    from . import config as config_mod
    from .darkroom import publish
    try:
        cfg = config_mod.load(None)
        if cfg.photoprism.export_dir or conn.execute(
                "SELECT 1 FROM darkroom_jobs WHERE publish IS NOT NULL LIMIT 1").fetchone():
            publish.publish_pending(conn, store, cfg.photoprism)
    except Exception as e:      # noqa: BLE001 - publication trouble must never stop camera work
        print(f"web publication pass failed: {type(e).__name__}: {e}", file=sys.stderr)


def _run_locked(conn: sqlite3.Connection, store: Store, *, max_jobs: int | None, jobs: int) -> list[JobResult]:
    recover_stale(conn)
    from .darkroom import jobs as web_jobs
    web_jobs.recover_stale(conn)
    bundles = Bundles(store)
    bundles.ensure_default()
    parked, _ = park_and_unpark(conn, bundles)
    if jobs <= 1:
        budget = None
        if max_jobs is not None:
            import multiprocessing as mp
            budget = mp.Value("i", max_jobs)
        return parked + _drain(conn, store, bundles, budget)
    import multiprocessing as mp
    ctx = mp.get_context("spawn")     # fresh interpreter: no inherited sqlite handle
    budget = ctx.Value("i", max_jobs if max_jobs is not None else 1 << 30)
    out = ctx.Queue()
    procs = [ctx.Process(target=_child, args=(str(store.root), budget, out), daemon=True) for _ in range(jobs)]
    for pr in procs:
        pr.start()
    done: list[JobResult] = []
    errors = []
    pending = len(procs)
    while pending:
        try:
            got = out.get(timeout=5)
        except queue.Empty:           # a child killed outright (OOM) never reports
            if all(not pr.is_alive() for pr in procs):
                errors.append(f"{pending} child process(es) died: exit codes {[pr.exitcode for pr in procs]}")
                break
            continue
        pending -= 1
        if isinstance(got, dict):
            errors.append(got["error"])
        else:
            done += [JobResult(**r) for r in got]
    for pr in procs:
        pr.join()
    if errors:
        raise RuntimeError(f"worker child failed: {errors[0]}")
    done.sort(key=lambda r: r.job_id)
    return parked + done
