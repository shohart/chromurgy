# SPDX-License-Identifier: GPL-2.0-only
"""Lay out the M-Film camera files for an SD card that already has CHDK
(docs/03): the app script, its library, the film list and the profile
bundle hash the receiver will develop with.

    mfilmctl camera-card OUT_DIR [--utc-offset +02:00] [--bench]

Copy OUT_DIR's contents to the card root (merging into CHDK/). The card
config never overwrites the camera's own state (device.cfg, active.cfg,
ROLLS/), so updating the app on a card in use is safe.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import core

REPO = core.REPO
APP = REPO / "src" / "camera" / "app"


def utc_offset_now() -> str:
    z = time.strftime("%z")                      # e.g. +0200
    return f"{z[:3]}:{z[3:]}" if len(z) == 5 else "+00:00"


def card_config(bundle: core.Bundle, utc_offset: str) -> str:
    films = json.loads((REPO / "profiles" / "films.json").read_text())
    if films.get("profile_bundle_hash", "").lower() != bundle.sha256:
        raise ValueError("profiles/films.json does not describe the bundle in use")
    lines = ["# M-Film camera config, written by mfilmctl camera-card", f"profile_bundle_hash={bundle.sha256}",
             f"utc_offset={utc_offset}"]
    keys = set(bundle.keys)
    for f in films["films"]:
        if f["key"] in keys:
            name = f["name"].replace("|", "/").replace("\n", " ")
            short = (f.get("short") or f["key"]).replace("|", "/")
            lines.append(f"film={f['key']}|{name}|{short}")
    return "\n".join(lines) + "\n"


def test_frame() -> bytes:
    """Screen test for the camera viewer: colour bars, a grey ramp and a circle
    that must look round on the 4:3 screen (the buffer's pixels are not square)."""
    import numpy as np
    from PIL import Image, ImageDraw

    from .camera_view import header, pack_uyvyyy
    w, h = 1600, 1200                                   # square pixels, 4:3
    im = Image.new("RGB", (w, h), (20, 20, 20))
    d = ImageDraw.Draw(im)
    bars = [(235, 235, 235), (235, 235, 16), (16, 235, 235), (16, 235, 16), (235, 16, 235), (235, 16, 16),
            (16, 16, 235), (16, 16, 16)]
    for i, c in enumerate(bars):
        d.rectangle([i * w // 8, 0, (i + 1) * w // 8 - 1, h // 2], fill=c)
    for x in range(w):
        v = round(255 * x / (w - 1))
        d.line([(x, h // 2 + 40), (x, h // 2 + 200)], fill=(v, v, v))
    d.ellipse([w // 2 - 300, h // 2 - 300, w // 2 + 300, h // 2 + 300], outline=(255, 140, 0), width=12)
    d.text((40, h - 200), "M-FILM SCREEN TEST", fill=(255, 255, 255), font_size=96)
    from .camera_view import fit_to_screen
    return header() + pack_uyvyyy(fit_to_screen(np.asarray(im)))


def write_card(out: Path, *, utc_offset: str | None = None, bench: bool = False,
               bundle: core.Bundle | None = None, chdk: bool = False) -> list[Path]:
    bundle = bundle or core.Bundle()
    out = Path(out)
    files = {
        out / "CHDK" / "MFVIEW" / "TEST.MFV": test_frame(),
        out / "CHDK" / "SCRIPTS" / "MFILM.LUA": (APP / "MFILM.LUA").read_bytes(),
        out / "CHDK" / "LUALIB" / "mfroll.lua": (APP / "mfroll.lua").read_bytes(),
        out / "CHDK" / "MFILM" / "CONFIG" / "MFILM.CFG": card_config(bundle, utc_offset or utc_offset_now()).encode(),
    }
    written = []
    for p, data in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        written.append(p)
    if chdk:                                            # the M-Film CHDK build (tools/build_chdk16.sh)
        built = REPO / "build" / "chdk16-card"
        if not (built / "DISKBOOT.BIN").is_file():
            raise FileNotFoundError(f"{built}: run tools/build_chdk16.sh first")
        for src in sorted(p for p in built.rglob("*") if p.is_file()):
            dst = out / src.relative_to(built)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            written.append(dst)
    if bench:
        built = REPO / "build" / "chdk-card" / "CHDK"
        for rel in ("MODULES/mfbench.flt", "DATA/MFBENCH.BIN", "SCRIPTS/MFPROBE.LUA"):
            src = built / rel
            if not src.is_file():
                raise FileNotFoundError(f"{src}: run tools/build_chdk.sh first")
            dst = out / "CHDK" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            written.append(dst)
    return written
