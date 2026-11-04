#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Render the camera app's screens from a harness draw log (MFILM_DRAWLOG):
render_screens.py LOG OUT_DIR -> OUT_DIR/<snap>.png, 360x240 x2. Text uses
a monospace 8x16 cell like CHDK's font (not CHDK's glyphs); the live view
behind the bitmap is drawn as a dark grey checker."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PAL = {0: None, 1: (0, 0, 0), 2: (255, 255, 255), 3: (220, 40, 40), 4: (140, 20, 20), 5: (255, 120, 120),
       6: (40, 180, 60), 7: (20, 110, 30), 8: (130, 230, 130), 9: (40, 80, 220), 10: (30, 50, 150),
       11: (110, 170, 255), 12: (128, 128, 128), 13: (70, 70, 70), 14: (190, 190, 190), 15: (240, 210, 40),
       16: (170, 140, 20), 17: (255, 240, 150), 18: (60, 60, 60), 19: (220, 60, 200)}


def colour(c):
    return PAL.get(int(c) - 256 if int(c) >= 256 else 1, (255, 0, 255))


def blank():
    im = Image.new("RGB", (360, 240), (45, 45, 50))
    d = ImageDraw.Draw(im)
    for y in range(0, 240, 20):
        for x in range(0, 360, 20):
            if (x + y) // 20 % 2:
                d.rectangle([x, y, x + 19, y + 19], fill=(55, 55, 60))
    return im


def main():
    log, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
    im = blank()
    d = ImageDraw.Draw(im)
    for line in log.read_text(errors="replace").splitlines():
        if line == "C":
            im = blank(); d = ImageDraw.Draw(im)
        elif line.startswith("R "):
            x1, y1, x2, y2, c = map(int, line.split()[1:6])
            if colour(c):
                d.rectangle([x1, y1, x2, y2], fill=colour(c))
        elif line.startswith("S "):
            parts = line.split(" ", 6)
            x, y, sc, fg, bg = map(int, parts[1:6])
            txt = parts[6] if len(parts) > 6 else ""
            w = 8 * sc * len(txt)
            if colour(bg):
                d.rectangle([x, y, x + w - 1, y + 16 * sc - 1], fill=colour(bg))
            if sc == 1:
                for i, ch in enumerate(txt):
                    d.text((x + 8 * i, y + 1), ch, fill=colour(fg), font=font)
            else:
                big = ImageFont.truetype("DejaVuSansMono-Bold.ttf", 13 * sc) if font != ImageFont.load_default() else font
                for i, ch in enumerate(txt):
                    d.text((x + 8 * sc * i, y + 1), ch, fill=colour(fg), font=big)
        elif line.startswith("SNAP "):
            im.resize((720, 480), Image.NEAREST).save(out / f"{line[5:].strip()}.png")
    print(f"screens in {out}")


if __name__ == "__main__":
    main()
