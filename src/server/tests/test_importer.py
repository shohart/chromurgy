# SPDX-License-Identifier: GPL-2.0-only
import json
import os

from mfilm_server.cli import main
from mfilm_server.ids import sha256_file
from mfilm_server.importer import import_card


def _snapshot(card):
    return {p: (p.stat().st_mtime_ns, sha256_file(p)[0]) for p in card.rglob("*") if p.is_file()}


def test_import_then_reimport_is_idempotent(make_card, store, conn):
    card = make_card()
    before = _snapshot(card)
    r1 = import_card(card, store, conn)
    assert [r.status for r in r1] == ["IMPORTED"]
    assert {f.status for f in r1[0].frames} == {"IMPORTED"}
    r2 = import_card(card, store, conn)
    assert [r.status for r in r2] == ["UNCHANGED"]
    assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 2
    assert conn.execute("SELECT state FROM rolls").fetchone()[0] == "INPUTS_COMPLETE"
    assert _snapshot(card) == before, "card must never be modified"
    archived = list((store.root / "originals").rglob("*.dng"))
    assert len(archived) == 2 and all(not os.access(p, os.W_OK) for p in archived)
    assert not list((store.root / "incoming").iterdir())


def test_dry_run_writes_nothing(make_card, store, conn):
    r = import_card(make_card(), store, conn, dry_run=True)
    assert r[0].status == "DRY_RUN" and {f.status for f in r[0].frames} == {"WOULD_IMPORT"}
    assert conn.execute("SELECT COUNT(*) FROM rolls").fetchone()[0] == 0
    assert not list((store.root / "originals").rglob("*"))


def test_hash_mismatch_keeps_roll_incomplete(make_card, store, conn):
    card = make_card(mutate=lambda d, c: d["frames"][1].update(source_sha256="0" * 64))
    r = import_card(card, store, conn)[0]
    assert r.status == "INCOMPLETE"
    assert [f.error_code for f in r.frames] == [None, "SOURCE_HASH_MISMATCH"]
    assert conn.execute("SELECT state FROM rolls").fetchone()[0] == "RECEIVING"
    states = dict(conn.execute("SELECT ordinal, original_state FROM frames").fetchall())
    assert states == {1: "VERIFIED", 2: "DECLARED"}


def test_conflicting_manifest_refused(make_card, store, conn):
    import_card(make_card(name="a"), store, conn)
    card_b = make_card(name="b", mutate=lambda d, c: d.update(film_profile_id="trix400"))
    r = import_card(card_b, store, conn)[0]
    assert r.status == "CONFLICT"
    assert conn.execute("SELECT film_profile_id FROM rolls").fetchone()[0] == "portra400"


def test_path_traversal_rejected(make_card, store, conn, tmp_path):
    (tmp_path / "secret.DNG").write_bytes(b"II*\x00secret")
    card = make_card(mutate=lambda d, c: d["frames"][0].update(source_path="A/../secret.DNG"))
    r = import_card(card, store, conn)[0]
    assert r.frames[0].error_code == "UNSAFE_SOURCE_PATH"


def test_unsafe_ids_rejected(make_card, store, conn):
    card = make_card(device_id="../evil")
    assert import_card(card, store, conn)[0].status == "INVALID"


def test_unsealed_roll_skipped(make_card, store, conn):
    r = import_card(make_card(state="CAPTURING"), store, conn)[0]
    assert r.status == "SKIPPED"
    assert conn.execute("SELECT COUNT(*) FROM rolls").fetchone()[0] == 0


def test_non_tiff_rejected(make_card, store, conn):
    def mutate(doc, card):
        p = card / "DCIM" / "100CANON" / "IMG_0001.DNG"
        data = b"JUNK" + p.read_bytes()[4:]
        p.write_bytes(data)
        import hashlib
        doc["frames"][0]["source_sha256"] = hashlib.sha256(data).hexdigest()
    r = import_card(make_card(mutate=mutate), store, conn)[0]
    assert r.frames[0].error_code == "UNSUPPORTED_DNG_FEATURE"


def test_cli_json_roundtrip(make_card, store, capsys):
    card = make_card()
    assert main(["import-card", str(card), "--data-dir", str(store.root), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rolls"][0]["status"] == "IMPORTED"
    assert main(["list-rolls", "--data-dir", str(store.root), "--json", "--state", "INPUTS_COMPLETE"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["verified"] == 2
    roll = rows[0]["id"]
    assert main(["verify", roll, "--data-dir", str(store.root)]) == 0
    capsys.readouterr()
    # this roll's bundle ("bbbb...") is not archived: reprocess refuses rather than substituting one
    assert main(["reprocess", roll, "--profile", "ektar100", "--data-dir", str(store.root)]) == 1
    assert "PROFILE_BUNDLE_UNAVAILABLE" in capsys.readouterr().err
