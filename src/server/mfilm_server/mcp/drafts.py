# SPDX-License-Identifier: GPL-2.0-only
"""MCP Recipe Drafts manager with optimistic concurrency (docs/39, docs/40)."""
from __future__ import annotations

import copy
import json
import sqlite3
import uuid
from typing import Any

from .. import core
from ..darkroom import combos, recipe2
from .errors import ConflictRevisionError, McpDomainError, RecipeInvalidError


def json_merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7396 JSON Merge Patch."""
    if isinstance(patch, dict):
        if not isinstance(target, dict):
            target = {}
        result = dict(target)
        for key, value in patch.items():
            if value is None:
                result.pop(key, None)
            else:
                result[key] = json_merge_patch(result.get(key), value)
        return result
    return patch


def _normalize_patch(patch: dict[str, Any]) -> dict[str, Any]:
    p = copy.deepcopy(patch)
    ext = p.setdefault("extensions", {})
    if "tone" in p:
        t = p.pop("tone")
        if isinstance(t, dict):
            if "brightness" in t and "brightness_ev" not in t:
                t["brightness_ev"] = t.pop("brightness")
            if "develop" in t and "develop_strength" not in t:
                t["develop_strength"] = t.pop("develop")
        ext["tone"] = t
    if "white_balance" in p:
        ext["white_balance"] = p.pop("white_balance")
    if "wb_profile" in p:
        ext["wb_profile"] = p.pop("wb_profile")
    if not ext and "extensions" in p:
        p.pop("extensions")
    return p


def default_recipe_for_asset(bundle: core.Bundle) -> dict[str, Any]:
    """Default baseline Render Recipe v2."""
    return recipe2.default("portra400", bundle)


def create_draft(
    conn: sqlite3.Connection,
    bundle: core.Bundle,
    asset_id: str,
    preset_id: str | None = None,
    recipe: dict[str, Any] | None = None
) -> dict[str, Any]:
    # Check that source asset exists
    cur = conn.cursor()
    cur.execute("SELECT id, sha256 FROM sources WHERE id = ?", (asset_id,))
    row = cur.fetchone()
    if not row:
        raise McpDomainError("ASSET_NOT_FOUND", f"Asset '{asset_id}' not found in catalog")

    draft_id = f"draft_{uuid.uuid4().hex[:16]}"

    if recipe is not None:
        base = default_recipe_for_asset(bundle)
        rec = json_merge_patch(base, _normalize_patch(recipe))
    elif preset_id:
        combo = combos.get(preset_id)
        if combo:
            res_combo = combos.resolve(combo, bundle)
            rec = res_combo["recipe"]
        else:
            rec = default_recipe_for_asset(bundle)
            # If preset matches camera look or film stock
            try:
                rec["film"]["id"] = recipe2.resolve_film(preset_id, bundle)
            except Exception:
                pass
    else:
        rec = default_recipe_for_asset(bundle)

    try:
        norm_r = recipe2.normalize(rec, bundle)
    except Exception as e:
        raise RecipeInvalidError(f"Recipe validation failed: {e}")

    rec_hash = recipe2.recipe_hash(norm_r)
    rec_json = json.dumps(norm_r, sort_keys=True)

    cur.execute(
        "INSERT INTO mcp_drafts (id, asset_id, revision, recipe, recipe_hash) VALUES (?, ?, 1, ?, ?)",
        (draft_id, asset_id, rec_json, rec_hash)
    )

    return {
        "draft_id": draft_id,
        "asset_id": asset_id,
        "revision": 1,
        "recipe": norm_r,
        "recipe_hash": rec_hash
    }


def get_draft(conn: sqlite3.Connection, draft_id: str) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, asset_id, revision, recipe, recipe_hash, created_at, updated_at FROM mcp_drafts WHERE id = ?",
        (draft_id,)
    )
    row = cur.fetchone()
    if not row:
        raise McpDomainError("DRAFT_NOT_FOUND", f"Draft '{draft_id}' not found")

    rec = json.loads(row[3])
    return {
        "draft_id": row[0],
        "asset_id": row[1],
        "revision": row[2],
        "recipe": rec,
        "recipe_hash": row[4],
        "created_at": row[5],
        "updated_at": row[6]
    }


def update_draft(
    conn: sqlite3.Connection,
    bundle: core.Bundle,
    draft_id: str,
    expected_revision: int,
    patch: dict[str, Any]
) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, asset_id, revision, recipe FROM mcp_drafts WHERE id = ?",
        (draft_id,)
    )
    row = cur.fetchone()
    if not row:
        raise McpDomainError("DRAFT_NOT_FOUND", f"Draft '{draft_id}' not found")

    actual_rev = row[2]
    if expected_revision != actual_rev:
        raise ConflictRevisionError(draft_id, expected=expected_revision, actual=actual_rev)

    current_rec = json.loads(row[3])
    patched_rec = json_merge_patch(current_rec, _normalize_patch(patch))

    try:
        norm_r = recipe2.normalize(patched_rec, bundle)
    except Exception as e:
        raise RecipeInvalidError(f"Patched recipe invalid: {e}")

    new_hash = recipe2.recipe_hash(norm_r)
    new_json = json.dumps(norm_r, sort_keys=True)
    new_rev = actual_rev + 1

    cur.execute(
        "UPDATE mcp_drafts SET revision = ?, recipe = ?, recipe_hash = ?, updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ','now')) WHERE id = ? AND revision = ?",
        (new_rev, new_json, new_hash, draft_id, actual_rev)
    )
    if cur.rowcount == 0:
        # Concurrent modification happened
        cur.execute("SELECT revision FROM mcp_drafts WHERE id = ?", (draft_id,))
        latest = cur.fetchone()
        raise ConflictRevisionError(draft_id, expected=expected_revision, actual=latest[0] if latest else -1)

    return {
        "draft_id": draft_id,
        "asset_id": row[1],
        "revision": new_rev,
        "recipe": norm_r,
        "recipe_hash": new_hash
    }
