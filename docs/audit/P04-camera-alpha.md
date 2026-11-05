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

## 0.3.0: rolls, own viewer, M-Film CHDK build

Owner's request (2026-11-05): rolls on the card with Develop / View, the
developed frames viewed in the app, Canon's own gallery never shown. The
owner allowed a folder for developed frames; it turned out not to be needed
in DCIM (below).

Display path. CHDK Lua cannot show a photo, and per-byte poke from Lua is far
too slow (camera: ~60k Lua loop iterations/s; a frame is 518 KB). So the app
runs on a CHDK built from the same source as the camera's (release-1_6
r6355, exported over HTTP into build/chdk-1.6-src; tools/build_chdk16.sh)
with three Lua functions added to its Lua module (src/camera/chdk/mfilm_lua.c):

- `mf_show(path)`: copies an MFV file into the playback image buffer
  (`vid_get_viewport_active_buffer()`, which is viewport_fb_d in playback),
  only in playback and only if the file's geometry equals the buffer's;
- `mf_overlay_clear()`: makes both overlay buffers transparent so Canon's
  playback icons do not cover the photo (bitmap_buffer[] at 0x413c from the
  sx510hs 101a stubs; refuses on any other platform at run time);
- `mf_viewport()`: the buffer address and geometry, for diagnostics.

Nothing is written to flash; the only memory written is the picture and the
overlay. HARDWARE-TEST REQUIRED: Diagnostics -> SET runs a screen test
(CHDK/MFVIEW/TEST.MFV: colour bars, grey ramp, a circle that must look
round); the log records the viewport geometry.

MFV (src/server/mfilm_server/camera_view.py): "MFV1", u16 width 720,
height 480, byte width 1080, then UYVYYY rows (U, V signed, as CHDK's
histogram reads them), 518,412 bytes. A 4:3 frame fills the 720x480 buffer
(non-square pixels on the 4:3 screen); a portrait frame is pillarboxed.

Frames reach the camera at Wi-Fi sync: camera-sync --run now imports,
develops and publishes while the camera is still connected, then uploads
A/CHDK/MFVIEW/<ROLL8>/Fnn.MFV for rolls whose set changed and an INDEX.CFG
(outside A/CHDK/MFILM, which every sync downloads).

App: Rolls (card rolls and developed rolls, canister icons, DEV marker) ->
roll card (film, date, frames, state) -> View developed frames (left/right,
SET hides the caption, MENU back, half-press: shoot) or Develop (on-camera
developing is the next step; the item says so). Canon's playback while
shooting is caught and turned back into the M-Film menu.

Installing: the card needs the M-Film DISKBOOT.BIN and CHDK/MODULES from
`mfilmctl camera-card OUT --chdk`; the app says so if it runs on stock CHDK.

## 0.4.0: developing on the camera

Rolls -> roll card -> Develop develops every frame on the camera (a roll still
in the camera is finished first, after a confirmation). Per frame, in its own
task (prio 0x1A, yields every 8-row strip): the DNG is read once and binned
4x4, LibRaw's fitted daylight transform, the lens table (fixed point),
mf_fx scan/glow/render at 1024x768, then a baseline JPEG
(A/CHDK/MFDEV/C<7 hex>/Fnn.JPG) and the viewer frame
(A/CHDK/MFVIEW/C<7 hex>/Fnn.MFV, turned upright by the DNG orientation:
TIFF 8 = LibRaw flip 5, 6 = flip 6). A finished roll goes into
A/CHDK/MFVIEW/CAMINDEX.CFG; the viewer prefers the server's set (INDEX.CFG)
when both exist. MENU stops; frames already developed stay. Full-size
development stays the server's job.

Code: src/camera/dev (mfd_develop, mfd_dng, mfd_jpeg, mfd_view, mfd_files,
mfdev_cam = CHDK env + task), linked into lua.flt by
src/camera/chdk/makefile_usermodules.inc (developer and film core -marm); Lua
functions mf_dev_start / mf_dev_status / mf_dev_cancel in mfilm_lua.c; the
Lua module's can_unload keeps it loaded while a frame is developing.

Data on the card (mfilmctl camera-card --chdk): CHDK/MFDEV/MFCAM.BIN
(camera_dev.py: white balance, camera->sRGB matrix, lens table in fixed
point) and MFDEV.BIN (mfdev_gen: all 72 films baked at 1024x768, 15.5 MB).

Host evidence: mfdev_host (same code and files) on three of the owner's
frames: landscape 4.3 mm, portrait 19 mm (orientation 8), portrait 4.3 mm
(6): mean colour within 1/255 of the server's render, viewer frames upright;
0.3 s per frame on the workstation; heap peak 350 KB landscape, 930 KB
portrait (+216 KB film table). tests/test_camera_dev.py runs it on a
synthetic CHDK-layout DNG (landscape, both portraits, unknown film), the
harness covers the app flow (develop, stop, missing data files).
HARDWARE-TEST REQUIRED: time per frame and heap on the SX510 HS.

## 0.4.1: boot loop with 0.4.0 card; official core, crash-loop guard

The owner's camera rebooted in a loop after installing the 0.4.0 card (our
own DISKBOOT.BIN, built here from release-1_6 r6355 with GCC 10, plus our
modules; CHDK autostarts the app at every power-on). Cause not yet proven
(ROMLOG.LOG from the card is needed). Changes:

- tools/build_chdk16.sh now ships the OFFICIAL CHDK 1.6.1-6355 build for
  sx510hs 101a (mighty-hoernsche.de, zip pinned by SHA-256): its
  DISKBOOT.BIN and modules byte for byte, with only lua.flt replaced by ours.
  Our core build is no longer used on the card.
