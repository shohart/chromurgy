# SPDX-License-Identifier: GPL-2.0-only
"""Service configuration (config.toml; see config.example.toml at the repo root)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PhotoPrism:
    export_dir: Path | None = None          # a folder inside PhotoPrism's originals (or import) path
    subdir: str = "M-Film"
    index_command: list[str] = field(default_factory=list)   # e.g. ssh host docker exec photoprism photoprism index M-Film


@dataclass
class Config:
    data_dir: Path = Path("/var/lib/mfilm")
    photoprism: PhotoPrism = field(default_factory=PhotoPrism)
    jobs: int = 1                           # [worker] jobs: frames developed at once (~0.9 GB each)
    chdkptp: str | None = None              # [camera] chdkptp: command template, {mirror} = local card mirror
    camera_host: str | None = None          # [camera] host: the camera's IP for Wi-Fi (PTP/IP); unset = USB


def load(path: str | os.PathLike | None) -> Config:
    path = path or os.environ.get("MFILM_CONFIG")
    if not path:
        return Config()
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    cfg = Config()
    if "data_dir" in raw:
        cfg.data_dir = Path(raw["data_dir"])
    pp = raw.get("photoprism", {})
    if pp.get("export_dir"):
        cfg.photoprism.export_dir = Path(pp["export_dir"])
    cfg.photoprism.subdir = pp.get("subdir", cfg.photoprism.subdir)
    cmd = pp.get("index_command", [])
    if isinstance(cmd, str) or not all(isinstance(c, str) for c in cmd):
        raise ValueError("photoprism.index_command must be a list of strings (no shell)")
    cfg.photoprism.index_command = list(cmd)
    jobs = raw.get("worker", {}).get("jobs", 1)
    if not isinstance(jobs, int) or jobs < 1:
        raise ValueError("worker.jobs must be a positive integer")
    cfg.jobs = jobs
    cam = raw.get("camera", {})
    cfg.chdkptp = cam.get("chdkptp") or None
    cfg.camera_host = cam.get("host") or None
    return cfg
