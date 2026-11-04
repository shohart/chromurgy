# SPDX-License-Identifier: GPL-2.0-only
"""Card -> archive -> queue -> developed JPEG, with M-Film's sample CR2 standing
in for an SX510 HS DNG (a pipeline fixture, not camera evidence)."""
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from mfilm_server import cli, core, worker
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


def _alt_bundle(tmp_path) -> Path:
    """A second valid bundle: the shipped one with one table value changed."""
    d = bytearray(core.bundle_path().read_bytes())
    d[-1] ^= 1
    p = tmp_path / "alt" / "mfilm-films.bin"
    p.parent.mkdir()
    p.write_bytes(bytes(d))
    return p


def test_unknown_bundle_parks_until_added(make_card, store, conn, tmp_path, capsys):
    alt = _alt_bundle(tmp_path)
    alt_sha = hashlib.sha256(alt.read_bytes()).hexdigest()

    def mutate(doc, card):
        dst = card / "DCIM" / "100CANON" / "IMG_0001.DNG"
        shutil.copyfile(SAMPLE, dst)
        data = dst.read_bytes()
        doc["frames"][0].update(source_size_bytes=len(data), source_sha256=hashlib.sha256(data).hexdigest())
        doc["profile_bundle_hash"] = alt_sha                      # shot with a bundle the server lacks
    import_card(make_card(frames=1, mutate=mutate), store, conn)
    roll = conn.execute("SELECT id FROM rolls").fetchone()[0]
    worker.enqueue_roll(conn, roll)
    res = worker.run(conn, store)
    assert [(r.state, r.error_code) for r in res] == [("WAITING_FOR_INPUTS", "PROFILE_BUNDLE_UNAVAILABLE")]
    assert conn.execute("SELECT attempt, state FROM jobs").fetchone()[:] == (0, "WAITING_FOR_INPUTS")
    assert worker.run(conn, store) == []                            # parked: not retried, not failed
    # never developed with the current bundle instead
    assert conn.execute("SELECT COUNT(*) FROM renders WHERE state='COMMITTED'").fetchone()[0] == 0

    root = ["--data-dir", str(store.root)]
    assert cli.main(["bundle-add", str(alt), *root]) == 0
    assert "1 waiting job(s) re-queued" in capsys.readouterr().out
    res = worker.run(conn, store)
    assert [r.state for r in res] == ["COMMITTED"]
    rel = conn.execute("SELECT a.path FROM renders r JOIN assets a ON a.id=r.asset_id").fetchone()[0]
    prov = json.loads((store.root / rel).with_suffix(".jpg.json").read_text())
    assert prov["profile_bundle_hash"] == alt_sha
    archived = store.root / "bundles" / f"{alt_sha}.bin"
    assert archived.is_file() and not os.access(archived, os.W_OK)
    assert cli.main(["bundle-list", *root]) == 0


def test_bundle_add_rejects_garbage(store, tmp_path, capsys):
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"MFB1" + b"\0" * 64)
    assert cli.main(["bundle-add", str(bad), "--data-dir", str(store.root)]) == 1
    assert not list((store.root / "bundles").glob(f"{hashlib.sha256(bad.read_bytes()).hexdigest()}*"))


def test_reprocess_new_film_keeps_old_and_is_idempotent(sample_card, store, conn, capsys):
    import_card(sample_card, store, conn)
    roll = conn.execute("SELECT id FROM rolls").fetchone()[0]
    worker.enqueue_roll(conn, roll)
    assert [r.state for r in worker.run(conn, store)] == ["COMMITTED"]
    root = ["--data-dir", str(store.root)]
    # unchanged recipe: same rendition, nothing queued
    assert cli.main(["reprocess", roll, *root]) == 0
    assert "nothing new" in capsys.readouterr().out
    assert cli.main(["reprocess", roll, "--profile", "nosuchfilm", *root]) == 1
    assert cli.main(["reprocess", roll, "--profile", "ektar100", "--grain-scale", "0.5", "--run", *root]) == 0
    assert cli.main(["reprocess", roll, "--profile", "ektar100", "--grain-scale", "0.5", *root]) == 0
    assert "nothing new" in capsys.readouterr().out.splitlines()[-1]
    rows = conn.execute("SELECT r.state, rc.json FROM renders r JOIN recipes rc ON rc.id=r.recipe_id "
                        "ORDER BY r.rowid").fetchall()
    assert [r["state"] for r in rows] == ["COMMITTED", "COMMITTED"]
    films = [json.loads(r["json"])["film_profile_id"] for r in rows]
    assert films == ["portra400", "ektar100"]
    new = json.loads(rows[1]["json"])
    assert new["recipe_id"].startswith("reprocess-ektar100-") and new["look_controls"]["grain_scale"] == 0.5
    # the roll itself stays frozen to its film
    assert conn.execute("SELECT film_profile_id FROM rolls").fetchone()[0] == "portra400"


def test_publish_folder_per_rendered_film(sample_card, store, conn, tmp_path):
    from mfilm_server import publisher
    from mfilm_server.config import PhotoPrism
    import_card(sample_card, store, conn)
    roll_row = conn.execute("SELECT * FROM rolls").fetchone()
    worker.enqueue_roll(conn, roll_row["id"])
    worker.enqueue_roll(conn, roll_row["id"], recipe=worker.build_recipe(roll_row, profile="ektar100"))
    assert [r.state for r in worker.run(conn, store)] == ["COMMITTED", "COMMITTED"]
    lib = tmp_path / "library"
    lib.mkdir()
    res = publisher.publish_roll(conn, store, PhotoPrism(export_dir=lib), roll_row["id"])
    assert [r.status for r in res] == ["EXPORTED", "EXPORTED"]
    assert sorted(p.parent.name.split("_")[1] for p in lib.glob("M-Film/*/*.jpg")) == ["Ektar100", "Portra400"]


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


def test_parallel_jobs_develop_each_frame_once(make_card, store, conn, tmp_path):
    bundle_hash = core.Bundle().sha256

    def mutate(doc, card):
        for fr in doc["frames"]:
            dst = card / "DCIM" / "100CANON" / Path(fr["source_path"]).name
            shutil.copyfile(SAMPLE, dst)
            data = dst.read_bytes()
            fr.update(source_size_bytes=len(data), source_sha256=hashlib.sha256(data).hexdigest())
        doc["profile_bundle_hash"] = bundle_hash
    import_card(make_card(frames=3, mutate=mutate), store, conn)
    roll = conn.execute("SELECT id FROM rolls").fetchone()[0]
    worker.enqueue_roll(conn, roll)
    res = worker.run(conn, store, jobs=3)
    assert sorted(r.state for r in res) == ["COMMITTED"] * 3
    assert len({r.render_id for r in res}) == 3
    assert conn.execute("SELECT state, attempt, COUNT(*) FROM jobs GROUP BY 1, 2").fetchall()[0][:] == ("COMMITTED", 1, 3)
    assert worker.run(conn, store, jobs=3) == []
    assert len(list((store.root / "renders").rglob("*.jpg"))) == 3
    assert not list((store.root / "incoming").iterdir())


def test_only_one_worker_pass_per_data_dir(store, conn):
    import fcntl

    from mfilm_server import worker
    with open(store.root / "worker.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(worker.WorkerBusy):
            worker.run(conn, store)
    worker.run(conn, store)                            # lock released: a pass runs again
