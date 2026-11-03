# SPDX-License-Identifier: GPL-2.0-only
"""Camera offline renditions (docs/07 "Offline execution", docs/08 "Handling
offline renders"): a JPEG the camera developed itself, uploaded as
media_role=camera_render together with the render record it claims.

The server cannot re-check the camera's pixels, so it checks the identity:
the recipe must be the roll's frozen film + bundle, the grain seed must be
the one derived for that frame, and render_id must recompute from the frame's
declared original hash, the recipe and the camera's film_core_version. Such a
file is kept as an origin=camera alternate under offline-renders/; it is
never published and never stands in for the canonical linux rendition.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path

from .develop import recipe_seed
from .ids import canonical_json, render_id, sha256_file
from .store import Store, safe_id

MAX_SIDE = 8192                    # SX510 HS sensor output is 4608x3456; anything larger is not a camera render


class CameraRenderError(Exception):
    def __init__(self, status: int, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.status, self.code, self.detail = status, code, detail


def check_declared(roll: sqlite3.Row, frame: sqlite3.Row, body: dict) -> dict:
    """Validate an upload init for a camera render; returns the record to keep with the session."""
    if body.get("media_type") != "image/jpeg":
        raise CameraRenderError(422, "UNSUPPORTED_MEDIA_TYPE", "camera_render must be image/jpeg")
    rec = body.get("render")
    if not isinstance(rec, dict):
        raise CameraRenderError(400, "BAD_REQUEST", "camera_render needs a 'render' record")
    try:
        recipe = rec["recipe"]
        core_version = str(rec["film_core_version"])
        seed_hex = str(rec["grain_seed"]).lower()
        rid = str(rec["render_id"]).lower()
        w, h = int(rec["output_width"]), int(rec["output_height"])
        if not isinstance(recipe, dict):
            raise TypeError("recipe")
        profile, bundle = recipe["film_profile_id"], str(recipe["profile_bundle_hash"]).lower()
        spec = recipe.get("output_spec", {})
    except (KeyError, TypeError, ValueError) as e:
        raise CameraRenderError(400, "BAD_REQUEST", f"render record: {e}") from None
    if profile != roll["film_profile_id"] or bundle != roll["profile_bundle_hash"].lower():
        raise CameraRenderError(409, "PROFILE_BUNDLE_MISMATCH",
                                "a camera render must use the roll's frozen film and bundle")
    if spec.get("format", "image/jpeg") != "image/jpeg":
        raise CameraRenderError(422, "UNSUPPORTED_RECIPE", "output_spec.format")
    if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE):
        raise CameraRenderError(422, "BAD_CAMERA_RENDER", f"output {w}x{h}")
    try:
        seed = recipe_seed(recipe, roll["device_id"], roll["id"], frame["id"])
    except (KeyError, TypeError, ValueError) as e:
        raise CameraRenderError(400, "BAD_REQUEST", f"recipe: {e}") from None
    if seed_hex != f"{seed:016x}":
        raise CameraRenderError(409, "GRAIN_SEED_MISMATCH", f"expected {seed:016x} for this frame")
    want = render_id(original_sha256=frame["declared_sha256"], recipe=recipe, film_core_version=core_version,
                     profile_bundle_hash=bundle, output_spec=spec,
                     input_normalization_version=str(recipe.get("input_normalization_version", "")),
                     grain_seed=seed)
    if rid != want:
        raise CameraRenderError(409, "RENDER_IDENTITY_MISMATCH", f"render_id should be {want}")
    return {"render_id": rid, "recipe": recipe, "film_core_version": core_version, "grain_seed": seed_hex,
            "output_width": w, "output_height": h, "original_sha256": frame["declared_sha256"],
            "camera": {k: rec[k] for k in ("developed_at", "elapsed_s", "core_build") if k in rec}}


def existing(conn: sqlite3.Connection, render_id_: str) -> sqlite3.Row | None:
    return conn.execute("SELECT r.*, a.sha256 FROM renders r LEFT JOIN assets a ON a.id=r.asset_id WHERE r.id=?",
                        (render_id_,)).fetchone()


def _check_jpeg(path: Path, w: int, h: int) -> None:
    from PIL import Image, UnidentifiedImageError
    try:
        with Image.open(path) as im:
            fmt, size = im.format, im.size
            im.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise CameraRenderError(422, "BAD_CAMERA_RENDER", f"not a readable JPEG: {e}") from None
    if fmt != "JPEG" or size != (w, h):
        raise CameraRenderError(422, "BAD_CAMERA_RENDER", f"{fmt} {size[0]}x{size[1]}, declared {w}x{h}")


def commit(conn: sqlite3.Connection, store: Store, upload: sqlite3.Row, part: Path, sha: str, nbytes: int) -> None:
    """Promote a verified upload into offline-renders/ and record the origin=camera rendition."""
    meta = json.loads(upload["meta"])
    rid = meta["render_id"]
    _check_jpeg(part, meta["output_width"], meta["output_height"])
    dest = (store.root / "offline-renders" / safe_id(upload["device_id"]) / safe_id(upload["roll_id"])
            / f"{safe_id(rid)}.jpg")
    have = existing(conn, rid)
    if have is not None and have["sha256"] and have["sha256"] != sha:
        raise CameraRenderError(409, "RENDER_CONFLICT", "this render_id already has different pixels")
    if dest.exists():
        if sha256_file(dest)[0] != sha:
            raise CameraRenderError(409, "ARCHIVE_HASH_CONFLICT", "")
        part.unlink()
    else:
        side = dest.with_suffix(".jpg.json")
        if not side.exists():
            prov = {**meta, "developed_by": "camera", "output_sha256": sha, "output_bytes": nbytes,
                    "device_id": upload["device_id"], "roll_id": upload["roll_id"], "frame_id": upload["frame_id"],
                    "received_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "output": str(dest.relative_to(store.root))}
            Store.promote(store.stage_bytes((json.dumps(prov, indent=2) + "\n").encode()), side)
        Store.promote(part, dest)     # the JPEG last: its presence means the pair is complete
    recipe_json = canonical_json(meta["recipe"]).decode()
    recipe_key = hashlib.sha256(recipe_json.encode()).hexdigest()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT OR IGNORE INTO assets(sha256, bytes, mime, kind, path) VALUES (?,?,?,?,?)",
                     (sha, nbytes, "image/jpeg", "offline_jpeg", str(dest.relative_to(store.root))))
        aid = conn.execute("SELECT id FROM assets WHERE sha256=?", (sha,)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO recipes(id, json, core_revision, bundle_hash) VALUES (?,?,?,?)",
                     (recipe_key, recipe_json, meta["film_core_version"],
                      meta["recipe"]["profile_bundle_hash"].lower()))
        spec = json.dumps(meta["recipe"].get("output_spec", {}), sort_keys=True)
        conn.execute("INSERT OR IGNORE INTO renders(id, device_id, frame_id, recipe_id, output_spec, asset_id, origin,"
                     " state) VALUES (?,?,?,?,?,?, 'camera', 'COMMITTED')",
                     (rid, upload["device_id"], upload["frame_id"], recipe_key, spec, aid))
        conn.execute("UPDATE uploads SET state='COMPLETE' WHERE id=?", (upload["id"],))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
