# SPDX-License-Identifier: GPL-2.0-only
"""Card -> archive -> queue -> developed JPEG, with M-Film's sample CR2 standing
in for an SX510 HS DNG (a pipeline fixture, not camera evidence)."""
import hashlib
import json
import shutil

import pytest

from mfilm_server import core, worker
from mfilm_server.cli import main
from mfilm_server.importer import import_card
from test_develop import SAMPLE

pytestmark = pytest.mark.skipif(not SAMPLE.is_file() or not core.lib_path().is_file(),
                                reason="needs vendor/m-film and the built core")


@pytest.fixture
def sample_card(make_card):
    bundle_hash = core.Bundle().sha256

    def mutate(doc, card):
        dst = card / "DCIM" / "100CANON" / "IMG_0001.DNG"
        shutil.copyfile(SAMPLE, dst)
        data = dst.read_bytes()
        doc["frames"][0].update(source_size_bytes=len(data), source_sha256=hashlib.sha256(data).hexdigest())
        doc["profile_bundle_hash"] = bundle_hash
        doc["render_recipe_id"] = None
        del doc["render_recipe_id"]
    return make_card(frames=1, mutate=mutate)


def test_card_to_developed_jpeg(sample_card, store, conn):
    assert import_card(sample_card, store, conn)[0].status == "IMPORTED"
    roll = conn.execute("SELECT id FROM rolls").fetchone()[0]
    q = worker.enqueue_roll(conn, roll)
    assert q["queued"] == 1
    assert worker.enqueue_roll(conn, roll)["queued"] == 0          # idempotent
    res = worker.run(conn, store)
    assert [r.state for r in res] == ["COMMITTED"], res
    r = conn.execute("SELECT r.state, a.path, a.kind FROM renders r JOIN assets a ON a.id=r.asset_id").fetchone()
    assert tuple(r) == ("COMMITTED", r["path"], "render_jpeg")
    jpg = store.root / r["path"]
    side = json.loads(jpg.with_suffix(".jpg.json").read_text())
    assert side["render_id"] == jpg.stem and side["developed_by"] == "linux"
    assert (side["output_width"], side["output_height"]) == (side["source_width"], side["source_height"])
    assert worker.run(conn, store) == []                            # nothing left
    assert not list((store.root / "incoming").iterdir())


def test_bundle_mismatch_is_terminal(make_card, store, conn):
    def mutate(doc, card):
        dst = card / "DCIM" / "100CANON" / "IMG_0001.DNG"
        shutil.copyfile(SAMPLE, dst)
        data = dst.read_bytes()
        doc["frames"][0].update(source_size_bytes=len(data), source_sha256=hashlib.sha256(data).hexdigest())
    card = make_card(frames=1, mutate=mutate)                        # bundle hash "bbbb..."
    import_card(card, store, conn)
    roll = conn.execute("SELECT id FROM rolls").fetchone()[0]
    worker.enqueue_roll(conn, roll)
    res = worker.run(conn, store)
    assert [(r.state, r.error_code) for r in res] == [("FAILED_TERMINAL", "PROFILE_BUNDLE_MISMATCH")]


def test_stale_running_job_recovered(sample_card, store, conn):
    import_card(sample_card, store, conn)
    roll = conn.execute("SELECT id FROM rolls").fetchone()[0]
    worker.enqueue_roll(conn, roll)
    conn.execute("UPDATE jobs SET state='RUNNING'")                  # a worker died here
    assert worker.recover_stale(conn) == 1
    assert conn.execute("SELECT state FROM jobs").fetchone()[0] == "QUEUED"


def test_cli_import_queues_and_worker_develops(sample_card, store, capsys):
    assert main(["import-card", str(sample_card), "--data-dir", str(store.root), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["queued"][0]["queued"] == 1
    assert main(["worker", "--data-dir", str(store.root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["jobs"][0]["state"] == "COMMITTED"
    assert main(["list-rolls", "--data-dir", str(store.root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["developed"] == 1
