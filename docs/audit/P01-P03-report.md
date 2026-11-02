# Engineering Phase Report: P01 film core, P02 Linux developer, P03 queue + PhotoPrism

- Phase ID / milestone gate: P01, P02, P03 → toward G1 (host pipeline). G1 not claimed: no SX510 HS DNG yet.
- Date: 2026-11-02
- Agent / environment: Claude Code (Opus 5.5); Debian 13 x86-64, gcc 14.2, cmake 3.31, Python 3.12 venv (uv), LibRaw 0.22.2 via rawpy 0.28, Pillow 13
- Pinned M-Film commit: `7c6cd7ee78a51182ae211818a59bb1bad80b234c`
- Pinned Film-Luts commit: `af957b631a304e6be94778b96cb3395de3438e9f` (MIT)
- Pinned CHDK revision: `3d8aa1082ed57a04efa556103e49da751ba1e44c` (unused in these phases)
- Film core ABI 1; core version = SHA-256 of its sources, baked into `libmf_core.so` (`mf_core_version()`)
- Profile bundle: `profiles/mfilm-films.bin`, sha256 `56e7dc7fe8326acb02d14655ceb81095cb8656b3f469d3cbe529911329776e05`

## Delivered

| Item | Where |
|---|---|
| All 72 M-Film films | `profiles/source/{films,filmluts,lut}.py` (verbatim upstream), `profiles/luts/` (63 Film-Luts `.cube`), `tools/build_bundle.py` → `profiles/mfilm-films.bin` + `profiles/films.json` |
| Bundle reader (bounds-checked) | `src/shared/film_core/src/mf_bundle.c` |
| Film table (Cineon 33³, tetrahedral) | `mf_table.c` |
| Whole-frame film stage | `mf_develop.c`: scanner exposure → film balance → softness → halation glow grid + vignette → table → grain |
| FFI + shared library | `mf_api.c`, `libmf_core.so` |
| `mfilm-develop` CLI | `src/server/mfilm_server/develop.py` (rawpy/LibRaw input adapter, JPEG + ICC + EXIF dates + provenance sidecar) |
| Queue + worker | `worker.py`, `mfilmctl develop/worker [--watch]` |
| PhotoPrism publisher | `publisher.py`, `mfilmctl publish [--index]`, auto-publish in worker |
| Receiver API (docs/09) | `api.py` (`mfilm-receiver`), device tokens `devices.py`, `mfilmctl device-pair/device-revoke` |
| Fake camera (reference sync client) | `simulator.py` |
| Config, deployment | `config.example.toml`, `deploy/systemd/mfilm-worker.service`, `deploy/README.md` |

Films: 63 take their colour from the Film-Luts LUT baked into a uint16 table; 9 use M-Film's own model (`portra400`, `cinestill800t`, `ektar100`, `gold200`, `superia400`, `velvia50`, `hp5`, `trix400`, and `cinestill400t`, whose upstream LUT is the author's private file, so upstream also falls back to the model).

## Verification

| Test | Command | Result |
|---|---|---|
| 8 built-in looks in the bundle equal upstream `fos_looks.c` | ctest `bundle_parses_all_films` | PASS |
| 63 LUT tables vs upstream `genfilms.py` `LOOKnn.LUT` | `tools/check_upstream_tables.sh` | PASS, max 0.498 of an 8-bit step (= identical after rounding) |
| Damaged bundles refused (magic, truncation, unterminated key) | ctest | PASS |
| Film stage: deterministic, seed-dependent grain, mono stays neutral, every film develops, unknown film refused | ctest `develop_frame_properties` | PASS |
| **Same CR2, same film vs M-Film's own in-camera developer** (`devtest`, 720×480) | `pytest test_develop.py::test_close_to_upstream_camera_print` | PASS: mean RGB 0.486/0.421/0.395 vs upstream 0.485/0.420/0.394; visually indistinguishable (`build/samples/compare-day.png`) |
| Byte-identical output for identical inputs | `pytest test_develop.py` | PASS (after zeroing the ICC creation date) |
| Card → archive → queue → full-size JPEG → PhotoPrism folder, idempotent, crash recovery, bundle mismatch terminal | `pytest test_worker.py test_publisher.py` | PASS (37 pytest total) |
| Sync API: idempotent manifest/uploads/finalize, receipts replay, conflicts, device isolation, revocation, hash mismatch 422, offset 409 | `pytest test_api.py` | PASS |
| Power loss after 100 chunks of a 26 MB original, resume from server offset, develop, return JPEG to camera gallery with hash check | `pytest test_api.py::test_power_loss_resume_develop_and_return`; live run over HTTP with uvicorn + simulator | PASS (resumed with exactly the remaining chunks) |
| Real PhotoPrism instance indexes the export | — | NOT TESTED (owner consent needed to write into the live library) |
| SX510 HS DNG | — | BLOCKED: no sample |

## Measurements

- M-Film sample CR2 (EOS M, 5208×3476 after LibRaw crop): full-size develop 7.7 s for the film stage + JPEG, 13.3 s wall including LibRaw AHD decode; peak RSS 0.91 GB; JPEG q92 4.2 MB.
- Scanner EV on the sample: ours 0.66 (daylight WB) vs upstream 0.45; the outputs still match in mean, because LibRaw's linear scale differs slightly from the camera's box-filtered sums. Not tuned.

## Decisions and deviations (PROPOSED unless noted)

- **Sizes in print pixels.** Upstream works on a 720×480 print; every radius here is expressed in print pixels of the frame fitted into 720×480, so the camera print is reproduced at scale 1 and a 4000×3000 frame gets the same relative glow, vignette and key sampling.
- **Grain above print size.** Upstream's camera grain is per-pixel noise × 0.55 (the softening of its 7.2× downscale from the lab's 5184 px). Full-size renders get grain clumped by `grain_size` (films.py, in lab px) and the amplitude interpolated log-linearly from 1.0 at lab size to 0.55 at camera size. Needs visual sign-off against real film scans.
- **Softness** (`soft`, unused by the camera) is applied above print size as a gaussian in lab px.
- **White balance default = daylight** (film is balanced; matches upstream). `as-shot` is available in recipes.
- **Float/uint16 instead of the camera's 1/4096 integers and uint8 table**: the camera build will need a fixed-point mode and tolerance-based parity (docs/05).
- Input adapter: LibRaw AHD, highlight clip, sRGB output, 1.0 = white level. CHDK's SX510 HS DNG colour matrix is a D10 copy (P00): **colour on SX510 files is uncalibrated until real DNGs arrive.**

## Constraints and follow-up

- Cannot yet claim: anything about SX510 HS files; PhotoPrism indexing on the live instance; that the camera can speak HTTP at all (G5); camera-rendered (offline) uploads (`media_role=camera_render` returns 422 for now); tiled/streaming core for the camera.
- render_id v2 includes the grain seed (found during the live run: the same DNG developed as two different frames had one id but different grain).
- Risks: grain/softness scaling is a modelling choice; LibRaw's scale vs the camera's changes the scanner key by ~0.2 EV; full-size test suite takes ~3 min.
- Next tasks: (1) camera_render uploads + reconciliation (P06); (2) `mfilmctl reprocess` with new renditions; (3) tiled fixed-point core variant and ARM cross-build (P05 prep); (4) SX510 colour calibration once DNGs exist.
- Owner action: SX510 HS firmware version and 2–3 CHDK DNGs; consent + path to publish into the live PhotoPrism library.
