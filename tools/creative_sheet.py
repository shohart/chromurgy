#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Comparison sheets for the creative stage (docs/web/24): per optical effect and per Camera Look, the
four variants none / 25% / 50% / 100% side by side. Input: any sRGB image (JPEG/PNG) or, without one, a
synthetic scene with a blown-out window, a lamp and a skin-tone patch.

    python tools/creative_sheet.py [--image photo.jpg] [--out sheets/] [--edge 600]

Look at them after changing src/server/mfilm_server/darkroom/creative*.py: the numeric tests prove behaviour,
only eyes judge taste. Bumps of creative.VERSION are required when the output changes."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "server"))
from mfilm_server.darkroom import creative  # noqa: E402
from mfilm_server.darkroom.creative_params import EFFECTS, LOOKS  # noqa: E402

LEVELS = (0.0, 0.25, 0.5, 1.0)


def synthetic(w: int = 600, h: int = 400) -> np.ndarray:
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.stack([0.04 + 0.02 * x / w, 0.045 + 0.02 * y / h, 0.07 + 0.03 * x / w], -1)   # dim blue-grey room
    win = (abs(x - w * 0.72) < w * 0.09) & (abs(y - h * 0.38) < h * 0.2)
    img[win] = np.array([6.0, 5.6, 4.8])                                                 # window, far above white
    lamp = (x - w * 0.18) ** 2 + (y - h * 0.3) ** 2 < (h * 0.05) ** 2
    img[lamp] = np.array([5.0, 3.6, 1.8])                                                # tungsten lamp
    skin = (abs(x - w * 0.4) < w * 0.07) & (abs(y - h * 0.7) < h * 0.12)
    img[skin] = np.array([0.35, 0.22, 0.16])                                             # skin-tone patch
    return img.astype(np.float32)


def load(path: str | None, edge: int) -> np.ndarray:
    if not path:
        return synthetic()
    im = Image.open(path).convert("RGB")
    im.thumbnail((edge, edge))
    a = np.asarray(im, np.float32) / 255
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4).astype(np.float32)     # sRGB -> linear


def to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0, 1)
    return (np.where(x <= 0.0031308, 12.92 * x, 1.055 * x ** (1 / 2.4) - 0.055) * 255 + 0.5).astype(np.uint8)


def sheet(rows: list[tuple[str, list[np.ndarray]]]) -> Image.Image:
    h, w = rows[0][1][0].shape[:2]
    out = Image.new("RGB", (w * len(LEVELS), (h + 18) * len(rows)))
    d = ImageDraw.Draw(out)
    for r, (name, imgs) in enumerate(rows):
        d.text((4, r * (h + 18) + 3), name, fill=(255, 200, 120))
        for c, im in enumerate(imgs):
            out.paste(Image.fromarray(to_srgb(im)), (c * w, r * (h + 18) + 18))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image")
    ap.add_argument("--out", default="creative-sheets")
    ap.add_argument("--edge", type=int, default=600)
    a = ap.parse_args(argv)
    x = load(a.image, a.edge)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    fx_rows = [(f"{eid}  (strength {', '.join(f'{k:.0%}' for k in LEVELS)})",
                [creative.apply_optics(x, [{"id": eid, "enabled": True, "parameters": EFFECTS[eid]}], k) for k in LEVELS])
               for eid in EFFECTS if eid != "none"]
    look_rows = [(f"{lid}  (strength {', '.join(f'{k:.0%}' for k in LEVELS)})", [creative.apply_look(x, lid, k) for k in LEVELS])
                 for lid in LOOKS if lid != "neutral"]
    paths = []
    for name, rows in (("optics", fx_rows), ("looks", look_rows)):
        p = out / f"{name}.png"
        sheet(rows).save(p)
        paths.append(p)
    print("\n".join(str(p) for p in paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
