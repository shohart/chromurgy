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
sed -i "s|^    FUNC(peek)$|    FUNC(peek)\n    FUNC(mf_viewport)\n    FUNC(mf_show)\n    FUNC(mf_overlay_clear)\n    FUNC(mf_overlay_mirror)\n    FUNC(mf_dev_start)\n    FUNC(mf_dev_status)\n    FUNC(mf_dev_cancel)\n    FUNC(mf_chdk_alt)|" "$lua"
grep -q "FUNC(mf_show)" "$lua" || { echo "patch failed" >&2; exit 1; }
# NOTE: do not touch _liblua's can_unload. CHDK calls can_unload on EVERY tick
# and unloads the module as soon as it returns true (module_tick_unloader);
# 0.4.0 put a function there and the Lua module was unloaded under the
# running script -> crash in PhySw at every autostart (ROMLOG 2026-11-05).
grep -q "mf_can_unload" "$lua" && { echo "can_unload must stay 0" >&2; exit 1; }
ln -sf "$root/src/camera/chdk/makefile_usermodules.inc" "$b/modules/makefile_usermodules.inc"
make -C "$b" -s PLATFORM=sx510hs PLATFORMSUB=101a BUILD_SVNREV=6355 MF_ROOT="$root" fir >"$root/build/chdk16-build.log" 2>&1 \
  || { grep -i -B2 -A6 "error" "$root/build/chdk16-build.log" | head -40; exit 1; }
# The card gets the OFFICIAL CHDK build (DISKBOOT.BIN = the core, and its
# modules) with only lua.flt replaced by ours. A core built here with GCC 10
# was never proven on the camera, and the 2026-11-05 card with our own
# DISKBOOT.BIN rebooted in a loop; modules from these same sources load on
# the official core (MFBENCH.FLT did, 2026-11-04): same architecture flag and
# interface versions.
OFFICIAL_URL=https://mighty-hoernsche.de/bins/sx510hs-101a-1.6.1-6355-full_ALPHA.zip
OFFICIAL_SHA=485f464c92025aaffa7aa9f85f4f4c0ff20c377f21fdb7f004a34596878d7cb6
off=$root/build/chdk-official
mkdir -p "$off"
[ -f "$off/full.zip" ] || curl -sfL --max-time 300 -o "$off/full.zip" "$OFFICIAL_URL"
echo "$OFFICIAL_SHA  $off/full.zip" | sha256sum -c --quiet - || { echo "official CHDK zip: hash mismatch" >&2; exit 1; }
rm -rf "$off/x" && mkdir -p "$off/x" && (cd "$off/x" && unzip -q ../full.zip)
rm -rf "$card" && mkdir -p "$card/CHDK"
cp "$off/x/DISKBOOT.BIN" "$card/"
cp -r "$off/x/CHDK/MODULES" "$card/CHDK/MODULES"
cp "$b/CHDK/MODULES/lua.flt" "$card/CHDK/MODULES/lua.flt"
(cd "$card" && find . -type f | sort | xargs sha256sum > "$root/build/chdk16-card.sha256")
echo "card tree: $card ($(find "$card" -type f | wc -l) files); DISKBOOT.BIN $(sha256sum "$card/DISKBOOT.BIN" | cut -c1-16)"
