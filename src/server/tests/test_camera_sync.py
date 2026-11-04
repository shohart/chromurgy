# SPDX-License-Identifier: GPL-2.0-only
import sys
from pathlib import Path

import pytest

from mfilm_server.camera_sync import SyncError, sync

FAKE = __file__.replace("test_camera_sync.py", "fake_chdkptp.py")


def _hashless(d, c):
    for fr in d["frames"]:
        fr.pop("source_sha256")
        fr["original_status"] = "WRITTEN"


def test_sync_pulls_sealed_rolls_and_imports_them(make_card, store, conn, tmp_path):
    card = make_card(mutate=_hashless)
    cmd = f"{sys.executable} {FAKE} --card {card}"
    r = sync(store, conn, chdkptp=cmd, mirror=tmp_path / "mirror")
    assert [x.status for x in r.rolls] == ["IMPORTED"]
    assert sorted(r.downloaded) == ["A/DCIM/100CANON/IMG_0001.DNG", "A/DCIM/100CANON/IMG_0002.DNG"]
    assert conn.execute("SELECT COUNT(*) FROM frames WHERE original_state='VERIFIED'").fetchone()[0] == 2
    again = sync(store, conn, chdkptp=cmd, mirror=tmp_path / "mirror")
    assert again.downloaded == [] and [x.status for x in again.rolls] == ["UNCHANGED"]
    assert not list((tmp_path / "mirror").rglob("*.part"))


def test_sync_skips_unsealed_rolls(make_card, store, conn, tmp_path):
    card = make_card(state="CAPTURING")
    r = sync(store, conn, chdkptp=f"{sys.executable} {FAKE} --card {card}", mirror=tmp_path / "m")
    assert r.downloaded == [] and [x.status for x in r.rolls] == ["SKIPPED"]


def test_sync_without_camera(make_card, store, conn, tmp_path):
    card = make_card()
    with pytest.raises(SyncError) as e:
        sync(store, conn, chdkptp=f"{sys.executable} {FAKE} --card {card} --offline", mirror=tmp_path / "m")
    assert e.value.code == "CAMERA_NOT_CONNECTED"


def test_sync_retries_a_broken_download_and_keeps_the_log(make_card, store, conn, tmp_path):
    card = make_card(mutate=_hashless)
    r = sync(store, conn, chdkptp=f"{sys.executable} {FAKE} --card {card} --fail-d 1", mirror=tmp_path / "m")
    assert len(r.downloaded) == 2 and r.failed == []
    assert [x.status for x in r.rolls] == ["IMPORTED"]
    assert "ptpip read failed" in Path(r.log_path).read_text()


def test_sync_reports_downloads_that_keep_failing(make_card, store, conn, tmp_path):
    card = make_card(mutate=_hashless)
    r = sync(store, conn, chdkptp=f"{sys.executable} {FAKE} --card {card} --fail-d 4", mirror=tmp_path / "m")
    assert r.downloaded == [] and len(r.failed) == 2
    assert all("attempt 2: got 4 of" in why and "ptpip read failed" in why for _, why in r.failed)
    assert not list((tmp_path / "m").rglob("*.part"))
