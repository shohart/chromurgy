# Camera alpha 0.1.0: roll capture app, card import, USB/Wi-Fi sync (2026-11-04)

What a first camera session must confirm. Everything below is tested on the
host; items marked HARDWARE-TEST REQUIRED have not run on the SX510 HS yet.

## Pieces

| piece | where | host evidence |
|---|---|---|
| roll app (menu, film choice, 12/24/36, frame counter overlay, finish roll, rolls list, diagnostics, quit) | `src/camera/app/MFILM.LUA` | `tests/test_camera_app.py`: 7 scenarios in CHDK's own integer host Lua |
| roll model, atomic state/manifest with recovery, journal, DNG watcher, first-run self-test | `src/camera/app/mfroll.lua` | same |
| CHDK 1.6.1 API check | `src/camera/test/chdk-1.6.1-r6355-lua-functions.txt` (from release-1_6 r6355 `luascript.c`) | static `luac -l` global check |
| card files | `mfilmctl camera-card OUT` | config carries the server's bundle hash and 72 films |
| hashless card import (camera does not hash; receiver hashes the staged copy) | `importer.py`, schema `if WRITTEN` | `test_importer.py` |
| camera-sync over chdkptp, USB or PTP/IP | `camera_sync.py`, `deploy/chdkptp` | `test_camera_sync.py` with a fake chdkptp |
| UPnP responder for the Canon "Connect to computer" flow | `deploy/systemd/user/mfilm-upnp.service` | running on octopusreborn (192.168.1.123, name "mfilm") |

## Facts the design relies on, settled from CHDK source (release-1_6 r6355)

- A script keeps running after `exit_alt()`: `kbd_process` calls
  `action_stack_process_all()` regardless of ALT, and keys go to the camera.
  Short Playback re-enters ALT with the script still running (its menu).
- `hook_raw.count()` increments on every shot even when the hook is not set,
  so shots are counted without blocking the capture task.
- `sleep`/`wait_click` yield the script coroutine: no `pcall` around code that
  waits (Lua 5.1 cannot yield across pcall). The harness yields the same way.
- CHDK Lua numbers are integers.
- 1.6.1 lacks only `get_focal_length`, `get_eff_focal_length`, `screen_needs_refresh`
  compared to trunk; the app uses none of them.

## HARDWARE-TEST REQUIRED (logged by the app's self-test to CHDK/MFILM/LOGS/app.log)

- `os.rename` over an existing file and `io.open(..., "a")` on DryOS FAT (fallbacks exist).
- `exit_alt()` from a script returns full camera control and the overlay stays visible.
- `hook_raw.count()` increments for user-initiated shots on this port.
- Frame detection timing (DNG complete ~0.13 s after shoot() returned in the probe).
- USB: chdkptp lists/downloads from the camera (`mfilmctl camera-sync --usb`).
- Wi-Fi: SX510 HS Wi-Fi menu offers "Computer", pairs with "mfilm", and chdkptp
  connects by PTP/IP and downloads files. Reported working on Elph130, SX280 and
  later models (chdkptp README-WIFI-PTPIP.TXT); not reported for the SX510 HS.

## Known limitations of the alpha

- Canon JPEGs stay in DCIM and in Canon playback; no preview hiding.
- Frames shot while the app is not running are not on any roll.
- No offline development on the camera yet (core is ready and bit-exact; DNG
  reader, reduction, JPEG encoder still to do).
- Wi-Fi sync is started from the server (`mfilmctl camera-sync --host IP`), not
  automatically when the camera connects.
