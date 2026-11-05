#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Build CHDK release-1_6 r6355 (the version on the camera) for the SX510 HS
# 1.01A with the M-Film Lua functions (src/camera/chdk/mfilm_lua.c), into a
# card tree build/chdk16-card/ (DISKBOOT.BIN + CHDK/MODULES etc.).
#   source: build/chdk-1.6-src, exported by deploy/chdkptp/fetch_svn.py
#   (see docs/audit/P04-camera-alpha.md); never modified, copied to build/chdk16.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
T=$HOME/.local/opt/gcc-arm-none-eabi-10.3-2021.10/bin
[ -x "$T/arm-none-eabi-gcc" ] || { echo "no toolchain: tools/arm_check.sh --install" >&2; exit 2; }
export PATH=$T:$PATH
src=$root/build/chdk-1.6-src b=$root/build/chdk16 card=$root/build/chdk16-card
[ -f "$src/Makefile" ] || { echo "build/chdk-1.6-src missing" >&2; exit 2; }
rm -rf "$b" && cp -a "$src" "$b" && mkdir -p "$b/bin"
lua=$b/modules/luascript.c
grep -q "^static const luaL_Reg chdk_funcs\[\] = {" "$lua" || { echo "luascript.c layout changed" >&2; exit 1; }
sed -i "s|^static const luaL_Reg chdk_funcs\[\] = {|#include \"$root/src/camera/chdk/mfilm_lua.c\"\n\n&|" "$lua"
sed -i "s|^    FUNC(peek)$|    FUNC(peek)\n    FUNC(mf_viewport)\n    FUNC(mf_show)\n    FUNC(mf_overlay_clear)\n    FUNC(mf_dev_start)\n    FUNC(mf_dev_status)\n    FUNC(mf_dev_cancel)|" "$lua"
grep -q "FUNC(mf_show)" "$lua" || { echo "patch failed" >&2; exit 1; }
# keep the Lua module loaded while the developer task runs
n=$(grep -c "^         0, 0, 0, 0, 0$" "$lua")
[ "$n" = 1 ] || { echo "luascript.c: _liblua base not found" >&2; exit 1; }
sed -i "s|^         0, 0, 0, 0, 0$|         0, 0, mf_can_unload, 0, 0|" "$lua"
ln -sf "$root/src/camera/chdk/makefile_usermodules.inc" "$b/modules/makefile_usermodules.inc"
make -C "$b" -s PLATFORM=sx510hs PLATFORMSUB=101a BUILD_SVNREV=6355 MF_ROOT="$root" fir >"$root/build/chdk16-build.log" 2>&1 \
  || { grep -i -B2 -A6 "error" "$root/build/chdk16-build.log" | head -40; exit 1; }
rm -rf "$card" && mkdir -p "$card"
cp "$b/bin/DISKBOOT.BIN" "$card/"
mkdir -p "$card/CHDK" && cp -r "$b/CHDK/MODULES" "$card/CHDK/MODULES"
(cd "$card" && find . -type f | sort | xargs sha256sum > "$root/build/chdk16-card.sha256")
echo "card tree: $card ($(find "$card" -type f | wc -l) files); DISKBOOT.BIN $(sha256sum "$card/DISKBOOT.BIN" | cut -c1-16)"
