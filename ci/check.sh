#!/usr/bin/env bash
# Host CI (docs/13 level 1): C film core + server tests. Run from anywhere.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cmake -S "$root" -B "$root/build" >/dev/null
cmake --build "$root/build" -j"$(nproc)"
ctest --test-dir "$root/build" --output-on-failure
cd "$root/src/server"
[ -x .venv/bin/pytest ] || { uv venv -q .venv && uv pip install -q -e '.[test]' --python .venv/bin/python; }
.venv/bin/pytest -q
