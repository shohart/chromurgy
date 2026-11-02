# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import json
from pathlib import Path

import pytest

from mfilm_server import db
from mfilm_server.store import Store

REPO = Path(__file__).resolve().parents[3]


def fake_dng(seed: int, size: int = 4096) -> bytes:
    """TIFF-magic bytes + deterministic filler. NOT a real DNG: importer-level fixture only."""
    body = hashlib.sha256(str(seed).encode()).digest() * (size // 32)
    return b"II*\x00" + body[: size - 4]


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "data")
    s.init()
    return s


@pytest.fixture
def conn(store):
    c = db.connect(store.db_path)
    db.migrate(c)
    yield c
    c.close()


@pytest.fixture
def make_card(tmp_path):
    """Build a fake SD card: DCIM originals + CHDK/MFILM/ROLLS/<roll>/manifest.json."""
    def _make(name="card", roll_id="11111111-2222-4333-8444-555555555555", frames=2, roll_length=12,
              state="SEALED", device_id="sx510hs-demo-001", mutate=None):
        card = tmp_path / name
        dcim = card / "DCIM" / "100CANON"
        dcim.mkdir(parents=True, exist_ok=True)
        entries = []
        for i in range(1, frames + 1):
            data = fake_dng(hash((roll_id, i)) & 0xFFFF)
            (dcim / f"IMG_{i:04}.DNG").write_bytes(data)
            entries.append({
                "frame_id": f"{roll_id}-{i:04}", "ordinal": i, "captured_at": "2026-11-02T12:01:00Z",
                "source_path": f"A/DCIM/100CANON/IMG_{i:04}.DNG", "source_size_bytes": len(data),
                "source_sha256": hashlib.sha256(data).hexdigest(), "original_status": "VERIFIED"})
        doc = {"schema_version": 1, "kind": "mfilm.roll_manifest", "device_id": device_id, "roll_id": roll_id,
               "roll_state": state, "roll_length": roll_length, "captured_frames": frames,
               "film_profile_id": "portra400", "profile_bundle_hash": "b" * 64,
               "created_at": "2026-11-02T12:00:00Z", "sealed_at": "2026-11-02T12:05:00Z",
               "render_recipe_id": "recipe-portra400-demo-v1", "frames": entries}
        if mutate:
            mutate(doc, card)
        mdir = card / "CHDK" / "MFILM" / "ROLLS" / roll_id
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "manifest.json").write_text(json.dumps(doc, indent=2))
        return card
    return _make
