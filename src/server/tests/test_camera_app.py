# SPDX-License-Identifier: GPL-2.0-only
"""The camera app (src/camera/app) in CHDK's own host Lua, driven through
scenarios by src/camera/test/harness.lua, and the cards it leaves behind
imported by the real receiver. Needs build/hostlua (tools/build_hostlua.sh)."""
import json
import os
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


def run(root, steps, expect_ok=True, env=None):
    scen = root / f"scenario{len(list(root.glob('scenario*.lua')))}.lua"
    scen.write_text("return {\n" + ",\n".join(lua_step(s) for s in steps) + "\n}\n")
    p = subprocess.run([str(LUA), str(HARNESS), str(APP), str(scen)], cwd=root, capture_output=True, text=True,
                       timeout=120, env=env, check=False)
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
    # the M-Film CHDK build (tools/build_chdk16.sh) registers luaCB_<name> from mfilm_lua.c;
    # the app checks have(name) and says when the stock build lacks them
    mfilm_build = set(re.findall(r"luaCB_(mf_\w+)", (REPO / "src/camera/chdk/mfilm_lua.c").read_text()))
    script = (REPO / "tools/build_chdk16.sh").read_text()
    assert all(f"FUNC({n})" in script for n in mfilm_build), "register every mfilm_lua.c function"
    app = (APP / "MFILM.LUA").read_text()
    assert all(f'have("{n}")' in app for n in used & mfilm_build), "guard M-Film build functions with have()"
    unknown = used - have - lua_std - chdk_tables - mfilm_build
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


def test_menu_in_shooting_mode_with_canon_info_off_chdk_osd_off_then_restored(card):
    # 0.2.0: Canon's information display is switched off (DISP) for the app's
    # lifetime; the menu stays in shooting mode with CHDK's OSD off
    run(card, [("wait", 300), ("expect_state", True, 0), ("expect_prop", 105, 1)] + LOAD_PORTRA + LEN12
        + [("wait", 600), ("expect_state", True, 1), ("expect", "Portra400 0/12")] + shots(1)
        + [("playback",), ("wait", 900), ("expect_state", True, 0), ("key", "shoot_half"), ("wait", 600),
           ("expect_state", True, 1), ("expect_prop", 105, 1)])


def test_owner_turning_canon_info_back_on_is_undone_at_the_menu(card):
    run(card, LOAD_PORTRA + LEN12 + [("wait", 600), ("set_prop", 105, 0), ("playback",), ("wait", 900),
                                     ("expect_prop", 105, 1), ("expect", "Shoot")])


def test_quit_restores_canon_info(card):
    run(card, [("wait", 600), ("expect_prop", 105, 1), ("key", "up"), ("key", "set"), ("expect", "NOT recorded"),
               ("key", "up"), ("key", "set"), ("expect_exit",), ("expect_prop", 105, 0)])


def test_menu_cursor_redraws_two_rows_without_clearing(card):
    # camera test 0.1.7: clearing and repainting the whole menu on each key let
    # the photo/live view under it show through
    log = card / "draw.log"
    run(card, [("wait", 1500), ("snap", "start"), ("key", "down"), ("wait", 400), ("key", "down"), ("wait", 400),
               ("key", "up"), ("wait", 400), ("snap", "end")], env={**os.environ, "MFILM_DRAWLOG": str(log)})
    lines = log.read_text().splitlines()
    i0, i1 = lines.index("SNAP start"), lines.index("SNAP end")
    assert "C" not in lines[i0:i1]
    screen, changed = {}, 0
    for i, ln in enumerate(lines[:i1]):
        if ln == "C":
            screen = {}
        elif ln.startswith("S "):
            _, x, y, rest = ln.split(" ", 3)
            if i > i0 and screen.get((x, y)) != rest:
                changed += 1
            screen[(x, y)] = rest
    assert changed == 6   # 3 cursor moves x (old row + new row); the safety repaint rewrites identical rows


def test_menu_complete_in_both_bitmap_buffers(card):
    # camera test 0.2.0: Canon flips two bitmap buffers and CHDK draws into the
    # active one only, so rows drawn once were missing after a flip
    run(card, [("wait", 1500), ("flip",), ("wait", 300), ("expect_screen_full",),
               ("key", "down"), ("wait", 200), ("flip",), ("wait", 300), ("expect_screen_full",),
               ("canon_erase",), ("wait", 300), ("expect_screen_full",),
               ("flip_every", 7), ("key", "down"), ("wait", 300), ("key", "down"), ("wait", 300),
               ("flip_every", 0), ("wait", 300), ("flip",), ("wait", 300), ("expect_screen_full",),
               ("expect", "Rolls on card")])


def test_menu_screen_full_with_a_loaded_film(card):
    run(card, LOAD_PORTRA + LEN12 + [("wait", 600)] + shots(1)
        + [("playback",), ("wait", 900), ("flip",), ("wait", 300), ("expect_screen_full",),
           ("flip",), ("wait", 300), ("expect_screen_full",)])


