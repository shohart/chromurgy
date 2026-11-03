# SPDX-License-Identifier: GPL-2.0-only
"""Archive of profile bundles, addressed by content hash (docs/05, docs/12).

A roll is frozen to the bundle it was shot with. The server keeps every
bundle it has ever been given under <data>/bundles/<sha256>.bin (read-only,
with the films.json that described it) and develops each roll with exactly
its own one. A roll whose bundle is not archived is parked, never developed
with a different bundle.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from . import core
from .ids import sha256_file
from .store import Store


class BundleUnavailable(core.CoreError):
    def __init__(self, sha: str):
        super().__init__("PROFILE_BUNDLE_UNAVAILABLE",
                         f"{sha} is not archived; add it with: mfilmctl bundle-add <mfilm-films.bin>")
        self.sha = sha


class Bundles:
    def __init__(self, store: Store):
        self.dir = store.root / "bundles"
        self.store = store
        self._cache: dict[str, core.Bundle] = {}

    def path(self, sha: str) -> Path:
        sha = sha.lower()
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise core.CoreError("INVALID_PROFILE_BUNDLE", f"bad bundle hash {sha!r}")
        return self.dir / f"{sha}.bin"

    def add(self, src: Path, films_json: Path | None = None) -> tuple[str, bool]:
        """Validate and archive a bundle file. Returns (sha256, newly_added)."""
        b = core.Bundle(src)                      # parses: refuses anything the core cannot read
        if sha256_file(src)[0] != b.sha256:
            raise core.CoreError("INVALID_PROFILE_BUNDLE", "bundle hash is not the file hash")
        dest = self.path(b.sha256)
        self.dir.mkdir(parents=True, exist_ok=True)
        meta = films_json if films_json is not None else src.with_name("films.json")
        new = False
        if not dest.exists():
            part = self.store.stage_copy(src)
            if sha256_file(part)[0] != b.sha256:
                part.unlink()
                raise core.CoreError("INVALID_PROFILE_BUNDLE", "copy verification failed")
            Store.promote(part, dest)
            new = True
        side = dest.with_suffix(".films.json")
        if not side.exists() and meta.is_file():
            try:
                doc = json.loads(meta.read_text())
                if doc.get("profile_bundle_hash") == b.sha256:   # only the description of THIS bundle
                    tmp = side.with_name(f".{side.name}.part")
                    shutil.copyfile(meta, tmp)
                    os.chmod(tmp, 0o444)
                    os.replace(tmp, side)
            except (OSError, ValueError):
                pass
        return b.sha256, new

    def ensure_default(self) -> str | None:
        """Archive the bundle this checkout ships (profiles/mfilm-films.bin), if present."""
        p = core.bundle_path()
        if not p.is_file():
            return None
        return self.add(p)[0]

    def get(self, sha: str) -> core.Bundle:
        sha = sha.lower()
        if sha in self._cache:
            return self._cache[sha]
        p = self.path(sha)
        if not p.is_file():
            raise BundleUnavailable(sha)
        b = core.Bundle(p)
        if b.sha256 != sha:
            raise core.CoreError("INVALID_PROFILE_BUNDLE", f"archived {p.name} hashes to {b.sha256}")
        self._cache[sha] = b
        return b

    def has(self, sha: str) -> bool:
        try:
            return self.path(sha).is_file()
        except core.CoreError:
            return False

    def list(self) -> list[dict]:
        out = []
        for p in sorted(self.dir.glob("*.bin")) if self.dir.is_dir() else []:
            try:
                b = self.get(p.stem)
                out.append({"profile_bundle_hash": b.sha256, "films": len(b.keys), "keys": b.keys,
                            "current": p.stem == _current_sha()})
            except core.CoreError as e:
                out.append({"profile_bundle_hash": p.stem, "error": e.code})
        return out

    def film_short(self, sha: str, key: str) -> str | None:
        """Display name ('Portra400') from the films.json archived with the bundle."""
        for meta in (self.dir / f"{sha}.films.json", core.bundle_path().with_name("films.json")):
            try:
                doc = json.loads(meta.read_text())
                if meta.parent != self.dir and doc.get("profile_bundle_hash") != sha:
                    continue
                for f in doc["films"]:
                    if f["key"] == key:
                        return f["short"]
            except (OSError, ValueError, KeyError):
                continue
        return None


def _current_sha() -> str | None:
    p = core.bundle_path()
    return sha256_file(p)[0] if p.is_file() else None
