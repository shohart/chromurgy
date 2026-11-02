#!/usr/bin/env bash
# Fetch upstream sources into vendor/ at the revisions pinned in LOCKFILE.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$root/vendor"
grep -vE '^\s*(#|$)' "$root/LOCKFILE" | while read -r name url commit _; do
  dst="$root/vendor/$name"
  if [ ! -d "$dst/.git" ]; then
    git init -q "$dst"
    git -C "$dst" remote add origin "$url"
  fi
  git -C "$dst" fetch -q --depth 1 origin "$commit"
  git -C "$dst" checkout -q --detach "$commit"
  echo "$name @ $(git -C "$dst" rev-parse HEAD)"
done
