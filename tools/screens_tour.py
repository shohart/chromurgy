#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""A tour of every screen of the camera app in the host harness, rendered
with CHDK's font: tools/screens_tour.py OUT_DIR -> OUT_DIR/NN_name.png and
develop.gif (the developing screen, animated). For reviewing layouts."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src" / "server"))
sys.path.insert(0, str(REPO / "tools"))
import fuzz_camera_app as fz  # noqa: E402


def K(*keys, w=200):
    return [s for k in keys for s in (("key", k), ("wait", w))]


def main():
    out = Path(sys.argv[1])
    n = [0]

    def snap(name):
        n[0] += 1
        return ("snap", f"{n[0]:02d}_{name}")

    dev = [s for i in range(40) for s in (("wait", 250), ("snap", f"dev_{i:03d}"))]
    tour = ([("wait", 1500), snap("menu_no_film")] + K("down", "set") + [snap("choose_film")]
            + K("down", "down", "down") + [snap("choose_film_scrolled")] + K("set") + [snap("roll_length")]
            + K("down", "down", "set") + [("wait", 1200), snap("shooting_overlay")]
            + [x for _ in range(3) for x in (("shoot", {}), ("wait", 700))] + [snap("shooting_after_shot")]
            + [("open_menu",), ("wait", 900), snap("menu_with_film")]
            + K("down", "down", "down", "set") + [snap("rolls")] + K("set") + [snap("roll_card")]
            + K("set") + [snap("develop_confirm")] + K("up", "set") + dev
            + [("wait", 2000), snap("roll_card_developed")] + K("set") + [("wait", 900), snap("viewer")]
            + K("set") + [snap("viewer_no_caption")] + K("menu") + [("wait", 900)]
            + fz.TO_MENU + K("down", "down", "down", "down", "down", "set") + [snap("diagnostics")]
            + K("menu") + [("wait", 600)] + fz.TO_MENU
            + K("down", "down", "down", "down", "down", "down", "set") + [snap("quit_confirm")])
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "A").mkdir()
        from mfilm_server.camera_card import write_card
        write_card(root / "A", utc_offset="+02:00")
        d = root / "A" / "CHDK" / "MFDEV"
        d.mkdir(parents=True, exist_ok=True)
        (d / "MFCAM.BIN").write_bytes(b"MFCAM001")
        (d / "MFDEV.BIN").write_bytes(b"MFDEV001")
        scen = root / "s.lua"
        scen.write_text("return {\n" + ",\n".join("{" + ",".join(fz.lua_val(x) for x in s) + "}"
                                                for s in [("fuzz",)] + tour) + "\n}\n")
        log = root / "draw.log"
        p = subprocess.run([str(fz.LUA), str(fz.HARNESS), str(fz.APP), str(scen)], cwd=root, capture_output=True,
                           text=True, env={"MFILM_DRAWLOG": str(log), "PATH": "/usr/bin:/bin"}, check=False)
        print(p.stdout.strip()[:300], p.stderr.strip()[-600:])
        shutil.rmtree(out, ignore_errors=True)
        subprocess.run([sys.executable, str(REPO / "tools" / "render_screens.py"), str(log), str(out),
                        "--gif", "develop:dev_"], check=True)


if __name__ == "__main__":
    main()
