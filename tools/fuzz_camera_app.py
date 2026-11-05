#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Random walks through the camera app in the host harness (the camera model:
two overlay buffers, Canon flipping/erasing them, CHDK splash, power cuts,
DCIM, the developer with the camera's heap).

    tools/fuzz_camera_app.py [--runs N] [--steps N] [--seed S] [--jobs J] [--keep DIR]

Every run must end without an app error, with no flicker caused by buffer
flips, erase glitches shorter than a key poll, and roll manifests that pass
the server's schema. Failing scenarios are kept for replay (harness.lua)."""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "server"))
LUA = REPO / "build" / "hostlua" / "lua"
HARNESS = REPO / "src" / "camera" / "test" / "harness.lua"
APP = REPO / "src" / "camera" / "app"

KEYS = ["up", "down", "up", "down", "set", "set", "menu", "left", "right", "shoot_half", "display", "zoom_in"]
MAX_GHOST_PX = 40           # pixels a pass may set and set back (a redraw over itself that flashes)
MAX_ERASE_MS = 260          # an erase is visible until the next poll: 60 ms in menus, 200 ms while developing


def lua_val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, dict):
        return "{" + ",".join(f"{k}={lua_val(x)}" for k, x in v.items()) + "}"
    return json.dumps(v)


def K(*keys, w=150):
    out = []
    for k in keys:
        out += [("key", k), ("wait", w)]
    return out


# back out of any submenu (MENU in the main menu returns to shooting), then a
# fresh main menu with the cursor on its first item
TO_MENU = [("open_menu",), ("wait", 900)] + [x for _ in range(5) for x in (("key", "menu"), ("wait", 300),
                                                                         ("open_menu",), ("wait", 300))] \
    + [("key", "menu"), ("wait", 600), ("open_menu",), ("wait", 900)]
MACROS = {
    "load_film": lambda rng: TO_MENU + K("down", "set") + K(*(["down"] * rng.randrange(0, 8)), "set")
    + K(*(["down"] * rng.randrange(0, 3)), "set") + [("wait", 900)],
    "shoot_some": lambda rng: [x for _ in range(rng.randrange(1, 5)) for x in (("shoot", {}), ("wait", 700))],
    "to_menu": lambda rng: [("playback",), ("wait", 900)] + TO_MENU,
    "rolls_develop": lambda rng: TO_MENU + K("down", "down", "down", "set") + K(*(["down"] * rng.randrange(0, 3)), "set")
    + K("set") + K(rng.choice(["set", "up"]), "set") + [("wait", rng.choice([1000, 4000, 9000]))],
    "develop_stop": lambda rng: TO_MENU + K("down", "down", "down", "set", "set", "set", "up", "set") + [("wait", 1500)]
    + K("menu") + [("wait", 1500)],
    "view": lambda rng: TO_MENU + K("down", "down", "down", "set", "set", "set") + [("wait", 900)]
    + K(*[rng.choice(["right", "left", "set", "down"]) for _ in range(rng.randrange(1, 6))]) + K("menu") + [("wait", 900)],
    "screen_test": lambda rng: TO_MENU + K("down", "down", "down", "down", "down", "set", "set") + [("wait", 900)]
    + K("menu") + [("wait", 900)],
    "finish_roll": lambda rng: TO_MENU + K("down", "down", "set", "up", "set") + [("wait", 600)],
}


def scenario(rng: random.Random, n: int) -> list:
    st = [("fuzz",), ("chaos", rng.randrange(1, 2 ** 30), rng.choice([0, 1, 3, 8]), rng.choice([0, 0, 1, 2])), ("wait", 1500)]
    st += MACROS["load_film"](rng) + MACROS["shoot_some"](rng)
    for _ in range(n):
        r = rng.random()
        if r < 0.25:
            st += MACROS[rng.choice(sorted(MACROS))](rng)
            continue
        r = rng.random()
        if r < 0.62:
            st.append(("key", rng.choice(KEYS)))
            if rng.random() < 0.3:
                st.append(("wait", rng.choice([50, 200, 700])))
        elif r < 0.72:
            st.append(("playback",))
            st.append(("wait", 900))
        elif r < 0.84:
            st.append(("shoot", {"lag": rng.random() < 0.1}))
            st.append(("wait", 700))
        elif r < 0.90:
            st.append(("wait", rng.choice([1000, 3000, 7000])))
        elif r < 0.93:
            st.append(("heap", rng.choice([968000, 500000]), rng.choice([964000, 320000, 120000])))
        elif r < 0.95:
            st.append(("canon_playback",))
            st.append(("wait", 900))
        elif r < 0.965:
            st.append(("setdir", f"A/DCIM/{rng.randrange(102, 130)}___11"))
        elif r < 0.98:
            st.append(("vbatt", rng.choice([3950, 3950, 3700, 3550, 3480, 3420, 3340])))
        else:
            st += [("powercut",), (rng.choice(["boot", "boot", "boot_playback"]),), ("wait", 1500)]
    return st


