# SPDX-License-Identifier: GPL-2.0-only
import json

import pytest

from mfilm_server.ids import canonical_json, frame_seed, render_id
from conftest import REPO


def test_frame_seed_matches_c_core_vector():
    # same vector as src/shared/film_core/tests/test_seed.c
    assert frame_seed("sx510hs-demo-001", "r1", "r1-0001", "portra400", "recipe-v1", 0) == 0xe64520a3e9d1b46c


def test_render_id_depends_on_output_size():
    recipe = json.loads((REPO / "contracts" / "render-recipe.example.json").read_text())
    base = dict(original_sha256="a" * 64, recipe=recipe, film_core_version="x", profile_bundle_hash="b" * 64,
                input_normalization_version="mfilm-linear-rgb-v1")
    big = render_id(output_spec={"width": 4000, "height": 3000}, **base)
    small = render_id(output_spec={"width": 720, "height": 480}, **base)
    assert big != small and len(big) == 64
    assert big == render_id(output_spec={"height": 3000, "width": 4000}, **base)   # key order irrelevant


def test_canonical_json_rejects_nan():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
