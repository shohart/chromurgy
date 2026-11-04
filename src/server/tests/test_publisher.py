# SPDX-License-Identifier: GPL-2.0-only
import json

import pytest
from mfilm_server import core, publisher, worker
from mfilm_server.cli import main
from mfilm_server.config import PhotoPrism, load
from mfilm_server.importer import import_card
from PIL import Image
from test_develop import SAMPLE
from test_worker import sample_card  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not SAMPLE.is_file() or not core.lib_path().is_file(),
                                reason="needs vendor/m-film and the built core")


@pytest.fixture
def developed(sample_card, store, conn):  # noqa: F811
    import_card(sample_card, store, conn)
    roll = conn.execute("SELECT id FROM rolls").fetchone()[0]
    worker.enqueue_roll(conn, roll)
    assert [r.state for r in worker.run(conn, store)] == ["COMMITTED"]
    return roll


def test_publish_is_atomic_idempotent_and_dated(developed, store, conn, tmp_path):
    lib = tmp_path / "photoprism-originals"
    lib.mkdir()
    pp = PhotoPrism(export_dir=lib, index_command=["true"])
    res = publisher.publish_roll(conn, store, pp, developed)
    assert [r.status for r in res] == ["EXPORTED"]
    files = list(lib.rglob("*"))
    jpgs = [f for f in files if f.is_file()]
    assert len(jpgs) == 1 and not jpgs[0].name.startswith(".")
    assert jpgs[0].parent.name.startswith("2026-11-02_Portra400_")
    with Image.open(jpgs[0]) as im:
        assert im.getexif().get_ifd(0x8769)[0x9003] == "2026:11:02 12:01:00"
    assert conn.execute("SELECT state FROM renders").fetchone()[0] == "PUBLISHED"
    again = publisher.publish_roll(conn, store, pp, developed)
    assert [r.status for r in again] == ["ALREADY"]
    ok, _ = publisher.run_index(conn, pp, [res[0].render_id])
    assert ok and conn.execute("SELECT status FROM publications").fetchone()[0] == "INDEXED"


def test_failed_index_leaves_exported(developed, store, conn, tmp_path):
    pp = PhotoPrism(export_dir=tmp_path, index_command=["false"])
    res = publisher.publish_roll(conn, store, pp, developed)
    ok, _ = publisher.run_index(conn, pp, [r.render_id for r in res])
    assert not ok and conn.execute("SELECT status FROM publications").fetchone()[0] == "EXPORTED"


def test_unconfigured_is_an_error(developed, store, conn):
    with pytest.raises(publisher.PublishError):
        publisher.publish_roll(conn, store, PhotoPrism(), developed)


def test_config_and_worker_autopublish(sample_card, store, tmp_path, capsys):  # noqa: F811
    lib = tmp_path / "lib"
    lib.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'data_dir = "{store.root}"\n[photoprism]\nexport_dir = "{lib}"\nindex_command = ["true"]\n')
    assert load(cfg).photoprism.index_command == ["true"]
    assert main(["import-card", str(sample_card), "--config", str(cfg)]) == 0
    capsys.readouterr()
    assert main(["worker", "--config", str(cfg), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["published"][0]["published"][0]["status"] == "EXPORTED" and out["index"]["ok"]
    assert len([f for f in lib.rglob("*.jpg")]) == 1


def test_index_command_must_be_argv(tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text('[photoprism]\nindex_command = "rm -rf /"\n')
    with pytest.raises(ValueError):
        load(cfg)


def test_a_fixed_pipeline_supersedes_its_earlier_render_but_looks_stay():
    import json

    from mfilm_server.publisher import _newest_pipeline

    def row(rid, ordinal, norm, grain=1.0, film="portra400"):
        rec = {"recipe_id": f"r-{norm}", "film_profile_id": film, "input_normalization_version": norm,
               "look_controls": {"grain_scale": grain}}
        return {"id": rid, "ordinal": ordinal, "recipe_json": json.dumps(rec)}

    rows = [row("a2", 1, "mfilm-linear-rgb-v2"), row("a3", 1, "mfilm-linear-rgb-v3"),
            row("b2", 2, "mfilm-linear-rgb-v2"), row("g2", 1, "mfilm-linear-rgb-v2", grain=2.0),
            row("e2", 1, "mfilm-linear-rgb-v2", film="ektar100")]
    keep, gone = _newest_pipeline(rows)
    assert [r["id"] for r in keep] == ["a3", "b2", "g2", "e2"]
    assert [r["id"] for r in gone] == ["a2"]
