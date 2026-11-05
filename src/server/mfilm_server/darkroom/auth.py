# SPDX-License-Identifier: GPL-2.0-only
"""Operator login for the Web Darkroom (docs/web/33): one password, scrypt-hashed
in <data>/web/auth.json (0600); browser sessions are random tokens whose SHA-256
is stored. Device (camera) tokens are a different credential and never valid here."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from pathlib import Path

from ..store import Store

SESSION_HOURS = 12
N, R, P = 2 ** 15, 8, 1
MIN_LEN = 10


def _auth_file(store: Store) -> Path:
    return store.root / "web" / "auth.json"


def _kdf(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P, maxmem=128 * 1024 * 1024, dklen=32)


def set_password(store: Store, password: str) -> None:
    if len(password) < MIN_LEN:
        raise ValueError(f"password must have at least {MIN_LEN} characters")
    salt = secrets.token_bytes(16)
    doc = {"v": 1, "kdf": "scrypt", "n": N, "r": R, "p": P, "salt": base64.b64encode(salt).decode(),
           "hash": base64.b64encode(_kdf(password, salt)).decode()}
    f = _auth_file(store)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(".auth.json.part")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(doc))
    os.replace(tmp, f)


def configured(store: Store) -> bool:
    return _auth_file(store).is_file()


def check_password(store: Store, password: str) -> bool:
    try:
        doc = json.loads(_auth_file(store).read_text())
        salt, want = base64.b64decode(doc["salt"]), base64.b64decode(doc["hash"])
    except (OSError, ValueError, KeyError):
        return False
    return hmac.compare_digest(_kdf(password, salt), want)


def new_session(conn: sqlite3.Connection) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO web_sessions(token_sha256, expires_at) VALUES (?, "
                 "strftime('%Y-%m-%dT%H:%M:%fZ','now', ?))",
                 (hashlib.sha256(token.encode()).hexdigest(), f"+{SESSION_HOURS} hours"))
    conn.execute("DELETE FROM web_sessions WHERE expires_at < strftime('%Y-%m-%dT%H:%M:%fZ','now')")
    return token


def valid_session(conn: sqlite3.Connection, token: str | None) -> bool:
    if not token:
        return False
    return conn.execute("SELECT 1 FROM web_sessions WHERE token_sha256=? AND revoked_at IS NULL AND "
                        "expires_at > strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                        (hashlib.sha256(token.encode()).hexdigest(),)).fetchone() is not None


def end_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("UPDATE web_sessions SET revoked_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE token_sha256=?",
                     (hashlib.sha256(token.encode()).hexdigest(),))
