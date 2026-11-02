# SPDX-License-Identifier: GPL-2.0-only
"""Device pairing and bearer tokens (docs/12). Only SHA-256 of a token is stored."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3

from .store import safe_id


def pair(conn: sqlite3.Connection, device_id: str) -> str:
    """Register (or re-key) a device; returns a new token, shown once."""
    safe_id(device_id, "device_id")
    token = secrets.token_urlsafe(32)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT OR IGNORE INTO devices(id) VALUES (?)", (device_id,))
        conn.execute("UPDATE devices SET status='ACTIVE' WHERE id=?", (device_id,))
        conn.execute("INSERT INTO device_tokens(token_sha256, device_id) VALUES (?,?)",
                     (hashlib.sha256(token.encode()).hexdigest(), device_id))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return token


def revoke(conn: sqlite3.Connection, device_id: str) -> int:
    conn.execute("BEGIN IMMEDIATE")
    n = conn.execute("UPDATE device_tokens SET revoked_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                     "WHERE device_id=? AND revoked_at IS NULL", (device_id,)).rowcount
    conn.execute("UPDATE devices SET status='REVOKED' WHERE id=?", (device_id,))
    conn.execute("COMMIT")
    return n


def authenticate(conn: sqlite3.Connection, token: str) -> str | None:
    row = conn.execute(
        "SELECT t.device_id FROM device_tokens t JOIN devices d ON d.id=t.device_id "
        "WHERE t.token_sha256=? AND t.revoked_at IS NULL AND d.status='ACTIVE'",
        (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    return row[0] if row else None
