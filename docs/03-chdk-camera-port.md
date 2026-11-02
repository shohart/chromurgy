# 03 — CHDK Port and Camera Hardware

## Confirmed baseline vs. unknowns

**Verified external camera specs:** SX510 HS is a Canon PowerShot with 12.1 MP CMOS, native still size up to **4000×3000**, DIGIC-generation CHDK port and 2.4 GHz 802.11b/g/n Wi-Fi. Official Canon documentation does **not** imply a public TCP/IP scripting API. CHDK community material identifies an SX510 HS port, historically labeled ALPHA; firmware subversions and current build support must be checked before use.

**Hardware unknowns:** exact Canon firmware version; loaded CHDK version; stable RAW hook and DNG support; size of free RAM and stack; framebuffer format/palette; C module ABI; Canon JPEG review suppression; side effects of file moves; Wi-Fi startup and networking APIs; power draw and sleep conditions.

## Required hardware probe

1. Read Canon firmware version (from a test JPEG or supported `ver.req` method), inspect SD card and stock camera menus.
2. Prepare a separate SD card with an exactly matching, reputable CHDK build. Preserve existing photos. Avoid any permanent Canon ROM flash.
3. Collect CHDK build ID, available free heap, `malloc` limits, CPU/bit-depth capabilities, RAW/DNG layout, and battery voltage readout (if exposed).
4. Capture 3 normal DNG/JPEG pairs (sunlit colors, high contrast, dark scene). With user permission include privately in local fixture set only, not in public Git.
5. Test UI callback interception, `PLAY` key, half-shutter, main Canon UI switching, CHDK RAW hooks, file handles and safe time of moving files after image write is finalized.
6. Benchmark minimal processing: read 1 MB, hash a DNG, decode a tile, transform tile, write small JPEG; collect peak memory and temperature/battery observations.
7. Research Wi-Fi: native Canon network mode, socket symbols in firmware dump, DryOS functions, PTP/IP behavior, OS task requirements and recovery after failure. No undocumented RAM addresses on camera until independently justified and owner approved.

Record all results in `templates/hardware-probe.md` with build hash and exact firmware revision.

## Implementing the device layer

Use `fos_port_*` interface from M-Film's `ml-dev/filmos/fos.h` as a reference: time, key events, overlay present/palette, memory, file operations, roll state and shooting metadata. Implement CHDK equivalents in a thin C adapter, e.g. `fos_port_chdk.c`. **Do not assume** the upstream canvas resolution/palette will work on this model: adapt coordinates, palette and display in a separate renderer.

Prefer a loadable module if it exposes required CHDK services; verify before committing to it. If a custom CHDK build is required, isolate patches and make rebuild reproducible. Use Lua/CHDKPTP for probes, not for full-resolution per-pixel workloads.

## Camera safety

- Preserve Canon OEM firmware; keep one known-good SD card without experiments.
- Never rely on auto-preview/Canon JPEG deletion prevention being safe until tested. Default `capture_protection=strict`; a failed DNG validation must prevent any JPEG deletion/move.
- Keep a documented escape / uninstall path (remove test card, reboot after power-off, restore OEM camera operation where applicable).
- Use low-risk read-only probes first. Nonvolatile writes, guessed memory patching and network firmware alteration are explicitly out of scope without owner approval.
- Never report the full product complete before on-body tests prove roll control and image integrity.

## Native preview problem

The SX510 HS stock processing pipeline normally creates a JPEG even if CHDK also saves RAW. Requirements: suppress automatic after-shot display; intercept casual playback; quarantine originals from user gallery only after writes are complete and native playback behavior is assessed. A simple overlay that disappears when Canon Playback is entered is not an acceptable guarantee. If strict hide is technically impossible on this port, report that limitation with the best safe compromise, not a false claim.
