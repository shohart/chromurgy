# 25 — Implementation Work Packages for Coding Agent

This is **implementation work**, not a request for another speculative roadmap. Execute host tasks immediately against the already working M-Film/Linux developer branch. Inspect existing code and tests before modifying them. Do **not** rebuild a second RAW engine or a second unrelated film filter system.

## CW00 — Audit existing implementation (first commit)

- Detect current repo structure, working renderer, film engine, recipe format, CLI, server API, and CHDK manifest support. Inspect actual source and pin revisions.
- Identify stage insertion points and ABI restrictions, threading, fixed vs floating point and color spaces.
- Create `docs/creative-integration-audit.md` listing exact existing functions/files to change and regression concerns; make minimal compatibility adapters rather than broad refactoring.
- Run existing tests, record results. **Deliver:** baseline + integration design, not just a plan.

## CW01 — Recipe v2 + profile registry (small standalone PR)

- Implement validated v2 schema and v1 migration with zero-look defaults.
- Add registry for eight Camera Looks, neutral, six optical effects and none; metadata/evidence tier, stable versions and complete defaults.
- Expand presets at roll sealing. Store canonical JSON/hash; expose via CLI/service.
- Tests: schemas, invalid ranges/unknown IDs, legacy v1 parity and roll manifest round-trip.
- **Deliver:** working parse/list/select tools with tests.

## CW02 — Camera Look core (Linux, mandatory)

- Implement common color-managed input interface / target output look engine separate from M-Film film color.
- Build functional parameterized looks for Leica M8, Leica M9, Fuji S5 Pro, Nikon D200, Pentax 645D, Ricoh GR III Positive Film, Sigma DP2 Merrill-inspired and Fuji X-Pro3 Classic Negative.
- Supply per-profile config and original code, no paid LUTs; no placeholders or identical parameter sets.
- Add look mixing and scene/test renders. Record visual evidence and caveats; initial `inspired` tier acceptable.
- **Deliver:** real full-res look-only JPEGs and tests for all eight looks.

## CW03 — Optical core (Linux, mandatory)

- Implement high-precision linear-light `soft_sun_glow`, `ricoh_hdf_diffusion`, `black_pro_mist_like`, `vintage_veiling_flare`, `film_halation_extra`, `orton_glow`.
- Implement multipass/multiscale diffusion, luminance knee, overlap handling, anti-clipping and optical strength, and prevent unintentional double film halation.
- Unit tests for spatial bright-source impulse, no-op, image-scaling invariance; visual regression contact sheets.
- **Deliver:** real full-res optical-effect JPEGs and per-stage timings.

## CW04 — Composition with existing M-Film film stocks (Linux, mandatory)

- Compose normalized RAW → optics → Camera Look → original M-Film film profile/color → single finishing stage. Maintain original M-Film semantics and color transforms.
- Support film-only, look-only, optics-only, all three, none; exercise film plus look combinations including Leica M9/Portra, Fuji S5/Portra, Ricoh Positive/HDF, Classic Negative/Sun Glow.
- Create `Golden Haze` preset as custom creative stack.
- **Deliver:** validated 12MP JPEGs and provenance from exact existing CLI pipeline.

## CW05 — Service/API, SD/USB/network round-trip and PhotoPrism (Linux, mandatory)

- Add creative profile endpoints and render-job creation/status/publish to existing receiver without breaking its ingest/sync methods.
- Accept camera roll recipe with RAW via server-first transfer, create full-resolution image, preserve previous renditions and attach recipe metadata; generate thumbnail/comparison.
- Publish selected rendition to PhotoPrism with atomic staging, idempotency and indexing; support re-render and publication switch.
- Add integration tests using local fixture import even if CHDK Wi-Fi not operational.
- **Deliver:** Linux service generates a PhotoPrism-visible artistic photo from a raw roll without camera-native rendering.

## CW06 — CHDK recipe selection/manifest (required after working camera port)

- Add on-camera selection of camera look, film, optical preset/strength; persist and sync v2 recipe.
- Show warnings if local developer does not implement requested stages; never falsely present local film-only results as full effects.
- Test on actual SX510 HS. **Deliver:** hardware-confirmed metadata/UI path, regardless of on-camera rendering power.

## CW07 — CHDK rendering feasibility (non-blocking, experimental)

- Prototype 3D LUT / curves at preview size and measure latency, RAM and battery. Only if safe try small multiscale bloom.
- If no reliable capability, disable local creative layers and keep offline film-only + server-full workflows. Record blockers.
- **Deliver:** measured feasibility report, not an assumed implementation.

## CW08 — Benchmark, compatibility and release

- Regression test original 72 film profiles, camera-look and optics workflows, old manifests and API.
- Build demo gallery; audit licenses and references; version preset bundles; generate reproducible release artifacts.
- **Deliver:** zipped release with documentation, migration notes, profile provenance and test report.

## Required final success gates

1. All 8 Camera Looks show actual distinct Linux outputs at nonzero strength.
2. All 6 Optical Effects produce meaningful, testable spatial/color behavior.
3. At least `Leica M9 + Portra 400 + Soft Sun Glow`, `Ricoh GR III Positive + HDF` and `Golden Haze` work through *the production server* from RAW to PhotoPrism.
4. Existing roll capture, originals, film-only development, sync, offline fallback and export remain functional.
5. CHDK stores/selects recipes; complex on-device effects explicitly remain experimental unless hardware-proven.
6. No stolen LUT packs, invented calibration data or fabricated physical camera tests.

## Reporting format

For each package: files changed; commands run; tests and source fixtures; sample output paths; exact measured metrics; what passes or is blocked; unresolved evidence questions. If hardware or proprietary samples unavailable, progress with synthetic / openly licensed tests and label quality confidence appropriately.

## v0.5 required delivery extension

The eight Camera Looks and six Optical Effects must be operable through the **Web Darkroom**, not only CLI/REST or a camera menu. A user must select raw source from browser upload or existing PhotoPrism album/folder, obtain reduced preview, develop full-resolution NEF/DNG and publish outputs to independently chosen PhotoPrism folder/album. Read [34](34-web-implementation-and-acceptance.md) for W01–W07 implementation packages and gates.

## v0.6 implementation waves — optical expansion inside current Linux service

After the existing CW01–CW05 server pipeline and v0.5 Web Darkroom are available, perform mandatory **Wave 1 / 2 / 3 / 5 / 10** according to [the detailed wave checklist](optical-engine/waves.md): W1 optical vignette and common registry; W2 source-based Ghosting and Starburst; W3 Anamorphic and seeded Light Leaks; W5 Vintage Glass (three real suboperators) and Lensbaby Sweet Spot; W10 Tilt-Shift, complete regression, performance and PhotoPrism. All seven new effects plus Vintage Glass must ship; **do not create a different service or optical selector**. These waves are Linux-only and must not be blocked by CHDK hardware testing. Old six effects have mandatory regression in every wave.


## v0.7 server-only curated combination presets

Implement and validate the 21 catalog entries in [35](35-curated-combination-presets.md) through the same existing recipe v2, optical graph and Web Darkroom. Activate per [37](37-combo-waves-and-acceptance.md) in waves 1/2/3/5/10. Preserve all legacy composite IDs and make every proposed strength editable. Do not call any exact trio community verified without direct source evidence.