- Crash-loop guard in the app: A/CHDK/MFILM/BOOT.TXT reads "starting" until
  the app has been up 5 s; an autostart that finds "starting" switches CHDK
  autostart off and says so, so a failing start cannot repeat forever.
- mfilm_alpha/FALLBACK/lua.flt is the official module: if the loop stays
  with 0.4.1, putting it in CHDK/MODULES tells core from module apart (the
  app then runs without the viewer and developer, and says so).

## 0.4.2: the boot loop explained (ROMLOG) and fixed

ROMLOG 2026-11-05 13:03: Exception vector 0x04 (undefined instruction) in
PhySw (the task running scripts), PC 0x005B0E14 (in the stack), return
addresses 0x422D15, 0x425965, 0x425993, 0x425FE1. Matched against lua.elf,
they fit exactly one load base, 0x4162D0: luaF_newproto, hashnum,
mainposition, newkey — Lua running in a module that was no longer there.
Cause: 0.4.0 had set _liblua's can_unload to a function returning "not
busy". CHDK calls can_unload on every keyboard tick and unloads the module
as soon as it returns true (modules/module_load.c module_tick_unloader), so
the Lua module was unloaded under the running script at every autostart.
Fix: can_unload stays 0 (tools/build_chdk16.sh refuses otherwise). The
developer task needs no such guard: the app waits for every frame or stops
it before the script can end. The official core (0.4.1) and the crash-loop
guard stay.

## 0.4.3: develop "stop" killed the camera; flicker

ROMLOG 13:14: data abort (vector 0x10) in task MFDevelop; return addresses at
the same module base 0x4162D0 map to dev_task -> mfd_develop ->
mfd_view_end. Stopping (or any error) before the render pass ended a viewer
whose heap block had been allocated but never begun; the camera heap is not
zeroed, so mfd_view_end closed and freed garbage. Fixed: the view and JPEG
state are zeroed when allocated, and ending a never-begun view is a no-op.
The host driver now fills every allocation with 0xA5 and can stop at a given
progress (MFDEV_CANCEL_AT); tests stop in each pass. The portrait viewer
buffer is RGB565 (390 KB instead of 580; host peak 740 KB + 216 KB film
table). APP.LOG records heap before and after each frame, and the screen
says why a frame failed.

Flicker: repainting the flipped-to overlay buffer within 60 ms was still
visible now and then. mf_overlay_mirror() (M-Film CHDK build) copies the
buffer just painted into the other one after every pass that changed
something, so a flip shows the same menu.

## 0.5.x: the simulator, and what it found (2026-11-05)

No emulator runs the SX510 HS firmware (QEMU for Canon needs a ROM dump and
covers mostly EOS), so the host harness became a model of the camera:
two overlay buffers that Canon flips and erases at random moments (seeded),
CHDK's splash, mode-switch transitions, the camera's heap for the developer,
CHDK's integer Lua and print, DryOS file rules, a deterministic clock. A
display model compares, at every tick, what the screen shows with what the
app last painted and counts visible glitches by cause, with the app's stack.
tools/fuzz_camera_app.py walks every screen (guided macros + random keys,
power cuts, Canon playback, low heap) and checks the roll manifests;
tools/screens_tour.py renders every screen with CHDK's own font.

Found and fixed with it (none needed the camera):
- load animation and viewer caption drawn into one buffer only (flicker on
  flips); erased viewer caption never noticed (gone for a second);
- the watcher stat'ed every DNG of every folder on every pass: ~2000 card
  accesses a second with a 400-file folder; now ~20 a second (new and
  unconfirmed files, a full check every 30 s or after a shot with no new DNG);
- string.format width flags (%-12s, %4d) replaced by Lua padding: on the
  camera Lua's format goes to Canon's _vsprintf, only %02d is proven there;
- harness bugs fixed on the way (a 32-bit-overflowing RNG, truncated print).

Results: 200 runs x 200 steps, 0 failures, 0 flicker from buffer flips,
erase glitches closed within one poll (60 ms in menus, 200 ms while
developing); Lua memory flat over an hour of camera time (151 shots).
Known: under flip+erase storms the viewer caption was once missing for
360 ms. CHDK's default alt_prevent_shutdown keeps the camera on while the
app is in ALT mode (menus, developing).

## 0.5.2: no redraw over itself (camera: the strip flickered)

Owner, camera 0.5.1: developing works; the contact strip on the developing
screen flickered as a whole with the pulsing current frame. Cause: every
pulse redrew the strip from a black fill up. The harness only compared
screens at the end of each pass, so it could not see a flash inside one.
It now keeps a pixel model of the overlay and counts "ghost" pixels -- set
and set back within one pass (a new screen, > 5000 changed pixels, is not
counted); the fuzz fails above 40. It found the strip (3190 px per pulse),
the main menu's film block (canister, counter, strip redrawn over themselves
by the 1 s safety refresh -- a flash every second), the load animation, the
canister icons in lists on the refresh, and the stage text drawn 4 px into
the next row.

Fixed: graphics lines have a key (what they show) and a signature (what
changes) and draw whole only when the key is new or the buffer was erased,
otherwise just the changed parts (the strip redraws the one cell that
changed; the tank moves only the dots of the reel and bubbles); canister and
strips are tiled so every pixel is set once; nothing graphic is redrawn by
the safety refresh. 100 fuzz runs: 0 ghosts above 40 px.
