# SPDX-License-Identifier: GPL-2.0-only
"""compare_tables.py BUNDLE UPSTREAM_TABLE_DIR fos_film.c: our uint16 LUT tables vs upstream LOOKnn.LUT (uint8)."""
import re
import struct
import sys
from pathlib import Path

import numpy as np

bundle, updir, fos_film = Path(sys.argv[1]).read_bytes(), Path(sys.argv[2]), Path(sys.argv[3]).read_text()
magic, ver, n, grid, rsize = struct.unpack_from("<4sIIII", bundle)
src = fos_film[fos_film.index("static const struct fos_film builtin[]"):]
builtin = re.findall(r'\{ "(\w+)", "', src[:src.index("};")])
keys, tables = [], {}
for i in range(n):
    rec = bundle[20 + i * rsize: 20 + (i + 1) * rsize]
    key = rec[:24].split(b"\0")[0].decode()
    keys.append(key)
    flags = struct.unpack_from("<i", rec, 120)[0]
    toff = struct.unpack_from("<I", rec, rsize - 4)[0]
    if flags & 1:
        tables[key] = np.frombuffer(bundle, "<u2", grid ** 3 * 3, toff).astype(np.float64)
more = [k for k in keys if k not in builtin]
worst, checked = 0, 0
for idx, key in enumerate(more):
    f = updir / f"LOOK{len(builtin) + idx:02d}.LUT"
    if key not in tables:
        assert not f.exists(), f"upstream baked {key} but we have no table"
        continue
    up = np.frombuffer(f.read_bytes()[8:], np.uint8).astype(np.float64)
    d = np.abs(tables[key] / 257 - up).max()
    worst = max(worst, d)
    checked += 1
    if d > 1.0:
        print(f"FAIL {key}: max |diff| {d:.3f} (8-bit units)")
        sys.exit(1)
print(f"{checked} LUT tables match upstream within {worst:.3f} of an 8-bit step")
