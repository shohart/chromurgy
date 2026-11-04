#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Build CHDK's host Lua (integer numbers, the camera's os/io libraries) into
# build/hostlua/{lua,luac} from vendor/chdk-trunk, for the camera app harness
# (src/camera/test). Needs only a host C compiler and make.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
src=$root/vendor/chdk-trunk b=$root/build/chdk-host
[ -f "$src/Makefile" ] || { echo "vendor/chdk-trunk missing: scripts/fetch-upstream.sh" >&2; exit 2; }
rm -rf "$b" && mkdir -p "$root/build" && cp -a "$src" "$b" && rm -rf "$b/.git"
make -C "$b/tools/hostlua" -s >"$root/build/hostlua-build.log" 2>&1 || { tail -20 "$root/build/hostlua-build.log"; exit 1; }
mkdir -p "$root/build/hostlua" && cp "$b/tools/hostlua/lua" "$b/tools/hostlua/luac" "$root/build/hostlua/"
rm -rf "$b"
echo "build/hostlua/lua: $("$root/build/hostlua/lua" -v 2>&1 | head -1)"
