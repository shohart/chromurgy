# Camera probe and first on-camera film-core run (2026-11-04)

Status: VERIFIED on the owner's SX510 HS unless marked otherwise. Raw logs
(`MFPROBE.TXT`, `MFBENCH.TXT`, `MFBENCH.PPM`) are kept with the calibration
shots outside Git.

## Camera and CHDK

- Canon PowerShot SX510 HS, firmware GM1.01A (platformid 12919).
- CHDK 1.6.1 build 6355 (autobuild `sx510hs-101a-1.6.1-6355-full_ALPHA`, built
  2026-07-20), DryOS, loaded from a new SD card (the old card had failed: writes
  silently dropped, unstable reads).
- Our module `MFBENCH.FLT`, built from the pinned CHDK trunk 1.7.0 (`tools/build_chdk.sh`),
  loads and runs on 1.6.1: modules bind CHDK exports by name hash.
- Lua in 1.6.1 has no `get_focal_length` (1.7+); `src/camera/scripts/mfprobe.lua`
  tolerates missing functions. The DNG EXIF carries the focal length.

## Resources (`mfprobe.lua`, `MFBENCH.FLT`)

| item | value |
|---|---|
| heap (system = combined; no ARAM, no EXMEM) | 3,182,272 B total, ~1.42-1.57 MB free |
| largest free block / largest malloc | 1,535,648 B / 1,531,904 B |
| CHDK core | 137,304 B at 0x265a28 |
| battery | 3.935-3.940 V |
| temperatures optical/CCD/battery | 28 / 30 / 30 C |
| zoom | 128 steps (0-127) |
| card | 15.26 GB, 673 DNG frames left |
| Lua, 200k integer loop iterations | 3,330 ms (pixel work must be C) |

## Shot timing (`mfprobe.lua`, P mode, DNG on)

- `shoot()` returns after 2,690 ms; the DNG (`CRW_4235.DNG`, 19,182,024 B) is
  complete and size-stable 130 ms after that. A script can hash/journal the DNG
  right after `shoot()`.

## Film core on the camera (`MFBENCH.FLT`, Portra 400, synthetic frame)

Output of `mf_fx` on the camera is **bit-identical** to the Linux host at both
sizes (chained SHA-256 of all output rows; the 720x480 preview also compares
equal pixel for pixel).

| size | context + strip buffers | scan | glow | render | total incl. scene generation, hashing, preview write |
|---|---|---|---|---|---|
| 720x480 | 96,552 + 103,712 B | <10 ms* | 30 ms* | 3,050 ms | 8,650 ms |
| 1200x800 | 100,392 + 172,832 B | 170 ms* | 1,200 ms* | 12,080 ms | 25,590 ms |

\* tick resolution is 10 ms and each strip call is shorter, so the per-strip
scan/glow sums undercount. Render: ~12.6 us per output pixel at 1200x800.
Film table 215,622 B. Peak use at 1200x800 ~0.5 MB of the 1.5 MB free block.

Other: SHA-256 1 MB in 560 ms (~1.8 MB/s: hashing one 19 MB DNG would take ~10.5 s);
SD write 8 MB in 1,690 ms (4.8 MB/s, 256 KB chunks); SD read 8 MB in 1,350 ms (6.1 MB/s).

## Failure found and fixed

The first run computed inside the GUI/keyboard task: 720x480 (9 s) finished, the
1200x800 case (~30 s) did not and the camera powered off. The bench now runs in its
own task (priority 0x1A, like CHDK's DNG byte reverser) and sleeps 10 ms between
strips; the second run completed both sizes and the SD tests, camera stayed on.
Long work on the camera must always run like this (offline developer, hashing).

## Consequences for P04/P05 (PROPOSED)

- Offline development at 1200x800: ~13.5 s of film core per frame plus raw read,
  reduction and JPEG encoding, i.e. several minutes per 36-frame roll; acceptable
  for a fallback, render is the place to optimise.
- Hashing every DNG on the camera costs ~10 s per frame; the manifest should
  record name, size and capture time at shot time and hash in the background (or
  leave hashing to the receiver for SD ingest).
- Not yet measured: raw-buffer access from a module, JPEG encoding, battery drain
  over a full roll, UI interception.
