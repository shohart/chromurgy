# 00 — Scope, Goals and Acceptance Gates

## Product objective

The SX510 HS should feel like a film camera at capture time and like a self-hosted RAW scanner afterwards: create a roll, shoot without immediate review, and **develop remotely on Linux by default**. Only when the server cannot be reached should the camera offer its own slower developer, using the same M-Film rendering logic.

## Priority order

**P0** — keep photographs safe; roll manifests; host full-resolution DNG-to-JPEG; shared film profiles; ingestion by at least SD; server archive; PhotoPrism integration; realistic diagnostics.

**P1** — CHDK on camera; roll capture without preview; USB/PTP sync; camera-local offline developer, at least reference-resolution output; developed-only app gallery; sync receipts and optional download of finished JPEGs.

**P2** — autonomous Wi-Fi client; Wi-Fi discovery/pairing, resumable bidirectional sync; larger on-camera developer resolution where performance permits; interactive film browsing; robust power management.

**P3** — advanced effects, full 12 MP on-device output, alternative cameras, remote device management.

Priority is not permission to omit P1/P2 from the design. P2 Wi-Fi remains gated by actual DryOS investigation.

## Success conditions

- A shot taken in a loaded roll has an immutable RAW/DNG with reliable roll/frame associations.
- No slow RAW development occurs between shutter presses; a closed roll can be synced later without reopening shooting UI.
- Linux receives all originals for a roll, verifies hashes, renders with the same film-core algorithms as the camera and saves full-size JPEGs without upscaling low-res previews.
- PhotoPrism sees finished images **only** after fully committed, verified export; originals can be archived outside indexed originals.
- For an unreachable server, the camera can develop the same roll locally, with the exact film profile and render recipe; actual attainable resolution must be measured and shown to the user.
- A later sync of an offline-developed roll archives DNG and optionally generates the server-grade full-resolution rendition. Both versions remain distinguishable.
- Server-developed files can be retrieved to populate the app gallery on the camera, without assuming Canon OEM Playback indexes arbitrary filenames.
- Interruptions do not corrupt RAW originals, duplicate files or produce false completion receipts.

## Out of scope in v1

Camera OTA updates; Internet-facing cloud hosting; exposure-control rewrites; video RAW; sharing albums via camera; editing Canon firmware ROM; background transfer while camera is off; guaranteed instantaneous image display; copying The Ritual proprietary algorithms. Server look management and on-device camera-specific DNG support are included in scope.

## Measurable performance goals (not promises)

- Host **4000×3000 final JPEG** at 4:3 where DNG active area supports it (official SX510 HS large image size). Other aspect ratios preserve intended crop.
- On-device first proof can be preview-sized; aim for 2592×1944 then 3264×2448 only if RAM/CPU permit.
- Film rendering reproducible within the reference parity thresholds; document the exact target and any resolution/decoder differences.
- Transmission: tolerate repeated or partial sends; no duplicate originals, no lost receipts; at most one canonical asset for each `device_id+roll_id+frame_id+sha256`.
- Hardware tests include at least 20 consecutive frames, power cycles, unplugged USB, failed Wi-Fi, interrupted camera processing, low storage and duplicate receipt replay.

## Dependencies and unknowns

CHDK on SX510 HS is historically an **ALPHA port**; exact firmware version, RAW hooks, memory, Wi-Fi, gallery interception and C-module execution need measurements. Never promise a fully supported networking stack merely because Canon shipped Wi-Fi hardware.
