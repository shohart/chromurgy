#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fit the lens geometry the camera applies to its own JPEGs, from CHDK DNG +
camera JPEG pairs, and write the lens table used by mfilm_server.lens.

    fit_lens.py --out profiles/lenses/canon-sx510hs.json DIR [DIR ...]

Pairs are matched by capture time (CHDK raw numbering can lag the JPEG
counter), never by file number. For each pair: SIFT matches between the
JPEG luma and the raw green plane, then a robust fit of

    raw = c + (j - J0) * s * (1 + k1 r^2 + k2 r^4 + k3 r^6),   r = |j - J0| / |J0|

with j a JPEG pixel coordinate (pixel centres at i + 0.5), J0 the JPEG
centre and c, s, k1..k3 free. Pairs of the same focal length are pooled.
Frames shot with digital zoom are skipped (the DNG keeps the optical field).
The images themselves stay out of Git; only the fitted numbers are written.

Needs: rawpy, pillow, numpy, scipy, opencv-python-headless.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import rawpy
from PIL import Image
from scipy.optimize import least_squares

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "server"))
from mfilm_server.lens import dng_info, radial_map

EXIF, FOCAL, DZOOM, DTORIG = 0x8769, 37386, 41988, 36867


def jpeg_info(path: Path) -> dict:
    with Image.open(path) as im:
        e = im.getexif()
        sub = e.get_ifd(EXIF)
        return {"size": im.size, "focal_mm": float(sub.get(FOCAL, 0) or 0),
                "digital_zoom": float(sub.get(DZOOM, 1) or 1), "time": sub.get(DTORIG) or e.get(306)}


def stamp(s: str | None) -> float | None:
    try:
        return dt.datetime.strptime(s.strip(), "%Y:%m:%d %H:%M:%S").timestamp() if s else None
    except ValueError:
        return None


def pairs(dirs: list[Path]) -> list[tuple[Path, Path]]:
    dngs, jpgs = [], []
    for d in dirs:
        for p in sorted(d.iterdir()):
            if p.suffix.upper() == ".DNG":
                t = stamp(dng_info(p).get("time"))
                if t is not None:
                    dngs.append((t, p))
            elif p.suffix.upper() in (".JPG", ".JPEG"):
                t = stamp(jpeg_info(p)["time"])
                if t is not None:
                    jpgs.append((t, p))
    out = []
    for t, d in dngs:                     # nearest JPEG within 2 s, each JPEG used once
        cand = sorted((abs(t - tj), j) for tj, j in jpgs if abs(t - tj) <= 2)
        if cand:
            out.append((d, cand[0][1]))
            jpgs = [(tj, j) for tj, j in jpgs if j != cand[0][1]]
    return out


def raw_green(path: Path) -> np.ndarray:
    with rawpy.imread(str(path)) as r:
        v = r.raw_image_visible.astype(np.float32) - float(np.mean(r.black_level_per_channel))
        pat = r.raw_pattern
    gi = [(y, x) for y in (0, 1) for x in (0, 1) if pat[y, x] in (1, 3)]
    g = (v[gi[0][0]::2, gi[0][1]::2] + v[gi[1][0]::2, gi[1][1]::2]) / 2
    g = np.clip(g / max(np.percentile(g, 99.5), 1), 0, 1) ** (1 / 2.2)
    return (g * 255).astype(np.uint8)


