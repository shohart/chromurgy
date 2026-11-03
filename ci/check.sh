#!/usr/bin/env bash
# Host CI (docs/13 level 1): C film core + server tests. Run from anywhere.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cmake -S "$root" -B "$root/build" >/dev/null
cmake --build "$root/build" -j"$(nproc)"
ctest --test-dir "$root/build" --output-on-failure
# camera tier links as a CHDK module (integer-only); needs tools/arm_check.sh --install
if "$root/tools/arm_check.sh" >/tmp/mfilm-arm-check.$$ 2>&1; then tail -1 /tmp/mfilm-arm-check.$$
else rc=$?; cat /tmp/mfilm-arm-check.$$; rm -f /tmp/mfilm-arm-check.$$; [ $rc -eq 2 ] || exit 1; fi
rm -f /tmp/mfilm-arm-check.$$
cd "$root/src/server"
[ -x .venv/bin/pytest ] || { uv venv -q .venv && uv pip install -q -e '.[test,tools]' --python .venv/bin/python; }
# parity evidence against upstream M-Film (needs scripts/fetch-upstream.sh)
sim="$root/vendor/m-film/ml-dev/filmos/sim"
if [ -d "$sim" ]; then
  make -s -C "$sim" out/devtest >/dev/null
  (cd "$sim" && ./out/devtest ../../films/sample/SAMPLE.CR2 out/sample.FOP out/sample.ppm 2>/dev/null)
  "$root/tools/check_upstream_tables.sh" | tail -1
else
  echo "vendor/ missing: upstream parity tests will be skipped (run scripts/fetch-upstream.sh)"
fi
.venv/bin/pytest -q -rs