def _developed_on_card(card, n=3, rid="aaaaaaaa-1111-4222-8333-444444444444"):
    vroot = card / "A" / "CHDK" / "MFVIEW"
    (vroot / "AAAAAAAA").mkdir(parents=True)
    for i in range(1, n + 1):
        (vroot / "AAAAAAAA" / f"F{i:02d}.MFV").write_bytes(b"MFV1" + bytes(8))
    (vroot / "INDEX.CFG").write_text(f"roll={rid}|portra400|Portra400|2026-11-04|{n}|AAAAAAAA|12345678\n")


ROLLS = [("wait", 1200), ("key", "down"), ("key", "down"), ("key", "down"), ("key", "set"), ("wait", 300)]


def test_viewer_shows_developed_frames_in_playback_and_returns(card):
    _developed_on_card(card)
    run(card, ROLLS + [("expect", "Portra400 +3 DEV"), ("key", "set"), ("expect", "DEVELOPED: 3 frames"),
                       ("key", "set"), ("wait", 600), ("expect_rec", False), ("expect_shown", "AAAAAAAA/F01.MFV"),
                       ("expect", "Portra400 2026%-11%-04  1/3"),
                       ("key", "right"), ("wait", 200), ("expect_shown", "F02.MFV"),
                       ("key", "left"), ("key", "left"), ("wait", 200), ("expect_shown", "F03.MFV"),
                       ("key", "menu"), ("wait", 900), ("expect_rec", True), ("expect", "View developed frames")])


def test_viewer_without_the_mfilm_chdk_build_says_so(card):
    _developed_on_card(card)
    run(card, [("stock_chdk",)] + ROLLS + [("key", "set"), ("key", "set"), ("expect", "M%-Film CHDK build"),
                                            ("expect_rec", True)])


def test_screen_test_from_diagnostics(card):
    assert (card / "A" / "CHDK" / "MFVIEW" / "TEST.MFV").read_bytes()[:4] == b"MFV1"   # from write_card
    run(card, [("wait", 1200)] + [("key", "down")] * 5 + [("key", "set"), ("expect", "SET: screen test"),
               ("key", "set"), ("wait", 600), ("expect_shown", "TEST.MFV"), ("expect", "Screen test  1/1"),
               ("key", "menu"), ("wait", 900), ("expect_rec", True)])


def test_canon_gallery_is_blocked_while_shooting(card):
    run(card, LOAD_PORTRA + LEN12 + [("wait", 600), ("canon_playback",), ("wait", 900), ("expect_rec", True),
                                     ("expect", "M%-Film 0%.")])
    assert "Canon playback blocked" in applog(card)


def _dev_files(card):
    d = card / "A" / "CHDK" / "MFDEV"
    d.mkdir(parents=True, exist_ok=True)
    (d / "MFCAM.BIN").write_bytes(b"MFCAM001")
    (d / "MFDEV.BIN").write_bytes(b"MFDEV001")


DEVELOP_LOADED = ROLLS + [("key", "set"), ("expect", "not developed yet"), ("key", "set"),
                          ("expect", "Finish it and develop it now"), ("key", "up"), ("key", "set")]


def test_develop_on_camera_then_view(card):
    _dev_files(card)
    run(card, LOAD_PORTRA + LEN12 + [("wait", 600)] + shots(2) + [("playback",), ("wait", 900)] + DEVELOP_LOADED
        + [("expect", "Frame 1/2"), ("wait", 4000), ("expect", "Frame 2/2"), ("wait", 4000),
           ("expect", "DEVELOPED: 2 frames %(camera%)"), ("key", "set"), ("wait", 600),
           ("expect_shown", "MFVIEW/C%w+/F01.MFV"), ("key", "right"), ("wait", 200), ("expect_shown", "F02.MFV"),
           ("key", "menu"), ("wait", 900), ("expect_rec", True)])
    (r,) = rolls(card)
    assert r["roll_state"] == "SEALED"
    idx = (card / "A" / "CHDK" / "MFVIEW" / "CAMINDEX.CFG").read_text()
    assert idx.startswith("roll=" + r["roll_id"] + "|portra400|") and "|2|C" in idx
    journal = next((card / "A" / "CHDK" / "MFILM" / "ROLLS").glob("*/JOURNAL.LOG")).read_text()
    assert "DEVELOPED frame 2 on camera" in journal and "DEVELOP on camera finished: 2 frames" in journal
    jpgs = sorted((card / "A" / "CHDK" / "MFDEV").glob("C*/F*.JPG"))
    assert [j.name for j in jpgs] == ["F01.JPG", "F02.JPG"]