def matches(dng: Path, jpg: Path, size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    w, h = size
    with Image.open(jpg) as im:
        a = np.asarray(im.convert("L").resize((w // 2, h // 2), Image.LANCZOS))
    b = raw_green(dng)
    sift = cv2.SIFT_create(8000)
    ka, da = sift.detectAndCompute(a, None)
    kb, db = sift.detectAndCompute(b, None)
    if da is None or db is None:
        return np.zeros((0, 2)), np.zeros((0, 2))
    good = [m for m, n in cv2.BFMatcher().knnMatch(da, db, k=2) if m.distance < 0.75 * n.distance]
    # half-res pixel i (cv2: centre at i) covers full-res 2i..2i+2: centre 2i + 1 in pixel-centre-at-k+0.5 coords
    pa = np.float64([ka[m.queryIdx].pt for m in good]) * 2 + 1
    pb = np.float64([kb[m.trainIdx].pt for m in good]) * 2 + 1
    return pa, pb


def fit(pa: np.ndarray, pb: np.ndarray, size: tuple[int, int]) -> tuple[list[float], float, int]:
    def resid(p, a, b):
        return (radial_map(a, size, *p) - b).ravel()
    keep = np.ones(len(pa), bool)
    if len(pa) >= 8:
        _, inl = cv2.findHomography(pa, pb, cv2.RANSAC, 40.0)
        keep = inl.ravel() > 0
    p = np.array([size[0] / 2 + 36, size[1] / 2 + 22, 1.0, 0.0, 0.0, 0.0])
    for it in range(4):
        p = least_squares(resid, p, args=(pa[keep], pb[keep]), loss="soft_l1", f_scale=2.0).x
        e = np.linalg.norm(radial_map(pa, size, *p) - pb, axis=1)
        keep = e < (max(3.0, 2 * np.percentile(e[keep], 90)) if it == 0 else 2.5)
    e = np.linalg.norm(radial_map(pa[keep], size, *p) - pb[keep], axis=1)
    return [float(x) for x in p], float(np.sqrt(np.mean(e ** 2))), int(keep.sum())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dirs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-matches", type=int, default=100)
    a = ap.parse_args()
    pooled: dict[float, list] = defaultdict(lambda: [[], [], []])
    model = size = None
    for dng, jpg in pairs(a.dirs):
        di, ji = dng_info(dng), jpeg_info(jpg)
        model = model or di.get("model")
        if ji["digital_zoom"] != 1:
            print(f"{dng.name}: skipped, digital zoom x{ji['digital_zoom']:.2f}")
            continue
        size = size or ji["size"]
        pa, pb = matches(dng, jpg, ji["size"])
        if len(pa) < a.min_matches:
            print(f"{dng.name}: skipped, {len(pa)} matches (flat subject?)")
            continue
        p, rms, n = fit(pa, pb, ji["size"])
        print(f"{dng.name}+{jpg.name}: {di['focal_mm']:7.3f} mm  {n:5d} pts  rms {rms:.2f} px  k1 {p[3]:+.4f}")
        fl = round(di["focal_mm"], 3)
        pooled[fl][0].append(pa)
        pooled[fl][1].append(pb)
        pooled[fl][2].append(dng.name)
    if not pooled:
        print("no usable pairs", file=sys.stderr)
        return 1
    entries = []
    for fl in sorted(pooled):
        pa, pb = np.concatenate(pooled[fl][0]), np.concatenate(pooled[fl][1])
        p, rms, n = fit(pa, pb, size)
        corner = radial_map(np.float64([[0.5, 0.5]]), size, *p)[0]
        print(f"{fl:7.3f} mm pooled {len(pooled[fl][2])} frame(s): rms {rms:.2f} px, centre ({p[0]:.1f}, {p[1]:.1f}),"
              f" s {p[2]:.4f}, k {p[3]:+.4f} {p[4]:+.4f} {p[5]:+.4f}, jpeg corner <- raw ({corner[0]:.0f}, {corner[1]:.0f})")
        entries.append({"focal_mm": fl, "cx": round(p[0], 3), "cy": round(p[1], 3), "s": round(p[2], 6),
                        "k1": round(p[3], 6), "k2": round(p[4], 6), "k3": round(p[5], 6),
                        "rms_px": round(rms, 3), "points": n, "frames": len(pooled[fl][2])})
    table = {"schema_version": 1, "camera_model": model, "output_width": size[0], "output_height": size[1],
             "model": "raw = c + (j - J0) * s * (1 + k1 r^2 + k2 r^4 + k3 r^6), r = |j - J0| / |J0|;"
                      " pixel centres at i + 0.5; raw = LibRaw visible area",
             "source": "fitted by tools/fit_lens.py from DNG + camera JPEG pairs (owner calibration shots,"
                       " not in Git)",
             "focal_lengths": entries}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(table, indent=1) + "\n")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
