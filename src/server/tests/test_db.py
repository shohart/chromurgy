# SPDX-License-Identifier: GPL-2.0-only
import sqlite3

import pytest

from mfilm_server import db


def test_migrate_is_idempotent(store):
    c = db.connect(store.db_path)
    assert db.migrate(c) == len(db.MIGRATIONS)
    assert db.migrate(c) == len(db.MIGRATIONS)
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_no_single_synced_state(conn):
    conn.execute("INSERT INTO devices(id) VALUES ('d')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO rolls(id, device_id, film_profile_id, profile_bundle_hash, roll_length, "
                      "expected_frames, camera_state, manifest_sha256, state) "
                      "VALUES ('r','d','p','h',12,1,'SEALED','m','SYNCED')")


def test_asset_sha_unique(conn):
    conn.execute("INSERT INTO assets(sha256, bytes, mime, kind, path) VALUES (?,1,'x','original_dng','a')", ("a" * 64,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO assets(sha256, bytes, mime, kind, path) VALUES (?,1,'x','original_dng','b')", ("a" * 64,))
