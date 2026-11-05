#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Render the camera app's screens from a harness draw log (MFILM_DRAWLOG).

    render_screens.py LOG OUT_DIR [--scale 2] [--gif NAME:PREFIX ...]

Each "SNAP name" in the log becomes OUT_DIR/<name>.png (360x240 x scale).
Text uses CHDK's own 8x16 font (src/camera/test/chdk_font_8x16.txt), scaled
text like draw_string's scale argument; colours are CHDK's script colour
indexes as the SX510 HS shows them (matched to the owner's videos). The live
view behind the transparent overlay is a dim checker; a viewer frame
(SHOW) is a grey placeholder photo. --gif NAME:PREFIX also writes NAME.gif
from the snaps whose names start with PREFIX, in order (animations)."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
FONT_FILE = REPO / "src" / "camera" / "test" / "chdk_font_8x16.txt"

# CHDK colour index -> RGB as seen on the camera (IDX_COLOR_*, core/gui_draw.h)
PAL = {0: None, 1: (12, 16, 36), 2: (240, 240, 240), 3: (225, 45, 40), 4: (140, 25, 25), 5: (250, 130, 120),
       6: (50, 190, 70), 7: (20, 110, 40), 8: (140, 235, 140), 9: (40, 90, 230), 10: (0, 160, 215),
       11: (110, 190, 255), 12: (130, 130, 135), 13: (65, 65, 72), 14: (190, 190, 195), 15: (245, 215, 50),
       16: (170, 140, 25), 17: (255, 240, 160), 18: (50, 50, 60), 19: (220, 70, 210)}


def load_font() -> dict[int, list[int]]:
    glyphs = {}
    for ln in FONT_FILE.read_text().splitlines():
        if ln and not ln.startswith("#"):
            code, rows = ln.split()
            glyphs[int(code, 16)] = [int(rows[i:i + 2], 16) for i in range(0, 32, 2)]
    return glyphs


def colour(c: int):
    c = int(c)
    return PAL.get(c - 256 if c >= 256 else 1, (255, 0, 255))


def live_view() -> Image.Image:
    im = Image.new("RGB", (360, 240), (58, 62, 70))
    d = ImageDraw.Draw(im)
    for y in range(0, 240, 20):
        for x in range(0, 360, 20):
            if (x + y) // 20 % 2:
                d.rectangle([x, y, x + 19, y + 19], fill=(70, 74, 82))
    return im


def photo() -> Image.Image:
    im = Image.new("RGB", (360, 240))
    px = im.load()
    for y in range(240):
        for x in range(360):
            px[x, y] = (110 + x // 6, 90 + y // 5, 80 + (x + y) // 10)
    return im


class Screen:
    def __init__(self, font):
        self.font = font
        self.back = live_view()
        self.ov = Image.new("RGBA", (360, 240), (0, 0, 0, 0))

    def text(self, x, y, sc, fg, bg, s):
        fgc, bgc = colour(fg), colour(bg)
        px = self.ov.load()
        for i, ch in enumerate(s):
            rows = self.font.get(ord(ch), self.font[0x3f])
            for r, bits in enumerate(rows):
                for c in range(8):
                    col = fgc if bits & (0x80 >> c) else bgc
                    for dy in range(sc):
                        for dx in range(sc):
                            X, Y = x + (i * 8 + c) * sc + dx, y + r * sc + dy
                            if 0 <= X < 360 and 0 <= Y < 240:
                                px[X, Y] = (*col, 255) if col else (0, 0, 0, 0)

    def rect(self, x1, y1, x2, y2, c):
        col = colour(c)
        ImageDraw.Draw(self.ov).rectangle([x1, y1, x2, y2], fill=(*col, 255) if col else (0, 0, 0, 0))

    def image(self, scale) -> Image.Image:
        im = self.back.copy()
        im.paste(self.ov, (0, 0), self.ov)
        return im.resize((360 * scale, 240 * scale), Image.Resampling.NEAREST)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("out")
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--gif", action="append", default=[], help="NAME:PREFIX")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    scr = Screen(load_font())
    frames: dict[str, Image.Image] = {}
    for ln in Path(a.log).read_text(errors="replace").splitlines():
        if ln.startswith("S "):
            _, x, y, sc, fg, bg, s = ln.split(" ", 6)
            scr.text(int(x), int(y), int(sc), int(fg), int(bg), s)
        elif ln.startswith("R "):
            _, x1, y1, x2, y2, c = ln.split()
            scr.rect(int(x1), int(y1), int(x2), int(y2), int(c))
        elif ln == "C":
            scr.ov = Image.new("RGBA", (360, 240), (0, 0, 0, 0))
        elif ln.startswith("SHOW "):
            scr.back = photo()
        elif ln.startswith("MODE "):
            scr.back = live_view() if ln == "MODE rec" else photo()
        elif ln.startswith("SNAP "):
            name = ln[5:].strip()
            im = scr.image(a.scale)
            frames[name] = im
            im.save(out / f"{name}.png")
    for spec in a.gif:
        name, prefix = spec.split(":", 1)
        seq = [frames[k] for k in sorted(frames) if k.startswith(prefix)]
        if seq:
            seq[0].save(out / f"{name}.gif", save_all=True, append_images=seq[1:], duration=200, loop=0)
    print(f"{len(frames)} screen(s) in {out}")


if __name__ == "__main__":
    main()
