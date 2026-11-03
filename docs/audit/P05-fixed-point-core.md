# P05 prep: fixed-point streaming film stage (2026-11-03)

Status: implemented and parity-tested on the host; cross-compiled for the camera
CPU; not run on a camera.

## What it is

`src/shared/film_core/src/mf_fx.c`: the film stage of `mf_develop_frame` in
integer arithmetic, streamed by rows, for the camera's offline development.

- Three passes over the rows of the output-size linear image:
  1. scanner exposure (same print-pixel samples and log-average as `mf_scanner_ev`),
  2. halation grid (same 4x4-print-pixel cells, same [1 2 1] smoothing),
  3. render: exposure + film balance, vignette, glow, Cineon encode, tetrahedral
     film table, grain. Rows in any order (grain is coordinate-addressed).
- Memory: one context in caller memory (`mf_fx_ctx_size`): 97 KB at 720x480,
  100 KB at 1200x800, 105 KB at 1760x1173 (glow grid + per-column tables), plus
  the film's 33^3 uint16 table (215 KB). No heap, no frame buffer.
- Formats: input linear Q15 (1.0 = 32768), display output 0..65535.
- `mf_fx_look_bake` (host, float) turns film + recipe + output size into the
  integer constants (`mf_fx_look`); the camera never touches float. A future
  camera bundle carries baked looks; the 9 model films also need their tables
  baked into it (today `mf_table_from_film` computes them with float + libm).

## Scope (honest limits)

Only output sizes at which the film stage needs no spatial kernel:
`mf_develop_kernels()` (shared with the float path, so they cannot disagree)
returns 0. With default look controls that is every film up to ~1760 px wide;
softness or clumped grain above that is the Linux server's job, and a larger
request is refused with `MF_E_UNSUPPORTED`, never approximated.

## Evidence

- `test_fx` (ctest `fx_matches_float_stage`): fixed point vs float on the same
  quantised input, all 72 films at 720x480 and 1200x800 with grain, every 6th film
  also at 1760x1173, 600x900 portrait and without grain: 180 cases, worst
  difference 1 code of 255, worst mean 0.039 codes, scanner EV identical to 1e-4
  stop; forwards and backwards strip rendering give identical pixels; the two
  kernel-needing requests are refused.
- The test catches deliberate faults: dropping halation (max 217 codes), grain
  (max 4), vignette (max 5), or shifting exposure by 0.05 stop (max 5) all fail it.
- `tools/arm_check.sh`: built with CHDK's DIGIC 4 flags (`-marm -march=armv5te
  -mtune=arm946e-s -Os`, ARM mode as `arm_rules.inc` uses for non-thumb firmware),
  the camera tier (`mf_fx.c`, `mf_seed.c`, `mf_sha256.c`) is 9.7 KB and needs only
  `__aeabi_uidiv`, `__aeabi_uidivmod`, `memcpy`, `memset`, `strlen`, all exported to
  CHDK modules (`modules/module_exportlist.inc` / `.c`). No float, no libm, no
  64-bit divide (CHDK does not export `__aeabi_uldivmod`), no per-pixel divide.
  The float path fails the same check, as it should.
- `mf_frame_seed` no longer uses `snprintf` (not exported to modules).

## Not done / next

- Nothing has run on the camera. Speed on the ARM946E-S and real free memory
  are unknown; three reads of the source per frame may be too slow.
- The raw adapter (CHDK raw buffer -> output-size linear RGB) and a camera-side
  JPEG encoder are separate P05 work.
- Camera bundle format with baked `mf_fx_look` + all 72 tables.

## Deployment note

Adding these sources changes `mf_core_version`, so every new Linux render_id
differs from before (pixels do not). Update a running server only with an empty
queue: stop the worker, check no job is QUEUED/RUNNING, update, start
(`deploy/update-user.sh` does this). `RENDER_IDENTITY_MISMATCH` is now terminal
(no wasted retries); `mfilmctl develop <roll>` re-queues under the current core.
