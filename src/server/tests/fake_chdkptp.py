# SPDX-License-Identifier: GPL-2.0-only
"""Stand-in for chdkptp in tests: understands the -e commands camera_sync
issues (connect, mdl -overwrite=y SRC DST, d SRC DST) against a card
directory. mdl semantics follow chdkptp's chdku.mdownload: the contents of
SRC go into DST."""
import shlex
import shutil
import sys
from pathlib import Path

args = sys.argv[1:]
card = Path(args[args.index("--card") + 1])
offline = "--offline" in args
connected = False
lines = [a[2:] for a in args if a.startswith("-e")]
if "-i" in args:                       # interactive: commands on stdin, like chdkptp -i
    lines = (ln.rstrip("\n") for ln in sys.stdin)
for line in lines:
    if line.startswith("!print("):
        print(line[len("!print('"):-2], flush=True)
        continue
    words = shlex.split(line)
    if not words:
        continue
    if words[0] in ("dis", "quit"):
        if words[0] == "quit":
            break
        continue
    if words[0] == "killscript":
        continue
    if words[0] in ("connect", "c"):
        if offline:
            print("ERROR: connection failed", flush=True)
            continue
        connected = True
        print("connected: Canon PowerShot SX510 HS")
        continue
    if not connected:
        print("ERROR: not connected", flush=True)
        continue
    if words[0] == "mdl":
        src, dst = Path(card / words[-2][2:]), Path(words[-1])
        for f in src.rglob("*"):
            if f.is_file():
                out = dst / f.relative_to(src)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, out)
    elif words[0] == "d":
        shutil.copyfile(card / words[1][2:], words[2])
    else:
        print(f"unknown command {words[0]}")
        sys.exit(1)
