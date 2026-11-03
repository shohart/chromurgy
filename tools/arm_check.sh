#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Cross-compile the film core for the SX510 HS CPU (DIGIC 4+: ARM946E-S,
# armv5te, no FPU) with the toolchain CHDK supports (GCC 4/5/8-11).
#   tools/arm_check.sh --install   fetch + verify the pinned toolchain into ~/.local/opt
#   tools/arm_check.sh             compile, report size and soft-float/libm symbols
# Exit 1 if any object needs floating point or libm: the camera variant must not.
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
srcs=${MFILM_ARM_SOURCES:-$(ls "$root"/src/shared/film_core/src/*.c)}
for f in $srcs; do
  "$T/arm-none-eabi-gcc" -c -Os -mtune=arm946e-s -march=armv5te -mthumb -std=gnu99 \
    -Wall -Wextra -Werror -Wdouble-promotion -ffp-contract=off -fno-common \
    -I"$root/src/shared/film_core/include" "$f" -o "$out/$(basename "$f" .c).o"
done
"$T/arm-none-eabi-size" -t "$out"/*.o | tail -1
fp=$("$T/arm-none-eabi-nm" -u "$out"/*.o | awk '{print $2}' | sort -u |
     grep -E '^__aeabi_(f|d|[if]2|[ul]?2[fd])|^(exp|log|pow|sin|cos|atan|ceil|floor|fmod|sqrt)' || true)
if [ -n "$fp" ]; then
  echo "needs floating point / libm on a camera without FPU:"
  echo "$fp" | tr '\n' ' '; echo
  exit 1
fi
echo "integer-only: OK"
