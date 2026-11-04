# SPDX-License-Identifier: GPL-2.0-only
"""The camera app (src/camera/app) in CHDK's own host Lua, driven through
scenarios by src/camera/test/harness.lua, and the cards it leaves behind
imported by the real receiver. Needs build/hostlua (tools/build_hostlua.sh)."""
import json
import re
import subprocess

import pytest

from conftest import REPO
from mfilm_server import core
from mfilm_server.camera_card import write_card
from mfilm_server.importer import find_manifests, import_card

LUA = REPO / "build" / "hostlua" / "lua"
LUAC = REPO / "build" / "hostlua" / "luac"
APP = REPO / "src" / "camera" / "app"
HARNESS = REPO / "src" / "camera" / "test" / "harness.lua"
FUNCS16 = REPO / "src" / "camera" / "test" / "chdk-1.6.1-r6355-lua-functions.txt"

pytestmark = pytest.mark.skipif(not LUA.is_file() or not core.lib_path().is_file(),
                                reason="needs build/hostlua (tools/build_hostlua.sh) and the built core")

LOAD_PORTRA = [("expect", "NO FILM"), ("key", "down"), ("key", "set"), ("expect", "Choose film"), ("key", "set"),
               ("expect", "Roll length")]
LEN36, LEN24, LEN12 = [("key", "set")], [("key", "down"), ("key", "set")], [("key", "down"), ("key", "down"),
                                                                          ("key", "set")]


def lua_step(s):
    def val(v):
        if isinstance(v, dict):
            return "{" + ",".join(f"{k}={val(x)}" for k, x in v.items()) + "}"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            return str(v)
        return json.dumps(v)
    return "{" + ",".join(val(x) for x in s) + "}"


@pytest.fixture
def card(tmp_path):
    root = tmp_path / "run"
    (root / "A").mkdir(parents=True)
    write_card(root / "A", utc_offset="+02:00")
    return root


def run(root, steps, expect_ok=True):
    scen = root / f"scenario{len(list(root.glob('scenario*.lua')))}.lua"
    scen.write_text("return {\n" + ",\n".join(lua_step(s) for s in steps) + "\n}\n")
    p = subprocess.run([str(LUA), str(HARNESS), str(APP), str(scen)], cwd=root, capture_output=True, text=True,
                       timeout=120)
    if expect_ok:
        assert p.returncode == 0, p.stderr + p.stdout
    return p


def rolls(root):
    return [json.loads(m.read_text()) for m in find_manifests(root / "A")]


def applog(root):
    return (root / "A" / "CHDK" / "MFILM" / "LOGS" / "APP.LOG").read_text()


def shots(n, **o):
    return [s for _ in range(n) for s in (("shoot", o) if o else ("shoot",), ("wait", 700))]


def test_app_uses_only_chdk_161_functions():
    have = {line.strip() for line in FUNCS16.read_text().splitlines() if line and not line.startswith("#")}
    lua_std = {"string", "table", "math", "os", "io", "pairs", "ipairs", "type", "tostring", "tonumber", "print",
               "require", "pcall", "error", "assert", "loadfile", "dofile", "select", "unpack", "next", "_G",
               "setmetatable", "getmetatable", "rawget", "rawset", "collectgarbage", "loadstring"}
    chdk_tables = {"hook_raw", "hook_shoot", "hook_preshoot"}
    used = set()
    for f in ("MFILM.LUA", "mfroll.lua"):
        listing = subprocess.run([str(LUAC), "-p", "-l", str(APP / f)], capture_output=True, text=True, check=True)
        used |= set(re.findall(r"[GS]ETGLOBAL\s.*;\s*(\w+)", listing.stdout))
    for f in ("MFILM.LUA", "mfroll.lua"):
        listing = subprocess.run([str(LUAC), "-p", "-l", str(APP / f)], capture_output=True, text=True, check=True)
        assert not re.findall(r"SETGLOBAL\s.*;\s*(\w+)", listing.stdout), f"{f} assigns a global"
    unknown = used - have - lua_std - chdk_tables
    # names the app guards with have()/type() checks before use are allowed to be missing on the camera
    assert not unknown, f"not in CHDK 1.6.1: {sorted(unknown)}"


def test_full_roll_seals_and_imports(card, store, conn):
    run(card, LOAD_PORTRA + LEN12 + [("wait", 600), ("expect", "Portra400 0/12")] + shots(12)
        + [("expect", "Roll complete")] + shots(1) + [("expect", "NO FILM")])
    (r,) = rolls(card)
    assert r["roll_state"] == "SEALED" and r["captured_frames"] == 12 and r["roll_length"] == 12
    assert r["profile_bundle_hash"] == core.Bundle().sha256 and r["film_profile_id"] == "portra400"
    assert [f["ordinal"] for f in r["frames"]] == list(range(1, 13))
    assert len({f["source_path"] for f in r["frames"]}) == 12
    assert "shot outside a roll" in applog(card)
    res = import_card(card / "A", store, conn)
    assert [x.status for x in res] == ["IMPORTED"], res
    assert conn.execute("SELECT COUNT(*) FROM frames WHERE original_state='VERIFIED'").fetchone()[0] == 12


