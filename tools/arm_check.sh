#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Cross-compile the film core for the SX510 HS CPU (DIGIC 4+: ARM946E-S,
# armv5te, no FPU) with the toolchain CHDK supports (GCC 4/5/8-11).
#   tools/arm_check.sh --install   fetch + verify the pinned toolchain into ~/.local/opt
#   tools/arm_check.sh             compile, report size and soft-float/libm symbols
# Exit 1 if the camera tier (mf_fx + seed + sha256) needs anything a CHDK module
# cannot call: floating point, libm, or libgcc helpers CHDK does not export.
set -eu
VER=10.3-2021.10
NAME=gcc-arm-none-eabi-$VER
URL=https://developer.arm.com/-/media/Files/downloads/gnu-rm/$VER/$NAME-x86_64-linux.tar.bz2
SHA256=97dbb4f019ad1650b732faffcc881689cedc14e2b7ee863d390e0a41ef16c9a3   # MD5 2383e4eb4ea23f248d33adc70dc3227e as published by Arm
OPT=${MFILM_ARM_OPT:-$HOME/.local/opt}
T=$OPT/$NAME/bin
root=$(cd "$(dirname "$0")/.." && pwd)

if [ "${1:-}" = "--install" ]; then
  mkdir -p "$OPT/dl"
  f=$OPT/dl/$NAME-x86_64-linux.tar.bz2
  [ -f "$f" ] || curl -fsSL -o "$f" "$URL"
  echo "$SHA256  $f" | sha256sum -c -
  tar -C "$OPT" -xjf "$f"
  "$T/arm-none-eabi-gcc" --version | head -1
  exit 0
fi

[ -x "$T/arm-none-eabi-gcc" ] || { echo "no toolchain: tools/arm_check.sh --install" >&2; exit 2; }
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
# the camera tier: everything the fixed-point stage links against
srcs=${MFILM_ARM_SOURCES:-"$root/src/shared/film_core/src/mf_fx.c $root/src/shared/film_core/src/mf_seed.c $root/src/shared/film_core/src/mf_sha256.c"}
# CHDK's DIGIC 4 flags (arm_rules.inc: ARM mode, not thumb) for a module
for f in $srcs; do
  "$T/arm-none-eabi-gcc" -c -marm -mtune=arm946e-s -march=armv5te -Os -fno-inline -fno-strict-aliasing \
    -fno-schedule-insns2 -std=gnu99 -Wall -Wextra -Werror -Wdouble-promotion -ffp-contract=off -fno-common \
    -I"$root/src/shared/film_core/include" "$f" -o "$out/$(basename "$f" .c).o"
done
"$T/arm-none-eabi-size" -t "$out"/*.o | tail -1
defined=$("$T/arm-none-eabi-nm" --defined-only "$out"/*.o | awk 'NF==3{print $3}' | sort -u)
undef=$("$T/arm-none-eabi-nm" -u "$out"/*.o | awk '{print $2}' | sort -u | grep -vxF "$defined" || true)
# what a CHDK module may call: the libgcc helpers in modules/module_exportlist.inc
# minus floating point (no FPU, and the camera stage must not need it), plus libc
exports="$root/vendor/chdk-trunk/modules/module_exportlist.inc"
if [ -f "$exports" ]; then
  allowed=$(grep -oE '__[a-z0-9_]+' "$exports" | grep -vE '__aeabi_([fd]|[ui]?2[fd]|[fd]2)' )
else
  allowed="__aeabi_uidiv __aeabi_idiv __aeabi_uidivmod __aeabi_idivmod __bswapsi2"
fi
# libc and CHDK functions the core exports to modules (modules/module_exportlist.c)
core_exports="$root/vendor/chdk-trunk/modules/module_exportlist.c"
if [ -f "$core_exports" ]; then
  # one bare identifier per line; floating-point libm is excluded on purpose
  allowed="$allowed $(grep -E '^[[:space:]]+[A-Za-z_][A-Za-z0-9_]*[[:space:]]*$' "$core_exports" | tr -d ' \t' |
                      grep -vxE '(sqrt|log|log2|log10|exp|pow|sin|cos|tan|atan|atan2|asin|acos|floor|ceil|fmod|fabs)f?' | tr '\n' ' ')"
else
  allowed="$allowed memcpy memset strlen"
fi
bad=$(echo "$undef" | grep -v '^$' | grep -vxF "$(echo "$allowed" | tr ' ' '\n')" || true)
echo "external symbols: $(echo $undef)"
if [ -n "$bad" ]; then
  echo "not available to a CHDK module on a camera without FPU: $(echo $bad)"
  exit 1
fi
echo "camera tier: OK (integer-only, links as a CHDK module)"
