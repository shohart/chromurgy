# SPDX-License-Identifier: GPL-2.0-only
"""End-to-end mfilm-develop on M-Film's sample CR2 (EOS M, not SX510 HS:
a decoder/pipeline fixture only). Needs the built core and vendor/m-film."""
import json

import numpy as np
import pytest

from conftest import REPO
from mfilm_server import core, develop

SAMPLE = REPO / "vendor" / "m-film" / "ml-dev" / "films" / "sample" / "SAMPLE.CR2"
UPSTREAM_PRINT = REPO / "vendor" / "m-film" / "ml-dev" / "filmos" / "sim" / "out" / "sample.ppm"

pytestmark = pytest.mark.skipif(not SAMPLE.is_file() or not core.lib_path().is_file(),
                                reason="needs vendor/m-film (scripts/fetch-upstream.sh) and the built core")


@pytest.fixture(scope="module")
def bundle():
    return core.Bundle()


def recipe(bundle, **over):
    r = develop.default_recipe("portra400", bundle.sha256)
    r["output_spec"].update(width=720, height=480)
    for k, v in over.items():
        r[k] = v
    return r


def test_bundle_has_all_films(bundle):
    assert len(bundle.keys) == 72 and "portra400" in bundle.keys and "kodachrome64" in bundle.keys


def test_develop_sample_and_provenance(tmp_path, bundle):
    out = tmp_path / "a.jpg"
    prov = develop.develop(SAMPLE, out, profile=None, recipe=recipe(bundle), bundle=bundle)
    side = json.loads((tmp_path / "a.jpg.json").read_text())
    assert side == prov
    assert prov["lens_correction"]["applied"] is False       # a CR2 is not a CHDK DNG
    assert (prov["output_width"], prov["output_height"]) == (720, 480)
    for key in ("render_id", "profile_bundle_hash", "film_core_git_commit", "grain_seed", "original_sha256",
                "raw_adapter_version", "developed_by", "output_sha256"):
        assert prov[key]
    # same inputs -> same render id and bytes
    prov2 = develop.develop(SAMPLE, tmp_path / "b.jpg", profile=None, recipe=recipe(bundle), bundle=bundle)
    assert prov2["render_id"] == prov["render_id"] and prov2["output_sha256"] == prov["output_sha256"]


@pytest.mark.skipif(not UPSTREAM_PRINT.is_file(), reason="needs the upstream devtest print")
def test_close_to_upstream_camera_print(tmp_path, bundle):
    """Same CR2, same film: our 720x480 vs M-Film's own in-camera developer."""
    from PIL import Image
    out = tmp_path / "p.jpg"
    develop.develop(SAMPLE, out, profile=None, recipe=recipe(bundle), bundle=bundle)
    ours = np.asarray(Image.open(out).convert("RGB"), float) / 255
    theirs = np.asarray(Image.open(UPSTREAM_PRINT).convert("RGB"), float) / 255
    diff = np.abs(ours.reshape(-1, 3).mean(0) - theirs.reshape(-1, 3).mean(0))
    assert diff.max() < 0.01, diff


def test_errors(tmp_path, bundle):
    with pytest.raises(develop.DevelopError) as e:
        develop.develop(SAMPLE, tmp_path / "x.jpg", profile="no-such-film", recipe=None, bundle=bundle)
    assert e.value.code == "UNSUPPORTED_PROFILE"
    with pytest.raises(develop.DevelopError) as e:
        develop.develop(SAMPLE, tmp_path / "x.jpg", profile=None,
                        recipe=recipe(bundle, profile_bundle_hash="0" * 64), bundle=bundle)
    assert e.value.code == "PROFILE_BUNDLE_MISMATCH"
    big = recipe(bundle)
    big["output_spec"].update(width=8000, height=6000)
    with pytest.raises(develop.DevelopError) as e:
        develop.develop(SAMPLE, tmp_path / "x.jpg", profile=None, recipe=big, bundle=bundle)
    assert e.value.code == "OUTPUT_LARGER_THAN_SOURCE"
    bad = tmp_path / "bad.dng"
    bad.write_bytes(b"II*\x00" + b"\x00" * 100)
    with pytest.raises(develop.DevelopError) as e:
        develop.develop(bad, tmp_path / "x.jpg", profile="portra400", recipe=None, bundle=bundle)
    assert e.value.code == "BAD_DNG"
    assert not (tmp_path / "x.jpg").exists()


def test_cli_json_error(capsys):
    assert develop.main(["--input", str(SAMPLE), "--output", "/nonexistent/x.jpg", "--profile", "nope", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {"ok": False, "error_code": "UNSUPPORTED_PROFILE", "detail": "nope"}