def test_develop_can_be_stopped_and_keeps_the_roll_undeveloped(card):
    _dev_files(card)
    run(card, LOAD_PORTRA + LEN12 + [("wait", 600)] + shots(2) + [("playback",), ("wait", 900)] + DEVELOP_LOADED
        + [("expect", "Frame 1/2"), ("key", "menu"), ("wait", 1000), ("expect", "Developing stopped")])
    assert not (card / "A" / "CHDK" / "MFVIEW" / "CAMINDEX.CFG").exists()


def test_develop_without_data_files_says_so(card):
    run(card, LOAD_PORTRA + LEN12 + [("wait", 600)] + shots(1) + [("playback",), ("wait", 900)] + DEVELOP_LOADED
        + [("expect", "MFDEV/MFCAM.BIN or MFDEV.BIN")])


def test_crash_loop_guard_switches_autostart_off(card):
    # 2026-11-05: the camera rebooted in a loop; an autostart that dies before the
    # app is up must not be repeated at the next power-on
    run(card, [("wait", 6000), ("expect_autostart", 1),
               ("powercut",), ("boot",), ("wait", 6000), ("expect_autostart", 1),      # a clean start: kept
               ("powercut",), ("boot",), ("wait", 1000),                                # dies while starting
               ("powercut",), ("boot",), ("wait", 600), ("expect_autostart", 0),
               ("expect", "Last start failed: autostart is OFF")])
    assert "previous start did not finish" in applog(card)


def test_both_overlay_buffers_hold_the_menu_before_any_flip(card):
    # 0.4.2 still flickered now and then: the flipped-to buffer was repainted
    # only after the flip. Now every paint is mirrored into the other buffer.
    log = card / "draw.log"
    run(card, [("wait", 1500), ("key", "down"), ("wait", 200), ("expect_screen_full",), ("flip",),
               ("expect_screen_full",), ("key", "down"), ("wait", 200), ("expect_screen_full",)],
        env={**os.environ, "MFILM_DRAWLOG": str(log)})


def test_watcher_does_not_stat_a_big_folder_all_the_time(card):
    # a folder with 400 DNGs: polling every DNG every 100-200 ms would hit the
    # card hundreds of times a second while the camera writes its own files
    d = card / "A" / "DCIM" / "101___01"
    d.mkdir(parents=True)
    for k in range(400):
        (d / f"CRW_{k:04d}.DNG").write_bytes(b"II*\0" + bytes(100))
    p = run(card, LOAD_PORTRA + LEN12 + [("wait", 600)] + shots(2) + [("wait", 60000)])
    m = __import__("re").search(r"card: (\d+) stat, (\d+) listdir in (\d+) s", p.stdout)
    stats, listdirs, secs = int(m[1]), int(m[2]), int(m[3])
    assert stats < 400 * 6 + 2000, (stats, listdirs, secs)      # a few full checks, not one per poll
    (r,) = rolls(card)
    assert r["captured_frames"] == 2


def test_developing_screen_redraws_only_what_changes(card):
    # camera 0.5.1: the whole contact strip flickered with the pulsing current
    # frame (filled black, then redrawn at every pulse)
    _dev_files(card)
    run(card, LOAD_PORTRA + LEN12 + [("wait", 600)] + shots(3) + [("playback",), ("wait", 900)] + DEVELOP_LOADED
        + [("expect", "Frame 1/3"), ("wait", 8000), ("expect_no_ghosts", 40)])


OSD_IDS = REPO / "src" / "camera" / "test" / "chdk-1.6.1-r6355-osd-conf-ids.txt"


def test_chdk_osd_clutter_switched_off(card):
    ids = {n: int(i) for n, i in (ln.split() for ln in OSD_IDS.read_text().splitlines()
                                  if ln and not ln.startswith("#"))}
    run(card, [("wait", 1200), ("expect_conf", ids["batt_icon_show"], 1)] + [("expect_conf", ids[n], 0) for n in
                                  ("batt_perc_show", "show_clock", "show_temp", "show_remaining_raw",
                                   "show_raw_state", "space_mb_show", "space_bar_show", "splash_show")])


def test_app_conf_ids_match_chdk_161():
    ids = {n: int(i) for n, i in (ln.split() for ln in OSD_IDS.read_text().splitlines()
                                  if ln and not ln.startswith("#"))}
    src = (APP / "MFILM.LUA").read_text()
    table = dict(re.findall(r"(\w+) = (\d{4})", src[src.index("local CONF = {"):src.index("local CONF_SHOW_OSD")]))
    assert {k: int(v) for k, v in table.items()} == ids


def test_fuzz_walks_all_screens_without_flicker():
    # tools/fuzz_camera_app.py: random walks with Canon flipping/erasing the
    # overlay, power cuts, developing and the viewer (a few seeds here; run the
    # tool for hundreds)
    import sys as _sys
    _sys.path.insert(0, str(REPO / "tools"))
    import fuzz_camera_app as fz
    for seed in (101, 202, 303):
        r = fz.run_one((seed, 120, None))
        assert not r["problems"], (seed, r["problems"], r["log"][-600:])
        assert r.get("flip", 0) == 0
