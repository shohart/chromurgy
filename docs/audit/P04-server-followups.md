# Server follow-ups: bundle archive, reprocess, camera renders (2026-11-03)

Status: implemented and tested on the host. Nothing here touches the camera.

## Profile bundle archive (docs/05, docs/12 "pause or use archived exact bundle")

- `mfilm_server/bundles.py`: bundles are stored content-addressed under
  `<data_dir>/bundles/<sha256>.bin` (read-only, staged + hash-checked + promoted),
  with the `films.json` that described them when its `profile_bundle_hash` matches.
- The shipped `profiles/mfilm-films.bin` is archived on `mfilmctl init`, on every
  worker pass and when the receiver starts.
- The worker develops each render with the bundle named in its recipe. A missing
  bundle parks the job in `WAITING_FOR_INPUTS` (`PROFILE_BUNDLE_UNAVAILABLE`, no
  attempt spent); `mfilmctl bundle-add <file>` archives it and re-queues the parked
  jobs. Publication of a roll waits while any of its renders is parked.
- `GET /v1/capabilities` lists all archived bundle hashes in `profile_bundles`.
- Replaces the earlier terminal `PROFILE_BUNDLE_MISMATCH` for rolls shot with an
  unknown bundle.

## `mfilmctl reprocess` (docs/01, docs/07 "Recipe changes", docs/08 admin CLI)

- `reprocess <roll> [--profile K] [--bundle HASH|current] [--grain-scale/--halation-scale/--softness-scale X] [--exposure-ev X] [--seed N] [--run]`.
- Unchanged arguments rebuild exactly the roll's recipe: same render ids, so it is a
  no-op ("nothing new"). Any change gets `recipe_id = reprocess-<film>-<hash of the
  change>`, hence a new grain seed and new renditions next to the old ones.
- The roll row is never changed (its film stays frozen). The bundle stays the roll's
  own unless `--bundle` is given explicitly.
- Unknown film for that bundle, or a bundle that is not archived, is refused.
- PhotoPrism folders are now named after the film of each render, so a reprocess
  with another film lands in its own `<date>_<Film>_<roll8>` folder. Publication is
  additive; nothing already in the library is replaced or removed.
- `--new-rendition` from the docs/08 sketch is not needed: every changed recipe is a
  new rendition by construction.

## Camera offline renders, `media_role=camera_render` (P06 receiver side)

- `POST /v1/uploads` accepts `camera_render` with a `render` record
  (`render_id, recipe, film_core_version, grain_seed, output_width, output_height`).
  The server checks the recipe is the roll's frozen film + bundle, recomputes the
  frame's grain seed and the render id from the frame's declared original hash, and
  refuses mismatches with 409 (`GRAIN_SEED_MISMATCH`, `RENDER_IDENTITY_MISMATCH`,
  `PROFILE_BUNDLE_MISMATCH`). The record is kept with the session (migration 4,
  `uploads.meta`).
- On complete: hash check, Pillow check that it is a JPEG of the declared size
  (else 422 `BAD_CAMERA_RENDER`, session aborted), then stored as
  `offline-renders/<device>/<roll>/<render_id>.jpg` + provenance sidecar,
  `assets.kind=offline_jpeg`, `renders.origin=camera`. Replays return the same receipt.
- Camera renders are never published and do not replace the linux canonical
  rendition. `GET /v1/rolls/{id}` shows `camera_render_id` per frame;
  `GET /v1/rolls/{id}/renders?origin=camera|all` lists them (default stays `linux`).
- Reference client: `simulator.py` uploads originals first, finalizes, then any
  `ROLLS/<roll_id>/offline/NN.jpg` + `NN.json`. `--develop-here` fakes the camera's
  reduced offline development (1200x800) with the shared core. The card layout for
  offline renders is a proposal until CHDK path limits are measured.

## PhotoPrism finding (operational, not code)

- On the owner's server the local CIFS mount `/mnt/theVault` is a Samba share rooted
  at the server's `/mnt/theVault/DOWNLOADS`, so the same-looking path over CIFS is not
  PhotoPrism's originals. A demo publication landed there and was removed.
- The `photoprism` container had started before `/mnt/theVault` was mounted and saw an
  empty originals directory (2026-11-03). `PHOTOPRISM_INDEX_SCHEDULE` is empty and
  `PHOTOPRISM_AUTO_INDEX` only covers WebDAV uploads.
- `deploy/README.md` now has a PhotoPrism checklist covering these.

## Evidence

- `ci/check.sh` on the committed tree: ctest 5/5, upstream table parity OK, pytest 48 passed, 0 skipped (9 min 20 s).
- New tests: parked-until-added bundle flow, garbage bundle refused, reprocess
  idempotence + new film + frozen roll, per-film publish folders, camera render
  upload/replay/reconciliation, camera render identity checks and bad JPEG.

## Deployment on octopusreborn and develop benchmark (2026-11-03)

Full-size develop of `SAMPLE.CR2` (5208x3476, Portra 400), `mfilm-develop` wall time
including the rawpy decode, same commit on both machines:

| host | CPU | 1 frame | throughput |
|---|---|---|---|
| octopusreborn | i7-4770K, 8 threads, 15 GB | 11.8 s | 9.4 / 15.4 / 17.1 frames/min at 2 / 4 / 6 parallel |
| workstation | Xeon E5-2696 v4, 44 threads, 125 GB | 13.8 s (Release) | 32.2 / 42.1 frames/min at 16 / 32 parallel |

- The old default build (`RelWithDebInfo`, -O2) took 24.5 s per frame on the
  workstation; -O3 Release is now the default.
- Output is byte-identical across both hosts and across -O2/-O3
  (`fa9dc726fa440dc1...`, same render_id), so a frame can be developed on either.
- End to end on octopusreborn, `[worker] jobs = 4`: a 12-frame demo roll imported,
  developed, published and indexed by PhotoPrism in 56 s (PhotoPrism `find` lists
  all 12 under `M-Film/2026-11-03_Portra400_25f6b8d3/`).
- Per 36-frame roll: ~2.2 min on octopusreborn (4-6 parallel) vs ~0.9 min on the
  workstation (32 parallel). Remote offload to the workstation is not built; the
  difference is about a minute per roll.

Deployment (no root): checkout `~/services/mfilm`, uv + cmake in `~/.local`,
data in `/mnt/theVault/mfilm`, publication to `/mnt/theVault/RAW_LIB/photos/M-Film`
(the container's `/photoprism/originals/M-Film`), index after every publish with
`docker exec photoprism photoprism index M-Film`, user unit
`deploy/systemd/user/mfilm-worker.service` with linger enabled; the unit refuses
to start while `/mnt/theVault` is not mounted.

## Camera toolchain

- SX510 HS = DIGIC 4+: ARM946E-S, armv5te, no FPU. CHDK accepts GCC 4/5/8-11;
  Debian trixie ships 14. Pinned Arm GNU Toolchain 10.3-2021.10 (sha256 in
  `tools/arm_check.sh --install`, installed under `~/.local/opt`).
- The current float core cross-compiles cleanly to 11 KB of thumb code but needs
  soft-float and libm (`exp2f`, `powf`, `atan2f`, ...). `tools/arm_check.sh` fails on
  that by design; the tiled fixed-point variant must pass it.
