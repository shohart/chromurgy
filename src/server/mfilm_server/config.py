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
        user_cfg = Path.home() / ".config" / "mfilm" / "config.toml"
        if user_cfg.is_file():
            path = user_cfg
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


def default_config_path() -> Path:
    env = os.environ.get("CHROMURGY_CONFIG") or os.environ.get("MFILM_CONFIG")
    if env:
        return Path(os.path.expanduser(env)).resolve()
    p_mfilm = Path("~/.config/mfilm/config.toml").expanduser()
    p_chromurgy = Path("~/.config/chromurgy/config.toml").expanduser()
    if p_chromurgy.is_file():
        return p_chromurgy.resolve()
    if p_mfilm.is_file():
        return p_mfilm.resolve()
    return p_chromurgy.resolve()


def save(path: str | os.PathLike, cfg: Config) -> None:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if p.is_file():
        try:
            existing = tomllib.loads(p.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    existing["data_dir"] = str(cfg.data_dir)
    pp = existing.setdefault("photoprism", {})
    if cfg.photoprism.url:
        pp["url"] = cfg.photoprism.url
    elif "url" in pp:
        del pp["url"]
    if cfg.photoprism.token_file:
        pp["token_file"] = str(cfg.photoprism.token_file)
    if cfg.photoprism.originals_dir:
        pp["originals_dir"] = str(cfg.photoprism.originals_dir)
    if cfg.photoprism.export_dir:
        pp["export_dir"] = str(cfg.photoprism.export_dir)
    if cfg.photoprism.web_folder:
        pp["web_folder"] = cfg.photoprism.web_folder
    if cfg.photoprism.subdir:
        pp["subdir"] = cfg.photoprism.subdir
    if cfg.photoprism.index_template:
        pp["index_template"] = list(cfg.photoprism.index_template)
    if cfg.photoprism.index_command:
        pp["index_command"] = list(cfg.photoprism.index_command)

    worker = existing.setdefault("worker", {})
    worker["jobs"] = cfg.jobs

    lines = [
        "# Chromurgy configuration (generated)",
        f'data_dir = "{existing.get("data_dir", "")}"',
        "",
        "[photoprism]",
    ]
    for k, v in pp.items():
        if isinstance(v, str):
            lines.append(f'{k} = "{v}"')
        elif isinstance(v, list):
            items_str = ", ".join(f'"{x}"' for x in v)
            lines.append(f'{k} = [{items_str}]')
        elif isinstance(v, bool):
            lines.append(f'{k} = {"true" if v else "false"}')
        elif isinstance(v, int):
            lines.append(f"{k} = {v}")

    lines.append("")
    lines.append("[worker]")
    for k, v in worker.items():
        if isinstance(v, int):
            lines.append(f"{k} = {v}")
        elif isinstance(v, str):
            lines.append(f'{k} = "{v}"')

    cam = existing.get("camera", {})
    if cam:
        lines.append("")
        lines.append("[camera]")
        for k, v in cam.items():
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')

    lines.append("")
    content = "\n".join(lines)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, p)


def test_photoprism_connection(url: str, token: str | None = None, originals_dir: str | Path | None = None) -> dict:
    import json
    import urllib.error
    import urllib.request

    res = {"ok": False, "api_ok": False, "version": None, "originals_dir_ok": None, "error": None}
    url = (url or "").strip().rstrip("/")
    if not url:
        res["error"] = "PhotoPrism URL is required"
        return res
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url

    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        req = urllib.request.Request(f"{url}/api/v1/config", headers=headers)
        with urllib.request.urlopen(req, timeout=8.0) as r:
            if r.status == 200:
                data = json.loads(r.read())
                res["api_ok"] = True
                res["version"] = data.get("version", "connected")
            else:
                res["error"] = f"PhotoPrism returned HTTP {r.status}"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            res["error"] = "PhotoPrism rejected the token (401 Unauthorized)"
        else:
            res["error"] = f"PhotoPrism HTTP Error {e.code}"
    except Exception as e:
        res["error"] = f"Connection failed to {url}: {e}"

    if originals_dir:
        p = Path(os.path.expanduser(str(originals_dir))).resolve()
        if p.is_dir() and os.access(p, os.R_OK):
            res["originals_dir_ok"] = True
        else:
            res["originals_dir_ok"] = False
            if not res["error"]:
                res["error"] = f"Originals directory does not exist or is not readable: {originals_dir}"

    res["ok"] = bool(res["api_ok"] and (res["originals_dir_ok"] is None or res["originals_dir_ok"]))
    return res