def test_power_cut_resume_and_finish_from_menu(card, store, conn):
    run(card, LOAD_PORTRA + LEN36 + [("wait", 600)] + shots(3) + [("powercut",), ("restart",), ("wait", 300),
        ("expect", "3/36"), ("key", "shoot_half"), ("wait", 600)] + shots(2)
        + [("playback",), ("expect", "M%-Film"), ("key", "down"), ("key", "down"), ("key", "set"),   # Finish roll now
           ("expect", "Seal it now"), ("key", "up"), ("key", "set"), ("wait", 300), ("expect", "NO FILM")])
    (r,) = rolls(card)
    assert r["roll_state"] == "SEALED" and r["captured_frames"] == 5 and r["roll_length"] == 36
    journal = next((card / "A" / "CHDK" / "MFILM" / "ROLLS").glob("*/JOURNAL.LOG")).read_text()
    assert "RESUMED" in journal and "SEALED frames=5" in journal
    assert [x.status for x in import_card(card / "A", store, conn)] == ["IMPORTED"]


def test_dcim_folder_rollover_and_raw_off(card):
    run(card, LOAD_PORTRA + LEN24 + [("wait", 600)] + shots(2) + [("setdir", "A/DCIM/102___02")] + shots(2)
        + shots(1, raw=False) + [("wait", 11000), ("expect", "No DNG written")])
    (r,) = rolls(card)
    dirs = [f["source_path"].split("/")[2] for f in r["frames"]]
    assert dirs == ["101___01", "101___01", "102___02", "102___02"] and r["roll_state"] == "CAPTURING"


def test_overwritten_dng_is_flagged_not_double_counted(card):
    run(card, LOAD_PORTRA + LEN24 + [("wait", 600)] + shots(2) + shots(1, overwrite="CRW_0102.DNG")
        + [("expect", "overwritten")])
    (r,) = rolls(card)
    assert r["captured_frames"] == 2
    assert "DNG changed after it was recorded" in applog(card)


def test_old_dngs_are_not_frames_and_new_film_seals_the_old_roll(card):
    run(card, [("shoot",), ("wait", 300), ("shoot",)])                 # DNGs on the card before a roll is loaded
    run(card, LOAD_PORTRA + LEN12 + [("wait", 600)] + shots(1)
        + [("playback",), ("key", "down"), ("key", "set"), ("expect", "Finish %(seal%) it"), ("key", "up"),
           ("key", "set"), ("expect", "Choose film"), ("key", "down"), ("key", "set"), ("key", "set"),
           ("wait", 600)] + shots(1))
    rs = rolls(card)
    assert len(rs) == 2
    sealed = [r for r in rs if r["roll_state"] == "SEALED"]
    live = [r for r in rs if r["roll_state"] != "SEALED"]
    assert len(sealed) == 1 and sealed[0]["captured_frames"] == 1 and sealed[0]["film_profile_id"] == "portra400"
    assert len(live) == 1 and live[0]["captured_frames"] == 1 and live[0]["roll_length"] == 36
    assert live[0]["film_profile_id"] != "portra400"
    used = {f["source_path"] for r in rs for f in r["frames"]}
    assert "A/DCIM/101___01/CRW_0101.DNG" not in used and "A/DCIM/101___01/CRW_0102.DNG" not in used


def test_quit_from_menu(card):
    run(card, LOAD_PORTRA + LEN12 + [("wait", 600), ("playback",), ("key", "up"), ("key", "set"),
        ("expect", "NOT recorded"), ("key", "up"), ("key", "set"), ("expect_exit",)])
    assert "---- quit" in applog(card)
    (r,) = rolls(card)
    assert r["roll_state"] == "LOADED"


def test_autostart_goes_straight_to_shooting_with_film_loaded(card):
    run(card, [("expect_autostart", 1)] + LOAD_PORTRA + LEN12 + [("wait", 600)] + shots(2)
        + [("powercut",), ("boot",), ("wait", 1200), ("expect", "Portra400 2/12")] + shots(1)
        + [("expect", "Portra400 3/12")])
    (r,) = rolls(card)
    assert r["captured_frames"] == 3


def test_autostart_can_be_switched_off_from_the_menu(card):
    run(card, [("expect", "Start with camera: ON"), ("key", "down"), ("key", "down"), ("key", "down"),
               ("key", "down"), ("key", "set"), ("expect", "Start with camera: OFF"), ("expect_autostart", 0)])


def test_menu_in_playback_with_chdk_osd_off_then_restored(card):
    run(card, [("wait", 300), ("expect_state", False, 0)] + LOAD_PORTRA + LEN12 + [("wait", 600),
               ("expect_state", True, 1), ("expect", "Portra400 0/12")] + shots(1)
        + [("playback",), ("wait", 900), ("expect_state", False, 0), ("key", "shoot_half"), ("wait", 600),
           ("expect_state", True, 1)])
