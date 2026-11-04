# SPDX-License-Identifier: GPL-2.0-only
"""Lens geometry for CHDK DNGs (mfilm_server.lens) against the committed
SX510 HS table. The calibration shots themselves are not in Git."""
import hashlib
from itertools import pairwise

import numpy as np
import pytest
from mfilm_server import develop, lens

MODEL = "Canon PowerShot SX510 HS"
CHDK = {"software": "CHDK ver. 1.6.1", "model": MODEL, "focal_mm": 4.3}
# The lens table changes pixels without changing render ids, so a new table must
# come with a new INPUT_NORMALIZATION. Update both together.
PINNED = {"mfilm-linear-rgb-v2": "613a1c08deff3fce96e798ceb2efeca6f3dfddafc85324bd3691ace5ca630749"}


@pytest.fixture(scope="module")
def table():
    t = lens.table_for(CHDK)
    assert t is not None
    return t


def corners(t):
    w, h = t["output_width"], t["output_height"]
    return np.array([[0.5, 0.5], [w - 0.5, 0.5], [0.5, h - 0.5], [w - 0.5, h - 0.5]])


def test_table_is_pinned_to_input_normalization(table):
    sha = hashlib.sha256((lens.LENS_DIR / table["file"]).read_bytes()).hexdigest()
    assert PINNED.get(develop.INPUT_NORMALIZATION) == sha, "lens table changed: bump INPUT_NORMALIZATION"


def test_only_chdk_dngs_of_the_calibrated_camera(table):
    assert lens.table_for({**CHDK, "software": "Canon"}) is None
    assert lens.table_for({**CHDK, "model": "Canon EOS M"}) is None
    assert lens.table_for({}) is None
    assert (table["output_width"], table["output_height"]) == (4000, 3000)


def test_long_end_is_the_dng_default_crop(table):
    # from ~15 mm the camera JPEG is the DNG DefaultCrop (36, 22) + 4000x3000, no distortion
    for fl in (15.4, 30, 74, 129, 500):
        d = lens.source_coords(table, fl, corners(table)) - corners(table)
        assert np.abs(d - [36, 22]).max() < 2.0, fl


def test_wide_end_reaches_into_the_raw(table):
    src = lens.source_coords(table, 4.3, corners(table))
    assert 300 < src[0, 0] < 380 and 220 < src[0, 1] < 280          # top-left from well inside the image circle
    assert 3690 < src[3, 0] < 3780 and 2760 < src[3, 1] < 2840


def test_distortion_shrinks_monotonically_with_focal_length(table):
    tl = [lens.source_coords(table, fl, corners(table)[:1])[0, 0] for fl in (4.3, 5, 6, 7, 8, 9, 10, 12, 16)]
    assert all(a > b for a, b in pairwise(tl))
    exact = table["focal_lengths"][1]
    got = lens.source_coords(table, exact["focal_mm"], corners(table)[:1])
    want = lens.radial_map(corners(table)[:1], (4000, 3000), *[exact[k] for k in ("cx", "cy", "s", "k1", "k2", "k3")])
    assert np.allclose(got, want)


def test_correct_samples_the_mapped_position(table):
    # a linear ramp image: bilinear sampling returns the source coordinate exactly
    H, W = 3044, 4072
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    img = np.stack([xx + 0.5, yy + 0.5, np.zeros_like(xx)], -1)
    out = lens.correct(img, table, 6.0)
    assert out.shape == (3000, 4000, 3)
    pts = np.array([[0.5, 0.5], [2000.5, 1500.5], [3999.5, 2999.5], [1234.5, 77.5]])
    src = lens.source_coords(table, 6.0, pts)
    for (x, y), (sx, sy) in zip(pts, src):
        assert abs(out[int(y), int(x), 0] - sx) < 1e-2 and abs(out[int(y), int(x), 1] - sy) < 1e-2


def test_dng_info_of_a_non_tiff_is_empty(tmp_path):
    p = tmp_path / "x.DNG"
    p.write_bytes(b"not a dng")
    assert lens.dng_info(p) == {}
