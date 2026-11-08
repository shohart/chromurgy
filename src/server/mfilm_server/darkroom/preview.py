# SPDX-License-Identifier: GPL-2.0-only
"""Reduced-resolution previews through the production pipeline (docs/web/31).

Per source the expensive part (LibRaw decode, lens correction, upright) runs once
and is cached as a <=2048 px float16 array; every preview is then the shared C
film core on a small buffer. The film core's spatial kernels scale with image
width, so a preview keeps the look of the full render (grain amplitude follows
the core's own downscale rule). The demosaic for previews is LibRaw's fast
linear one: after a 2x+ reduction its difference to AHD is below display
visibility; final renders always use the recipe's demosaic.

This module runs inside a dedicated worker process (see PreviewLane): a decoder
crash or a 36-frame batch must never stall or kill the API."""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import multiprocessing as mp
import os
import threading
import time
from pathlib import Path

import numpy as np

from .. import core, develop
from ..ids import canonical_json
from . import creative, cropping, engine, tone, wb

NORM_EDGE = 2048
PREVIEW_DEMOSAIC = "fast"
PREVIEW_QUALITY = 82


def wb_mode(v2: dict) -> str:
    return (v2.get("extensions") or {}).get("white_balance", "daylight")


def preview_key(*, sha: str, kind: str, recipe_hash: str, max_edge: int, bundle_hash: str, wb: str = "daylight",
                crop: dict | None = None, rotate: float | None = None) -> str:
    """Cache identity: source + recipe + engine versions + size (never a file name)."""
    doc = {
        "v": "mfilm-preview-v1", "kind": kind, "source": sha, "recipe": recipe_hash, "edge": max_edge,
        "core": core.core_version(), "bundle": bundle_hash, "norm": develop.INPUT_NORMALIZATION,
        "demosaic": PREVIEW_DEMOSAIC, "wb": wb, "crop": crop}
    if rotate:
        doc["rotate"] = rotate
    return hashlib.sha256(canonical_json(doc)).hexdigest()


def _shrink(img: np.ndarray, edge: int) -> np.ndarray:
    h, w, _ = img.shape
    if max(h, w) <= edge:
        return img
    s = edge / max(h, w)
    return develop.fit_output(img, max(1, round(w * s)), max(1, round(h * s)))


def normalized_small(root: Path, src_path: Path, sha: str, wb: str) -> np.ndarray:
    d = root / "web-previews" / "norm"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sha}-{develop.INPUT_NORMALIZATION}-{wb}-{PREVIEW_DEMOSAIC}-{NORM_EDGE}.npy"
    if f.is_file():
        return np.load(f).astype(np.float32)
    lin, flip = develop.decode_raw(src_path, wb, PREVIEW_DEMOSAIC)
    lin, _info = develop.normalize_geometry(src_path, lin)
    lin = develop.upright(lin, flip)
    small = _shrink(lin, NORM_EDGE)
    tmp = f.with_name(f".{f.name}.{os.getpid()}.part")
    with open(tmp, "wb") as fh:
        np.save(fh, small.astype(np.float16))
    os.replace(tmp, f)
    return small


