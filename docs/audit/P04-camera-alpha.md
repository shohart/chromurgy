# Camera alpha 0.1.x: roll capture app, card import, USB/Wi-Fi sync (2026-11-04)

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

## First camera session (2026-11-04, 0.1.0) and fixes in 0.1.1

VERIFIED on the camera (self-test in the app log): all Lua functions present,
`hook_raw` present, append mode works, RAW on, screen 360x240, image dir
`A/DCIM/127___11`. `os.rename` over an existing file is **refused**.

Failures:
- Menu flickered over the live view: full-screen fill + redraw every 250 ms.
  0.1.1 redraws only on change (or every 3 s), pads lines instead of filling,
  keeps off CHDK's bottom bar.
- "Load film" powered the camera off. ROMLOG: `ASSERT!! DriveLetterManager.c
  Line 105`, task PhySw (the script task), camera in playback. The roll
  directory had only `state.cfg.tmp`: it died in write-tmp -> stat -> rename
  inside a long-named (UUID) directory; `mkdirs` also stat-ed the bare drive "A".
  0.1.1: 8.3 upper-case names only (roll dirs = 8 hex digits, MANIFEST.JSN,
  STATE_A|B.CFG, JOURNAL.LOG, APP.LOG), no rename anywhere (state in two
  alternating copies with a generation marker; manifest rewritten from state on
  every start), no path without "A/". The importer finds MANIFEST.JSN and the
  CHDK/MFILM/ROLLS path case-insensitively. The harness now fails on rename,
  non-8.3 or lower-case created names and bare-drive paths; 0.1.0 fails it.

## Second session (2026-11-04, 0.1.1 -> 0.1.2): first roll end to end over Wi-Fi

VERIFIED:
- 0.1.1 loaded a roll, recorded 12 frames, sealed it (no power-off).
- Wi-Fi: SX510 HS menu "Computer" paired with the mfilm-upnp responder
  (camera 192.168.1.157 fetched the UPnP description), chdkptp connected by
  PTP/IP ("connected: Canon PowerShot SX510 HS"), `mfilmctl camera-sync`
  downloaded the manifest and 12 DNGs, imported, developed and published
  12/12 to PhotoPrism (`M-Film/2026-11-04_Portra400_160b4e21`), lens-corrected.
- The camera accepts one PTP/IP session per Canon connect: a second connect
  after a disconnect times out. Sync now runs in one interactive chdkptp
  session; deploy/camera-watch.sh (+ user unit mfilm-camera-watch) starts it
  the moment the camera fetches the description.
- A running camera script blocks chdkptp ("a script is already running"):
  the sync runs `killscript` first.

Fixed:
- Server: camera-sync --run and the service worker developed 3 frames twice
  (recover_stale assumed a single worker). One worker pass per data dir now
  (flock on <data>/worker.lock; the second pass reports busy).
- App 0.1.2: overlay moved below Canon's top icon row and shortened
  ("Portra400 3/12"); the menu repaints every 300 ms without clearing (Canon
  keeps drawing its icons into the same bitmap) and hides CHDK's title bar.

## 0.1.5: the menu leaves the live view

Camera videos of 0.1.2-0.1.4 showed that a Lua menu cannot share the live
view: Canon (shots left, battery) and CHDK's own OSD (clock, battery %,
temperature, DNG counter) draw into the same bitmap, and CHDK clears it from
time to time, so the menu showed the live view and icons through whatever the
repaint rate. 0.1.5 switches to playback (set_record) while the menu is up and
turns CHDK's "Show OSD" (conf id 1) off, restoring both when leaving (and the
OSD at start, in case of a power-off in the menu). While shooting the counter
and strip appear for 3 s at start and after each shot, centred above Canon's
bottom row, then the screen is given back (draw_clear). The harness models
record/playback and the OSD setting and fails if menu text is drawn in shooting
mode; keys reach the app only when it waits for one; expect waits up to 3 s.

## 0.1.7: CHDK config ids

