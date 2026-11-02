# SPDX-License-Identifier: GPL-2.0-only
"""Content identities (docs/04, docs/05)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CHUNK = 1 << 20


def sha256_file(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def canonical_json(obj: Any) -> bytes:
    """Sorted keys, no whitespace, UTF-8, no NaN: the bytes hashed for identities."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def render_id(*, original_sha256: str, recipe: dict, film_core_version: str,
              profile_bundle_hash: str, output_spec: dict, input_normalization_version: str) -> str:
    """render_id = sha256(canonical JSON of everything that changes the pixels)."""
    return hashlib.sha256(canonical_json({
        "v": "mfilm-render-id-v1",
        "original_sha256": original_sha256.lower(),
        "recipe": recipe,
        "film_core_version": film_core_version,
        "profile_bundle_hash": profile_bundle_hash.lower(),
        "output_spec": output_spec,
        "input_normalization_version": input_normalization_version,
    })).hexdigest()


def frame_seed(device_id: str, roll_id: str, frame_id: str, profile_id: str,
               recipe_version: str, user_seed: int = 0) -> int:
    """Must equal mf_frame_seed() in the C core (tested against it)."""
    parts = ["mfilm-seed-v1", device_id, roll_id, frame_id, profile_id, recipe_version]
    data = b"".join(p.encode("utf-8") + b"\0" for p in parts) + str(user_seed).encode()
    return int.from_bytes(hashlib.sha256(data).digest()[:8], "big")
