# SPDX-License-Identifier: GPL-2.0-only
"""Data files for the camera's own developer (src/camera/dev).

MFCAM.BIN: "MFCAM001" + struct mfd_camera (little-endian int32):
    wb_q16[3]   lin_Q15 = (raw - black) * wb_q16 >> 16   (white balance and 1/(white-black))
    m_q12[9]    camera RGB -> linear sRGB, rows, Q12
    jpeg_w, jpeg_h, nlens
    lens[24]    focal_q8, cx_q8, cy_q8, s_q24, k1_q24, k2_q24, k3_q24
The colour is LibRaw's daylight transform for the SX510 HS, fitted to it
(docs/audit/P05-chdk-dng-calibration.md); the lens entries are
profiles/lenses/canon-sx510hs.json in fixed point.

MFDEV.BIN (every film baked at 1024x768) is written by the C tool mfdev_gen.
"""
from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

from .lens import LENS_DIR

MAGIC = b"MFCAM001"
MAX_LENS = 24
BLACK, WHITE = 127, 4095
# LibRaw daylight white balance (normalised to green) and camera -> sRGB matrix, SX510 HS
WB_DAYLIGHT = (1.5452, 1.0, 1.7791)
CAM_TO_SRGB = ((1.555, -0.3059, -0.2491), (-0.3765, 2.0334, -0.657), (0.0487, -0.8561, 1.8074))
REPO = Path(__file__).resolve().parents[3]


def camera_blob(lens_file: Path | None = None) -> bytes:
    t = json.loads((lens_file or LENS_DIR / "canon-sx510hs.json").read_text())
    fls = sorted(t["focal_lengths"], key=lambda e: e["focal_mm"])
    if not 1 <= len(fls) <= MAX_LENS:
        raise ValueError(f"{len(fls)} lens entries (1..{MAX_LENS})")
    span = WHITE - BLACK
    wb = [round(w / span * 32768 * 65536) for w in WB_DAYLIGHT]
    m = [round(v * 4096) for row in CAM_TO_SRGB for v in row]
    out = MAGIC + struct.pack("<3i", *wb) + struct.pack("<9i", *m)
    out += struct.pack("<3i", int(t["output_width"]), int(t["output_height"]), len(fls))
    for e in fls:
        out += struct.pack("<7i", round(e["focal_mm"] * 256), round(e["cx"] * 256), round(e["cy"] * 256),
                           round(e["s"] * 2 ** 24), round(e["k1"] * 2 ** 24), round(e["k2"] * 2 ** 24),
                           round(e["k3"] * 2 ** 24))
    out += bytes(7 * 4 * (MAX_LENS - len(fls)))
    return out


def mfdev_gen() -> Path:
    for p in (REPO / "build" / "src" / "shared" / "film_core" / "mfdev_gen",):
        if p.is_file():
            return p
    raise FileNotFoundError("mfdev_gen not built: cmake --build build --target mfdev_gen")


def films_blob(bundle: Path, out: Path) -> None:
    subprocess.run([str(mfdev_gen()), str(bundle), str(out)], check=True, capture_output=True)
