#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Wi-Fi auto-sync: when the camera connects to "mfilm" (Canon Wi-Fi menu ->
# Computer), it fetches the UPnP description from mfilm-upnp; that is the
# moment to connect, because the SX510 HS accepts one PTP/IP session per
# Canon connect. Then: mfilmctl camera-sync --host <camera> --run.
set -u
export PATH=$HOME/.local/bin:$PATH
repo=$(cd "$(dirname "$0")/.." && pwd)
last=0
journalctl --user -u mfilm-upnp -f -n 0 --no-pager | while read -r line; do
  case "$line" in
    *"GET /ptpip-canon-desc-helper.xml"*)
      ip=$(echo "$line" | grep -oE "([0-9]{1,3}\.){3}[0-9]{1,3} - -" | cut -d" " -f1)
      now=$(date +%s)
      [ -n "$ip" ] && [ $((now - last)) -gt 60 ] || continue
      last=$now
      echo "camera $ip connected: syncing"
      sleep 1
      timeout 3600 "$repo/src/server/.venv/bin/mfilmctl" camera-sync --host "$ip" --run
      echo "sync finished: rc=$?";;
  esac
done
