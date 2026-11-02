# SPDX-License-Identifier: GPL-2.0-only
"""Load and validate the wire contracts in <repo>/contracts."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import jsonschema

MAX_MANIFEST_BYTES = 256 * 1024


def contracts_dir() -> Path:
    env = os.environ.get("MFILM_CONTRACTS_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[3] / "contracts"


@lru_cache(maxsize=None)
def _validator(name: str) -> jsonschema.protocols.Validator:
    schema = json.loads((contracts_dir() / name).read_text(encoding="utf-8"))
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema, format_checker=cls.FORMAT_CHECKER)


class ManifestError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def load_roll_manifest(raw: bytes) -> dict:
    """Parse + schema-validate + semantic checks. Raises ManifestError."""
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestError("MANIFEST_TOO_LARGE", f"{len(raw)} bytes")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ManifestError("MANIFEST_NOT_JSON", str(e)) from None
    errors = sorted(_validator("roll-manifest.schema.json").iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        e = errors[0]
        raise ManifestError("MANIFEST_SCHEMA", f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}")
    frames = doc["frames"]
    ordinals = [f["ordinal"] for f in frames]
    if len(set(ordinals)) != len(ordinals):
        raise ManifestError("MANIFEST_DUPLICATE_ORDINAL", str(ordinals))
    if len({f["frame_id"] for f in frames}) != len(frames):
        raise ManifestError("MANIFEST_DUPLICATE_FRAME_ID", "")
    if doc["captured_frames"] != len(frames):
        raise ManifestError("MANIFEST_FRAME_COUNT", f"captured_frames={doc['captured_frames']} frames={len(frames)}")
    if doc["captured_frames"] > doc["roll_length"]:
        raise ManifestError("MANIFEST_FRAME_COUNT", "more frames than the roll holds")
    return doc
