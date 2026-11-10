# SPDX-License-Identifier: GPL-2.0-only
"""SQLite catalog (docs/08 data model) with versioned migrations.

State machines stay separate (docs/04): a roll's server intake state, each
frame original's state, each render's state, each job and each publication
have their own column. There is deliberately no single "SYNCED" status.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROLL_SERVER_STATES = ("RECEIVING", "INPUTS_COMPLETE")
FRAME_ORIGINAL_STATES = ("DECLARED", "VERIFIED", "ERROR")
RENDER_STATES = ("WAITING_FOR_INPUTS", "QUEUED", "RUNNING", "COMMITTED", "PUBLISHED",
                 "FAILED_RETRYABLE", "FAILED_TERMINAL")
UPLOAD_STATES = ("OPEN", "COMPLETE", "ABORTED")
PUBLICATION_STATES = ("PENDING", "EXPORTED", "INDEXED", "FAILED")


def _enum(col: str, values: tuple[str, ...]) -> str:
    return f"CHECK ({col} IN ({', '.join(repr(v) for v in values)}))"


MIGRATIONS: list[str] = [
    # 1: initial catalog
    f"""
    CREATE TABLE devices (
        id            TEXT PRIMARY KEY,
        key_id        TEXT,
        status        TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'REVOKED')),
        created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        last_seen_at  TEXT
    );
    CREATE TABLE assets (
        id            INTEGER PRIMARY KEY,
        sha256        TEXT NOT NULL UNIQUE CHECK (length(sha256) = 64),
        bytes         INTEGER NOT NULL CHECK (bytes > 0),
        mime          TEXT NOT NULL,
        kind          TEXT NOT NULL CHECK (kind IN ('original_dng', 'render_jpeg', 'offline_jpeg', 'manifest')),
        path          TEXT NOT NULL UNIQUE,
        created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE TABLE rolls (
        id                 TEXT NOT NULL,
        device_id          TEXT NOT NULL REFERENCES devices(id),
        film_profile_id    TEXT NOT NULL,
        profile_bundle_hash TEXT NOT NULL,
        render_recipe_id   TEXT,
        roll_length        INTEGER NOT NULL CHECK (roll_length IN (12, 24, 36)),
        expected_frames    INTEGER NOT NULL,
        camera_state       TEXT NOT NULL,
        manifest_sha256    TEXT NOT NULL,
        created_at         TEXT,
        sealed_at          TEXT,
        state              TEXT NOT NULL {_enum('state', ROLL_SERVER_STATES)},
        received_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        PRIMARY KEY (device_id, id)
    );
    CREATE TABLE frames (
        id                 TEXT NOT NULL,
        device_id          TEXT NOT NULL,
        roll_id            TEXT NOT NULL,
        ordinal            INTEGER NOT NULL CHECK (ordinal BETWEEN 1 AND 36),
        capture_time       TEXT,
        declared_sha256    TEXT NOT NULL,
        declared_bytes     INTEGER NOT NULL,
        source_path        TEXT NOT NULL,
        original_asset_id  INTEGER REFERENCES assets(id),
        original_state     TEXT NOT NULL {_enum('original_state', FRAME_ORIGINAL_STATES)},
        error_code         TEXT,
        PRIMARY KEY (device_id, id),
        UNIQUE (device_id, roll_id, ordinal),
        FOREIGN KEY (device_id, roll_id) REFERENCES rolls(device_id, id)
    );
    CREATE TABLE uploads (
        id               TEXT PRIMARY KEY,
        device_id        TEXT NOT NULL REFERENCES devices(id),
        roll_id          TEXT NOT NULL,
        frame_id         TEXT,
        media_role       TEXT NOT NULL,
        declared_sha256  TEXT NOT NULL,
        declared_bytes   INTEGER NOT NULL,
        offset_bytes     INTEGER NOT NULL DEFAULT 0,
        state            TEXT NOT NULL {_enum('state', UPLOAD_STATES)},
        updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE TABLE recipes (
        id               TEXT PRIMARY KEY,
        json             TEXT NOT NULL,
        core_revision    TEXT NOT NULL,
        bundle_hash      TEXT NOT NULL
    );
    CREATE TABLE renders (
        id               TEXT PRIMARY KEY,            -- render_id (sha256)
        device_id        TEXT NOT NULL,
        frame_id         TEXT NOT NULL,
        recipe_id        TEXT NOT NULL REFERENCES recipes(id),
        output_spec      TEXT NOT NULL,
        asset_id         INTEGER REFERENCES assets(id),
        origin           TEXT NOT NULL CHECK (origin IN ('linux', 'camera')),
        state            TEXT NOT NULL {_enum('state', RENDER_STATES)},
        FOREIGN KEY (device_id, frame_id) REFERENCES frames(device_id, id)
    );
    CREATE TABLE jobs (
        id               INTEGER PRIMARY KEY,
        render_id        TEXT NOT NULL REFERENCES renders(id),
        attempt          INTEGER NOT NULL DEFAULT 0,
        state            TEXT NOT NULL {_enum('state', RENDER_STATES)},
        error_code       TEXT,
        created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        started_at       TEXT,
        finished_at      TEXT
    );
    CREATE TABLE publications (
        id               INTEGER PRIMARY KEY,
        render_id        TEXT NOT NULL REFERENCES renders(id),
        destination      TEXT NOT NULL,
        status           TEXT NOT NULL {_enum('status', PUBLICATION_STATES)},
        UNIQUE (render_id, destination)
    );
    """,
    # 2: queue lookups
    """
    CREATE INDEX jobs_state ON jobs(state, id);
    CREATE INDEX renders_frame ON renders(device_id, frame_id)
    """,
    # 3: device credentials (only the token's hash is stored)
    """
    CREATE TABLE device_tokens (
        token_sha256  TEXT PRIMARY KEY CHECK (length(token_sha256) = 64),
        device_id     TEXT NOT NULL REFERENCES devices(id),
        created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        revoked_at    TEXT
    );
    CREATE INDEX uploads_frame ON uploads(device_id, frame_id, declared_sha256, state)
    """,
    # 4: declared render record of a camera_render upload (JSON), checked at init, used at complete
    """
    ALTER TABLE uploads ADD COLUMN meta TEXT
    """,
    # 5: Web Darkroom (docs/web/30). Additive only: a web batch is NOT a camera roll, so none of the
    # camera tables (CHECKs on ordinal/roll_length/asset kind, FKs to frames) is touched or reused.
    """
    CREATE TABLE sources (
        id           TEXT PRIMARY KEY,
        sha256       TEXT NOT NULL CHECK (length(sha256) = 64),
        origin       TEXT NOT NULL CHECK (origin IN ('upload', 'photoprism', 'camera_roll')),
        filename     TEXT NOT NULL,
        format       TEXT NOT NULL,
        bytes        INTEGER NOT NULL,
        path         TEXT NOT NULL,
        eligible     INTEGER NOT NULL DEFAULT 1,
        reason       TEXT,
        meta         TEXT NOT NULL DEFAULT '{}',
        provenance   TEXT NOT NULL DEFAULT '{}',
        created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE INDEX sources_sha ON sources(sha256);
    CREATE TABLE web_uploads (
        id               TEXT PRIMARY KEY,
        filename         TEXT NOT NULL,
        declared_bytes   INTEGER NOT NULL,
        declared_sha256  TEXT,
        offset_bytes     INTEGER NOT NULL DEFAULT 0,
        state            TEXT NOT NULL CHECK (state IN ('OPEN', 'COMPLETE', 'ABORTED')),
        source_id        TEXT,
        error_code       TEXT,
        created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE TABLE web_sessions (
        token_sha256 TEXT PRIMARY KEY CHECK (length(token_sha256) = 64),
        created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        expires_at   TEXT NOT NULL,
        revoked_at   TEXT
    )
    """,
    # 6: Web Darkroom jobs. Job state is derived from its items; only cancellation is stored on the job.
    """
    CREATE TABLE darkroom_jobs (
        id               TEXT PRIMARY KEY,
        idempotency_key  TEXT UNIQUE,
        request          TEXT NOT NULL,
        recipe           TEXT NOT NULL,
        recipe_hash      TEXT NOT NULL,
        cancel_requested INTEGER NOT NULL DEFAULT 0,
        created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE TABLE web_renders (
        id          TEXT PRIMARY KEY,
        source_id   TEXT NOT NULL REFERENCES sources(id),
        recipe_hash TEXT NOT NULL,
        recipe      TEXT NOT NULL,
        path        TEXT NOT NULL UNIQUE,
        sha256      TEXT NOT NULL,
        bytes       INTEGER NOT NULL,
        width       INTEGER NOT NULL,
        height      INTEGER NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE INDEX web_renders_source ON web_renders(source_id, created_at);
    CREATE TABLE darkroom_items (
        id           INTEGER PRIMARY KEY,
        job_id       TEXT NOT NULL REFERENCES darkroom_jobs(id),
        source_id    TEXT NOT NULL REFERENCES sources(id),
        source_sha256 TEXT NOT NULL,
        ordinal      INTEGER NOT NULL,
        state        TEXT NOT NULL CHECK (state IN ('QUEUED','DECODING','RENDERING','VALIDATING','STAGED',
                         'PUBLISHING','INDEXING','ALBUM_LINKING','COMPLETE','FAILED','CANCELLED')),
        attempt      INTEGER NOT NULL DEFAULT 0,
        render_id    TEXT REFERENCES web_renders(id),
        error_code   TEXT,
        error_detail TEXT,
        started_at   TEXT,
        finished_at  TEXT,
        UNIQUE (job_id, source_id)
    );
    CREATE INDEX darkroom_items_state ON darkroom_items(state, id)
    """,
    # 7: publication of web renders (docs/web/32): per item destination state, per job album
    """
    ALTER TABLE darkroom_jobs ADD COLUMN publish TEXT;
    ALTER TABLE darkroom_jobs ADD COLUMN album_uid TEXT;
    ALTER TABLE darkroom_items ADD COLUMN pub_path TEXT;
    ALTER TABLE darkroom_items ADD COLUMN pp_photo_uid TEXT;
    ALTER TABLE darkroom_items ADD COLUMN pub_attempts INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE darkroom_items ADD COLUMN pub_note TEXT
    """,
    # 8: operator's saved Darkroom presets (look + film + optics + adjustments as one named UI state)
    """
    CREATE TABLE darkroom_presets (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE,
        state       TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    # 9: creative color grade user presets
    """
    CREATE TABLE color_grade_presets (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        data        TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
    # 10: MCP versioned recipe drafts
    """
    CREATE TABLE mcp_drafts (
        id          TEXT PRIMARY KEY,
        asset_id    TEXT NOT NULL REFERENCES sources(id),
        revision    INTEGER NOT NULL DEFAULT 1,
        recipe      TEXT NOT NULL,
        recipe_hash TEXT NOT NULL,
        created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE INDEX mcp_drafts_asset ON mcp_drafts(asset_id);
    """,
]


def connect(path: Path, *, threads: bool = False) -> sqlite3.Connection:
    """threads=True: the connection may hop threads (one request at a time, FastAPI threadpool)."""
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=not threads)   # explicit BEGIN/COMMIT
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; returns the resulting schema version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.execute("BEGIN IMMEDIATE")
        try:
            for stmt in filter(str.strip, sql.split(";")):
                conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {i}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        version = i
    return version
