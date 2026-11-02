#!/usr/bin/env bash
# Regenerate film-colour golden vectors from the pinned upstream M-Film.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
fos="$root/vendor/m-film/ml-dev/filmos"
[ -f "$fos/fos_dev.c" ] || { echo "run scripts/fetch-upstream.sh first" >&2; exit 1; }
out="$root/build/golden"; mkdir -p "$out"
# only fos_film_color() and the look table are needed; unused code (and its
# fos_port_* references) is dropped by section GC
cc -O2 -std=gnu99 -w -ffunction-sections -fdata-sections -Wl,--gc-sections \
  -I"$fos" -o "$out/golden_film_color" \
  "$root/tools/golden_film_color_main.c" "$fos/fos_dev.c" "$fos/fos_looks.c" -lm
"$out/golden_film_color" > "$root/src/shared/film_core/tests/golden_film_color.txt"
echo "upstream: $(git -C "$root/vendor/m-film" rev-parse HEAD)"
wc -l "$root/src/shared/film_core/tests/golden_film_color.txt"
