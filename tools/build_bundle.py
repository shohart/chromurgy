#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build the film profile bundle from the M-Film film definitions.

    src/server/.venv/bin/python -I tools/build_bundle.py   # -> profiles/mfilm-films.bin, profiles/films.json

Sources (committed, copied from the pinned upstreams in LOCKFILE):
  profiles/source/{films,filmluts,lut}.py   M-Film ml-dev/films (GPL-2.0)
  profiles/luts/**.cube                     Film-Luts (MIT)

Films whose colour comes from a LUT get a 33^3 table baked exactly the way
M-Film's tools/genfilms.py bakes LOOKnn.LUT (Cineon grid -> linear -> LUT),
but stored as uint16 instead of uint8. Films without a LUT carry no table:
the core builds it from the look model (mf_film_color) at load time.

Binary layout (little-endian), see src/shared/film_core/src/mf_bundle.c:
  header  "MFB1" u32 version u32 nfilms u32 grid u32 record_size
  records nfilms x RECORD
  tables  uint16 [grid^3][3], red fastest, 0..65535 = display 0..1
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "profiles" / "source"
LUTS = ROOT / "profiles" / "luts"
sys.path.insert(0, str(SRC))

import numpy as np  # noqa: E402
import lut as lutlib  # noqa: E402
from films import FILMS, short_name  # noqa: E402

GRID = 33
VERSION = 1
HUES = ["red", "orange", "yellow", "green", "cyan", "blue", "magenta"]
KINDS = ["neg", "slide", "xpro", "bw", "cine", "print"]
HEADER = struct.Struct("<4sIIII")
# key name short brand | iso kind flags | balance slide ev sat contrast3 pivot3 black3 white3 nhues
# hues 4x(from to amount chroma) | halation hal_thr hal_tint3 grain grain_size soft mono mono_mix3 | table_off
RECORD = struct.Struct("<24s48s24s16s iii ii ff 3f3f3f3f i " + "iiff" * 4 + " ff3fff f i3f I")
FLAG_TABLE = 1


def cstr(s: str, n: int) -> bytes:
    b = s.encode("utf-8")
    if len(b) >= n:
        raise ValueError(f"{s!r} longer than {n - 1} bytes")
    return b


def tri(v):
    return list(v) + [v[0]] * (3 - len(v))


def lut_path(f: dict) -> Path | None:
    name = f.get("lut")
    if not name:
        return None
    p = LUTS / name.removeprefix("filmluts/")
    return p if p.is_file() else None


def bake(f: dict, path: Path) -> bytes:
    """As genfilms.bake(), at uint16."""
    table = lutlib.Lut(str(path), f.get("lut_space"))
    g = np.arange(GRID, dtype=np.float32) / (GRID - 1)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")          # red changes fastest, as the camera's grid
    lin = lutlib.decode(np.stack([r, gg, b], -1).reshape(-1, 3), "cineon")
    rgb = np.clip(table.apply(lin), 0, 1)
    return (rgb * 65535 + 0.5).astype("<u2").tobytes()


def main() -> int:
    keys = list(FILMS)
    records, tables, meta = [], [], []
    table_base = HEADER.size + RECORD.size * len(keys)
    offset = table_base
    for key in keys:
        f = FILMS[key]
        hues = f.get("hues", [])[:4]
        hv = []
        for a, b2, amt, ch in hues:
            hv += [HUES.index(a), HUES.index(b2), amt, ch]
        hv += [0, 0, 0.0, 0.0] * (4 - len(hues))
        mono = f.get("mono")
        lp = lut_path(f)
        table = bake(f, lp) if lp else b""
        flags = FLAG_TABLE if table else 0
        brand, _, _ = f["name"].partition(" ")
        records.append(RECORD.pack(
            cstr(key, 24), cstr(f["name"], 48), cstr(short_name(key), 24), cstr(brand, 16),
            f["iso"], KINDS.index(f["kind"]), flags,
            int(f.get("balance", 5500)), int(bool(f.get("slide"))), f.get("ev", 0.0), f.get("sat", 1.0),
            *tri(f["contrast"]), *tri(f["pivot"]), *tri(f["black"]), *tri(f["white"]),
            len(hues), *hv,
            f.get("halation", 0.0), f.get("hal_thr", 0.75), *f.get("hal_tint", (1.0, 0.28, 0.06)),
            f.get("grain", 0.0), f.get("grain_size", 1.0), f.get("soft", 0.0),
            int(bool(mono)), *tri(mono or (0, 0, 0)),
            offset if table else 0))
        if table:
            tables.append(table)
            offset += len(table)
        meta.append({"key": key, "name": f["name"], "short": short_name(key), "iso": f["iso"], "kind": f["kind"],
                     "colour": "lut" if table else "model",
                     "lut": str(lp.relative_to(ROOT)) if lp else None,
                     "lut_wanted_missing": bool(f.get("lut")) and not lp})
    blob = HEADER.pack(b"MFB1", VERSION, len(keys), GRID, RECORD.size) + b"".join(records) + b"".join(tables)
    out = ROOT / "profiles" / "mfilm-films.bin"
    out.write_bytes(blob)
    h = hashlib.sha256(blob).hexdigest()
    (ROOT / "profiles" / "films.json").write_text(json.dumps(
        {"bundle": out.name, "profile_bundle_hash": h, "format_version": VERSION, "grid": GRID,
         "films": meta}, indent=1, ensure_ascii=False) + "\n")
    n_lut = sum(m["colour"] == "lut" for m in meta)
    print(f"{out.relative_to(ROOT)}: {len(keys)} films ({n_lut} LUT tables, {len(keys) - n_lut} model), "
          f"{len(blob)} bytes, sha256 {h}")
    missing = [m["key"] for m in meta if m["lut_wanted_missing"]]
    if missing:
        print("  LUT named but absent (model colour used):", ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
