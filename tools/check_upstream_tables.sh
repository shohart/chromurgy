#!/usr/bin/env bash
# Parity: every LUT film table in profiles/mfilm-films.bin against the
# uint8 LOOKnn.LUT that upstream M-Film's genfilms.py bakes from the same LUT.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
py="$root/src/server/.venv/bin/python"
films="$root/vendor/m-film/ml-dev/films"
out="$root/build/upstream-tables"
rm -rf "$out"; mkdir -p "$out"
# upstream fetcher, fed from the pinned Film-Luts checkout (writes only under vendor/)
(cd "$films" && "$py" -E -s getluts.py --from "$root/vendor/film-luts" >/dev/null)
(cd "$root/vendor/m-film/ml-dev/filmos/tools" && "$py" -E -s genfilms.py "$out/FOSFILMS.BIN" --tables "$out")
"$py" -I "$root/tools/compare_tables.py" "$root/profiles/mfilm-films.bin" "$out" \
  "$root/vendor/m-film/ml-dev/filmos/fos_film.c"
