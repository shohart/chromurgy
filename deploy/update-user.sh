#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Update a per-user deployment (deploy/README.md) from a git bundle, safely:
# a film-core change changes every new render_id, so only update with an
# empty queue.   usage: deploy/update-user.sh /tmp/mfilm.bundle [--force]
set -eu
bundle=$1
force=${2:-}
repo=$(cd "$(dirname "$0")/.." && pwd)
ctl="$repo/src/server/.venv/bin/mfilmctl"
export MFILM_CONFIG=${MFILM_CONFIG:-$HOME/.config/mfilm/config.toml}
export PATH=$HOME/.local/bin:$PATH
systemctl --user stop mfilm-worker
busy=$("$repo/src/server/.venv/bin/python" -I -c '
import sqlite3, sys
from mfilm_server import config
c = sqlite3.connect(config.load(None).data_dir / "db" / "mfilm.sqlite3")
print(c.execute("SELECT COUNT(*) FROM jobs WHERE state IN (\"QUEUED\",\"RUNNING\")").fetchone()[0])')
if [ "$busy" != 0 ] && [ "$force" != --force ]; then
  echo "$busy job(s) queued/running: finish them first (mfilmctl worker), or pass --force" >&2
  systemctl --user start mfilm-worker
  exit 1
fi
git -C "$repo" pull -q "$bundle" main
cmake --build "$repo/build" -j"$(nproc)" >/dev/null
(cd "$repo/src/server" && uv pip install -q -e . --python .venv/bin/python)
"$ctl" init
systemctl --user start mfilm-worker
git -C "$repo" log --oneline -1
