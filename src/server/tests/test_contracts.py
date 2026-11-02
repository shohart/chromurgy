# SPDX-License-Identifier: GPL-2.0-only
import json

import pytest

from mfilm_server import contracts
from conftest import REPO


def test_example_manifest_validates():
    raw = (REPO / "contracts" / "roll-manifest.example.json").read_bytes()
    doc = contracts.load_roll_manifest(raw)
    assert doc["captured_frames"] == len(doc["frames"]) == 2


def test_all_example_json_parse():
    for p in (REPO / "contracts").glob("*.json"):
        json.loads(p.read_text())


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d.update(roll_length=10), "MANIFEST_SCHEMA"),
    (lambda d: d.update(extra=1), "MANIFEST_SCHEMA"),
    (lambda d: d["frames"][1].update(ordinal=1), "MANIFEST_DUPLICATE_ORDINAL"),
    (lambda d: d.update(captured_frames=3), "MANIFEST_FRAME_COUNT"),
    (lambda d: d["frames"][0].update(source_sha256="xyz"), "MANIFEST_SCHEMA"),
])
def test_bad_manifests_rejected(mutate, code):
    doc = json.loads((REPO / "contracts" / "roll-manifest.example.json").read_text())
    mutate(doc)
    with pytest.raises(contracts.ManifestError) as e:
        contracts.load_roll_manifest(json.dumps(doc).encode())
    assert e.value.code == code


def test_not_json_rejected():
    with pytest.raises(contracts.ManifestError) as e:
        contracts.load_roll_manifest(b"\xff{")
    assert e.value.code == "MANIFEST_NOT_JSON"