def _srgb_oetf(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def render(job: dict) -> dict:
    """Never raises (exceptions with custom constructors do not survive the process boundary)."""
    try:
        return _render(job)
    except cropping.CropError as e:
        return {"failed": True, "error_code": "INVALID_CROP", "detail": str(e)}
    except (develop.DevelopError, core.CoreError) as e:
        return {"failed": True, "error_code": e.code, "detail": e.detail[:300]}
    except (OSError, ValueError, MemoryError) as e:
        return {"failed": True, "error_code": "RENDER_FAILED", "detail": f"{type(e).__name__}: {e}"[:300]}


_CREATIVE_CACHE: dict[str, np.ndarray] = {}
_FILM_CACHE: dict[str, tuple[np.ndarray, float | None]] = {}
_CACHE_MAX = 4


def _cache_put(cache: dict, key: str, val):
    if key in cache:
        cache.pop(key)
    elif len(cache) >= _CACHE_MAX:
        cache.pop(next(iter(cache)))
    cache[key] = val
    return val


def _render(job: dict) -> dict:
    """Runs in the preview process. job: root, src_path, sha, kind ('treated'|'before'), v2, v1, max_edge, key, captured_at."""
    t0 = time.monotonic()
    root = Path(job["root"])
    out = root / "web-previews" / "img" / f"{job['key']}.jpg"
    meta_file = out.with_suffix(".json")
    if out.is_file() and meta_file.is_file():
        return {"cached": True, **json.loads(meta_file.read_text())}
    out.parent.mkdir(parents=True, exist_ok=True)
    if job["kind"] == "before":
        lin = normalized_small(root, Path(job["src_path"]), job["sha"], job["wb"])
        lin = cropping.apply_rotate(lin, job.get("rotate"))
        lin = cropping.apply_crop(lin, job.get("crop"))          # same fractions as the full render
        lin = _shrink(lin, job["max_edge"])
        img = _srgb_oetf(lin)
        info = {"scanner_ev": None}
    else:
        v1 = job["v1"]
        ckey = canonical_json({"sha": job["sha"], "wb": job["wb"], "rotate": job.get("rotate"), "crop": job.get("crop"),
                               "edge": job["max_edge"], "wb_profile": v1.get("wb_profile"), "creative": v1.get("creative")}).decode()
        lin = _CREATIVE_CACHE.get(ckey)
        if lin is None:
            lin = normalized_small(root, Path(job["src_path"]), job["sha"], job["wb"])
            lin = cropping.apply_rotate(lin, job.get("rotate"))
            lin = cropping.apply_crop(lin, job.get("crop"))
            lin = _shrink(lin, job["max_edge"])
            if v1.get("wb_profile"):
                lin = wb.apply(lin, v1["wb_profile"])
            if v1.get("creative"):
                lin = creative.apply_creative(lin, v1["creative"])
            _cache_put(_CREATIVE_CACHE, ckey, lin)
        bundle = engine.current_bundle()
        seed = develop.recipe_seed(v1, *job["seed_ids"])
        t = v1.get("tone") or {}
        ev = float(v1.get("exposure_compensation_ev", 0.0))
        key = v1["film_profile_id"]
        s = float(t.get("develop_strength", 1.0))
        if key == "none":
            base_img = tone.srgb_encode(lin * (2.0 ** ev))
            neutral = None
            ev_post = 0.0
            scanner = None
        else:
            look = v1["look_controls"]
            fkey = canonical_json({"c": ckey, "film": key, "look": look, "seed": seed, "bundle": bundle.sha256}).decode()
            cached_film = _FILM_CACHE.get(fkey)
            if cached_film is None:
                cached_film = bundle.develop(key, lin, seed=seed, grain_scale=look["grain_scale"],
                                             halation_scale=look["halation_scale"], softness_scale=look["softness_scale"],
                                             exposure_ev=0.0)
                _cache_put(_FILM_CACHE, fkey, cached_film)
            base_img, scanner = cached_film
            neutral = tone.srgb_encode(lin) if s < 1.0 else None
            ev_post = ev
        img = tone.apply_post_tone(base_img, neutral, ev=ev_post, contrast=float(t.get("contrast", 0.0)),
                                   develop_strength=s, filter_name=t.get("filter", "none"),
                                   filter_strength=float(t.get("filter_strength", 1.0)), seed=seed)
        info = {"scanner_ev": None if scanner is None else round(scanner, 4)}
    meta = {"width": int(img.shape[1]), "height": int(img.shape[0]), "elapsed_s": round(time.monotonic() - t0, 3),
            "recipe_hash": job["recipe_hash"], "kind": job["kind"], "max_edge": job["max_edge"], **info}
    tmp = out.with_suffix(".json.part")
    tmp.write_text(json.dumps(meta))
    os.replace(tmp, meta_file)
    develop.write_jpeg(img, out, PREVIEW_QUALITY, f"M-Film preview {job['kind']} {job['key'][:16]} (not export quality)")
    return {"cached": False, **meta}


def warm() -> bool:
    engine.current_bundle()
    return True


class PreviewLane:
    """One or two long-lived preview processes; per `stream` the latest request wins."""

    def __init__(self, workers: int = 1):
        self.pool = cf.ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"))
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}            # key -> {future, stream, state}
        self.latest: dict[str, str] = {}           # stream -> key
        self.pool.submit(warm)                      # load the bundle before the first request

    def submit(self, job: dict, stream: str) -> str:
        key = job["key"]
        with self.lock:
            old = self.latest.get(stream)
            if old and old != key and old in self.jobs:
                self.jobs[old]["superseded"] = True
                self.jobs[old]["future"].cancel()          # only effective while still queued
            self.latest[stream] = key
            cur = self.jobs.get(key)
            if cur and not cur["future"].cancelled():
                cur["superseded"] = False
                return key
            self.jobs[key] = {"future": self.pool.submit(render, job), "superseded": False}
            for k in [k for k, v in self.jobs.items() if v["future"].done() and k != key][:-128]:
                del self.jobs[k]
        return key

    def status(self, root: Path, key: str) -> dict:
        img = root / "web-previews" / "img" / f"{key}.jpg"
        meta_file = img.with_suffix(".json")
        with self.lock:
            j = self.jobs.get(key)
        if img.is_file() and meta_file.is_file():
            return {"status": "DONE", **json.loads(meta_file.read_text())}
        if j is None:
            return {"status": "UNKNOWN"}
        f = j["future"]
        if f.cancelled():
            return {"status": "SUPERSEDED"}
        if f.done():
            try:
                res = f.result()
            except Exception as e:                   # the process itself died (OOM, decoder crash)
                return {"status": "FAILED", "error_code": "PREVIEW_PROCESS_DIED", "detail": type(e).__name__}
            if res.get("failed"):
                return {"status": "FAILED", "error_code": res["error_code"], "detail": res["detail"]}
            return {"status": "DONE", **res}
        return {"status": "SUPERSEDED" if j["superseded"] else ("RUNNING" if f.running() else "QUEUED")}

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