`set_config_value(id)` treats ids below CONF_CORE (1000) as OLD 1.2 ids and
remaps them (modules/conf_migrate.c): 0.1.5 used 1 for Show OSD (maps to 2001,
correct by luck) and 0.1.6 used 102/104 for the battery display, which map to
core settings 1112/1121 instead. 0.1.6 was withdrawn before it ran on the
camera. 0.1.7 uses the real ids (CONF_OSD 2000 + osd_conf_info id), pinned in
src/camera/test/chdk-1.6.1-r6355-osd-conf-ids.txt and checked by tests; the
harness refuses ids below 1000. At start the app switches off CHDK's battery
icon/percent, clock, temperature, RAW counter and state and card space display.

## 0.1.8: menu redraw without clearing

Camera test 0.1.7 (video): moving the cursor briefly showed the photo or live
view under the lower part of the menu. screen() called draw_clear() whenever
the content changed and then repainted every row, so the bitmap was
transparent until the slow Lua repaint caught up. Now each row's signature is
cached and only changed rows are redrawn (a cursor move rewrites two rows); the
screen is never cleared while a menu is up, every row is opaque and full width
so a new screen overwrites the old one, and graphics (counter, canisters) are
redrawn only with their row. The safety repaint (every 5 s) rewrites text rows
only. A test replays the draw log and checks no clear and exactly two changed
rows per cursor move.

## 0.2.0: Canon's information display off, CHDK UI only

Owner's decision after 0.1.7/0.1.8: Canon's own UI is unwanted; the camera
should show CHDK's UI and the app. Canon draws its icons (shots left, battery,
mode, focus) into the same bitmap as CHDK's OSD and the app, redraws them on
its own schedule and CHDK repaints over them: that collision is the likely
source of the overlaps and of the CHDK OSD flicker seen so far.

- The app switches Canon's information display off by pressing DISP
  (`click("display")`) until propcase 105 (PROPCASE_DISPLAY_MODE, propset 6)
  is non-zero (0 = information shown; CHDK's osd_visible uses the same
  meaning). It does so on entering the menu and on starting to shoot, so an
  owner pressing DISP is undone at the next menu; Quit restores the original
  mode. The values seen are logged to APP.LOG and shown in Diagnostics.
  HARDWARE-TEST REQUIRED: which non-zero mode the SX510 HS lands on.
- The menu stays in shooting mode (no switch to playback) over the live view;
  every row is opaque and full width. CHDK's OSD is off while the menu is up.
- While shooting CHDK's OSD shows its battery icon (Canon's is hidden now);
  clock, temperature, RAW counter/state and card space stay off.
- CHDK's hide_osd default (1, "in playback") keeps its OSD visible in
  shooting mode whatever Canon's display mode.
- `click`/`press`/`release` are registered as closures in
  register_lua_funcs, so they are added to the pinned function list. The
  harness models propcase 105 and DISP and refuses menu text drawn while
  Canon's information display is on.

## 0.2.1: both bitmap buffers

Camera test 0.2.0 (video): rows drawn once (the film counter, rows the
cursor had not visited) showed the live view, and two rows were sometimes
highlighted at once. Cause, from CHDK release-1_6 r6355: the SX510 HS
platform defines DRAW_ON_ACTIVE_BITMAP_BUFFER_ONLY, so CHDK draws into
bitmap_buffer[active_bitmap_buffer] only, and Canon flips the two buffers.
CHDK's own GUI copes through a guard pixel (core/gui.c gui_redraw: repaint
when draw_test_guard() fails). This also explains the CHDK OSD flicker seen
earlier.

The app now reads (peek, read only) active_bitmap_buffer (0x4138) and
bitmap_buffer[] (0x413c), both from CHDK's stubs_min.S for sx510hs 101a,
keeps a row cache per buffer, samples three bitmap bytes it painted to
notice an erased buffer, and repaints a pass again if the buffer flipped
during it. Keys are polled every 60 ms, so a flipped buffer is filled within
about that. Build or sanity check mismatch: full repaint every 300 ms.
Diagnostics and APP.LOG show "bitmap buffers ... active N".

The harness models both buffers (flip, flip every n draws, Canon erase,
peek) and checks that both hold the same complete screen; the 0.2.0 app
fails that test with the second buffer empty, as on the camera.