def run_one(args) -> dict:
    seed, steps, keep = args
    rng = random.Random(seed)
    from mfilm_server.camera_card import write_card
    with tempfile.TemporaryDirectory(prefix="mffuzz") as td:
        root = Path(td)
        (root / "A").mkdir()
        write_card(root / "A", utc_offset="+02:00")
        dev = root / "A" / "CHDK" / "MFDEV"
        dev.mkdir(parents=True, exist_ok=True)
        (dev / "MFCAM.BIN").write_bytes(b"MFCAM001")
        (dev / "MFDEV.BIN").write_bytes(b"MFDEV001")
        shutil.copytree(root / "A", root / "A.start")          # for replay: the card as the run found it
        st = scenario(rng, steps)
        scen = root / "scenario.lua"
        scen.write_text("return {\n" + ",\n".join("{" + ",".join(lua_val(x) for x in s) + "}" for s in st) + "\n}\n")
        p = subprocess.run([str(LUA), str(HARNESS), str(APP), str(scen)], cwd=root, capture_output=True, text=True,
                           timeout=600, check=False)
        out = {"seed": seed, "rc": p.returncode, "log": (p.stderr + p.stdout)[-1500:]}
        sm = re.search(r"^screens: (.*)$", p.stdout, re.MULTILINE)
        out["screens"] = sm[1] if sm else ""
        m = re.search(r"glitches: flip (\d+), erase (\d+), longest (\d+) ms", p.stdout)
        if m:
            out.update(flip=int(m[1]), erase=int(m[2]), longest=int(m[3]))
        gm = re.search(r"ghosts: (\d+) passes, max (\d+) px", p.stdout)
        if gm:
            out.update(ghost_passes=int(gm[1]), ghost_max=int(gm[2]))
        problems = []
        if gm and int(gm[2]) > MAX_GHOST_PX:
            problems.append(f"in-place redraw flashed {gm[2]} px ({gm[1]} passes)")
        if p.returncode != 0:
            problems.append("harness failed")
        if m and int(m[1]) > 0:
            problems.append(f"{m[1]} flip glitch(es)")
        if m and int(m[3]) > MAX_ERASE_MS:
            problems.append(f"glitch visible {m[3]} ms")
        problems += check_manifests(root / "A")
        out["problems"] = problems
        if problems and keep:
            dst = Path(keep) / f"seed{seed}"
            shutil.rmtree(dst, ignore_errors=True)
            dst.mkdir(parents=True)
            shutil.copytree(root / "A.start", dst / "A")         # replay: cd dst; lua harness.lua APP scenario.lua
            shutil.copyfile(scen, dst / "scenario.lua")
        return out


def check_manifests(card: Path) -> list:
    from mfilm_server.contracts import ManifestError, load_roll_manifest
    from mfilm_server.importer import find_manifests
    bad = []
    for m in find_manifests(card):
        try:
            doc = load_roll_manifest(m.read_bytes())
        except ManifestError as e:
            bad.append(f"{m.parent.name}: {str(e)[:200]}")
            continue
        frames = doc.get("frames", [])
        if len({f["source_path"] for f in frames}) != len(frames):
            bad.append(f"{m.parent.name}: a DNG recorded twice")
        if len(frames) > doc.get("roll_length", 0):
            bad.append(f"{m.parent.name}: more frames than the roll holds")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--steps", type=int, default=250)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--keep", help="copy failing runs (card + scenario) here")
    a = ap.parse_args()
    jobs = [(a.seed + i, a.steps, a.keep) for i in range(a.runs)]
    fails, totals, cover = [], {"flip": 0, "erase": 0, "longest": 0}, {}
    with ProcessPoolExecutor(a.jobs) as ex:
        for r in ex.map(run_one, jobs):
            for k in ("flip", "erase"):
                totals[k] += r.get(k, 0)
            totals["longest"] = max(totals["longest"], r.get("longest", 0))
            if r["problems"]:
                fails.append(r)
            for part in r.get("screens", "").split("; "):
                m2 = re.match(r"(viewer frames|developed) (\d+)$", part)
                key = (m2[1] + (" > 0" if int(m2[2]) else " = 0")) if m2 else re.sub(r"\d+", "N", part)
                cover[key] = cover.get(key, 0) + 1
    print(f"{a.runs} runs x {a.steps} steps: {len(fails)} failing; glitches flip {totals['flip']}, "
          f"erase {totals['erase']}, longest {totals['longest']} ms")
    print("coverage (runs reaching each screen):")
    for k in sorted(cover):
        print(f"  {cover[k]:4d}  {k}")
    for r in fails[:10]:
        print(f"--- seed {r['seed']}: {r['problems']}\n{r['log'][-700:]}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
