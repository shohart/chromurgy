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
    # Web Darkroom (docs/web/29): API for browsing albums/folders and linking results to albums
    url: str | None = None                  # e.g. http://localhost:2342 (must be this host's PhotoPrism: no per-request URLs)
    token_file: Path | None = None          # app password / token, mode 0600; never in the config itself
    originals_dir: Path | None = None       # PhotoPrism originals as this host sees them (read-only use); default export_dir
    index_template: list[str] = field(default_factory=list)   # argv with {path} = folder relative to originals
    web_folder: str = "M-Film/Developed"    # default output folder (below export_dir); M-Film/ exists and is writable


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
    cfg.photoprism.url = pp.get("url") or None
    if pp.get("token_file"):
        cfg.photoprism.token_file = Path(os.path.expanduser(pp["token_file"]))
    if pp.get("originals_dir"):
        cfg.photoprism.originals_dir = Path(pp["originals_dir"])
    tmpl = pp.get("index_template", [])
    if isinstance(tmpl, str) or not all(isinstance(c, str) for c in tmpl):
        raise ValueError("photoprism.index_template must be a list of strings (no shell)")
    cfg.photoprism.index_template = list(tmpl)
    cfg.photoprism.web_folder = pp.get("web_folder", cfg.photoprism.web_folder)
    jobs = raw.get("worker", {}).get("jobs", 1)
    if not isinstance(jobs, int) or jobs < 1:
        raise ValueError("worker.jobs must be a positive integer")
    cfg.jobs = jobs
    cam = raw.get("camera", {})
    cfg.chdkptp = cam.get("chdkptp") or None
    cfg.camera_host = cam.get("host") or None
    return cfg
