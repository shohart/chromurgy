#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Build CHDK for the SX510 HS (firmware 1.01A) from the pinned trunk in
# vendor/chdk-trunk, with the M-Film modules (src/camera), and lay out a card
# tree in build/chdk-card/ to copy to the SD card root.
#     tools/build_chdk.sh            (needs tools/arm_check.sh --install)
# The vendored tree is copied to build/chdk and never modified.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
T=$HOME/.local/opt/gcc-arm-none-eabi-10.3-2021.10/bin
[ -x "$T/arm-none-eabi-gcc" ] || { echo "no toolchain: tools/arm_check.sh --install" >&2; exit 2; }
export PATH=$T:$PATH
src=$root/vendor/chdk-trunk b=$root/build/chdk card=$root/build/chdk-card
[ -f "$src/Makefile" ] || { echo "vendor/chdk-trunk missing: scripts/fetch-upstream.sh" >&2; exit 2; }
rm -rf "$b" && mkdir -p "$root/build"
cp -a "$src" "$b" && rm -rf "$b/.git" && mkdir -p "$b/bin"
ln -sf "$root/src/camera/mfbench/makefile_usermodules.inc" "$b/modules/makefile_usermodules.inc"
rev=$(awk '$1=="chdk-trunk"{print substr($3,1,8)}' "$root/LOCKFILE")
make -C "$b" -s PLATFORM=sx510hs PLATFORMSUB=101a MF_ROOT="$root" BUILD_SVNREV="mfilm-$rev" fir >"$root/build/chdk-build.log" 2>&1 \
  || { tail -30 "$root/build/chdk-build.log"; exit 1; }
# CHDK's host Lua (integer numbers, camera os/io libs) for the app harness
make -C "$b/tools/hostlua" -s >>"$root/build/chdk-build.log" 2>&1
mkdir -p "$root/build/hostlua" && cp "$b/tools/hostlua/lua" "$b/tools/hostlua/luac" "$root/build/hostlua/"
cmake --build "$root/build" --target mfbench_gen >/dev/null
rm -rf "$card" && mkdir -p "$card"
cp "$b/bin/DISKBOOT.BIN" "$card/"
cp -r "$b/CHDK" "$card/CHDK" && rm -f "$card/CHDK/Makefile"
mkdir -p "$card/CHDK/DATA" "$card/CHDK/SCRIPTS"
"$root/build/src/shared/film_core/mfbench_gen" "$root/profiles/mfilm-films.bin" portra400 "$card/CHDK/DATA/MFBENCH.BIN"
cp "$root/src/camera/scripts/mfprobe.lua" "$card/CHDK/SCRIPTS/MFPROBE.LUA"
(cd "$card" && find . -type f | sort | xargs sha256sum > "$root/build/chdk-card.sha256")
echo "card tree: $card ($(find "$card" -type f | wc -l) files); DISKBOOT.BIN $(sha256sum "$card/DISKBOOT.BIN" | cut -c1-16)"
