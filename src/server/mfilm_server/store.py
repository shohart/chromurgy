# SPDX-License-Identifier: GPL-2.0-only
"""Server storage layout (docs/04) with path confinement and atomic promotion."""
from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class UnsafePath(ValueError):
    pass


def safe_id(value: str, what: str = "id") -> str:
    if not isinstance(value, str) or not SAFE_ID.match(value) or ".." in value:
        raise UnsafePath(f"unsafe {what}: {value!r}")
    return value


def confine(base: Path, relative: str) -> Path:
    """Resolve an untrusted relative path strictly inside base (no symlink escape)."""
    if not relative or relative.startswith(("/", "\\")) or "\0" in relative:
        raise UnsafePath(f"unsafe path: {relative!r}")
    base_r = base.resolve()
    target = (base_r / relative.replace("\\", "/")).resolve()
    if target != base_r and base_r not in target.parents:
        raise UnsafePath(f"path escapes {base}: {relative!r}")
    return target


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Store:
    SUBDIRS = ("incoming", "originals", "offline-renders", "renders", "manifests", "bundles", "db", "logs")

    def __init__(self, root: Path):
        self.root = Path(root)

    def init(self) -> None:
        for d in self.SUBDIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        return self.root / "db" / "mfilm.sqlite3"

    def original_path(self, device_id: str, roll_id: str, frame_id: str) -> Path:
        return (self.root / "originals" / safe_id(device_id, "device_id") / safe_id(roll_id, "roll_id")
                / f"{safe_id(frame_id, 'frame_id')}.dng")

    def manifest_path(self, device_id: str, roll_id: str) -> Path:
        return self.root / "manifests" / safe_id(device_id, "device_id") / f"{safe_id(roll_id, 'roll_id')}.json"

    def stage_copy(self, src: Path) -> Path:
        """Copy src into incoming/ and fsync; caller verifies then promotes."""
        part = self.root / "incoming" / f"{uuid.uuid4().hex}.part"
        with open(src, "rb") as fi, open(part, "xb") as fo:
            shutil.copyfileobj(fi, fo, 1 << 20)
            fo.flush()
            os.fsync(fo.fileno())
        return part

    def stage_bytes(self, data: bytes) -> Path:
        part = self.root / "incoming" / f"{uuid.uuid4().hex}.part"
        with open(part, "xb") as fo:
            fo.write(data)
            fo.flush()
            os.fsync(fo.fileno())
        return part

    @staticmethod
    def promote(part: Path, dest: Path, *, readonly: bool = True) -> None:
        """Atomic rename into the archive; never overwrites an existing file."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        if readonly:
            os.chmod(part, 0o444)
        os.link(part, dest)          # fails with FileExistsError instead of replacing
        os.unlink(part)
        fsync_dir(dest.parent)
