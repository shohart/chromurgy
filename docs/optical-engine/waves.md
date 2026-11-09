# Integrated Server Optical Engine — Mandatory Delivery Waves 1 / 2 / 3 / 5 / 10

**All listed work is mandatory.** Wave labels deliberately follow the requested sequence (1, 2, 3, 5, 10). There is no standalone subsystem and no CHDK/camera implementation in these waves. Work occurs in the existing Linux RAW processing service, existing six-effect engine, Web Darkroom and PhotoPrism publication workflow.

## Baseline before Wave 1

- Audit current deployed repository, not just the specification. Record commits for existing M-Film core, all six optical modules, real endpoint names, 72 Film Stocks, camera looks, render-recipe-v2 schema and job DB migrations.
- Capture golden images/JSON for original six individually and combined with known film profiles, including old saved recipes, preview and PhotoPrism output. Preserve original assets and tests.
- Create branch, migration inventory and a `feature_flags.optical_v06` for incomplete effects; no unfinished effects in production discovery API.
- Add deterministic fixtures for a single light, multiple lights, backlit portrait, city night, uniformly white scene, dark scene, geometric grid, tilt-shift city and RAW sources in NEF/DNG.
- Add effect registry descriptor type, shared source detector contract, stable coordinate convention and numeric validation before individual effects.

## Wave 1 — Engine foundation and everyday lens character

**Implement:** `optical_vignetting`, initial effect registry, consistent preview/full normalized coordinates, `vignette_policy`, mask management, recipe-v2 schema expansion/backward compatibility, UI integration in existing Step 4.

Tasks:
1. Wire one descriptor registry through Linux worker, CLI, Web Darkroom and `GET /api/v1/creative/optical-effects`; expose old six unchanged.
2. Add linear-light radial/elliptical vignette with adjustable center/radius/feather/exposure, per-effect strength and documented stacking with existing stock vignette.
3. Implement source and recipe provenance/versioning scaffolding. Expand stack capacity to 16.
4. Create old six regression harness, strength-zero/no-op tests, synthetic radial gradients, full-resolution 12MP and available Nikon NEF fixtures.
5. Implement preset save/load for existing optical controls without changing previous defaults.

**Exit gate W1:** old six still work and their historical recipe JSON validates; `optical_vignetting` changes correct pixels at all supported sizes; web preview/full job/PhotoPrism publication works; no new server endpoint required for normal rendering.

## Wave 2 — Physically motivated bright-source optics

**Implement:** `lens_flare_ghosting`, `starburst_cross_screen`, production shared bright-source detector, preview interaction handles, source selection/override.

Tasks:
1. Detect compact energetic bright sources from scene-linear stats with documented thresholds, confidence and count limits. Support manual and auto source modes; cache normalized coordinates.
2. Render source-position-linked geometric ghosts via aperture/iris PSF approximations, avoid fake random static stickers and broad veil aliasing.
3. Render 4/6/8-point starburst via directional convolution or sparse PSF kernels, validate rotations, multiple sources, rays at frame edges.
4. Reuse existing multiscale bloom/veil engine where possible but keep effect identifiers, semantics and test outputs distinct from existing `vintage_veiling_flare`.
5. Add existing Step 4 image handles and `No light source detected` UI state; preserve pipeline's photo-indexing and recipe hashing.

**Exit gate W2:** Ghosting and Starburst both visibly and independently work with old six, multiple fixture types and user-selected sources; full-resolution output, preview geometry and source coordinates match within stated tolerance.

## Wave 3 — Cinematic streaks and analog exposure artifacts

**Implement:** `anamorphic_streak`, `analog_light_leaks`; robust deterministic stochastic engine.

Tasks:
1. Develop long directional streak kernel with angle, color, source mask and energy limits; integrate with source detector, optional manual lights, 0°/90° rotation.
2. Procedural edge-attached warm fog/leak masks controlled by `seed`, per-asset salt and normalized global coordinates; no commercial texture overlays.
3. Ensure a light-leak preview uses same pattern composition and spatial features as full-size render. Validate multiple portraits/landscapes, rotated images, cropped photos and batches.
4. Add UI controls for angle/length/tint, leak edge/coverage/warmth, fixed seed/reshuffle action. Keep legacy Film Stock grain/halation seeds unaffected.
5. Benchmark high MP RAW NEF/DNG and multiple simultaneously selected effects; profile memory/cancellation behavior.

**Exit gate W3:** all five new standalone effects implemented to date (Vignetting, Ghosting, Starburst, Anamorphic Streak, Light Leaks) are available together with old six; deterministic regeneration, unmodified originals, finished PhotoPrism output and complete provenance.

## Wave 5 — Vintage Glass and selective-focus tools

**Implement:** `vintage_glass` *compound preset*, its three real operators (CA, edge softness, barrel distortion), and `lensbaby_sweet_spot`.

Tasks:
1. Build inverse-map geometric warp with bounds/crop and calibration grid; avoid cumulative geometry corruption.
2. Build radial lateral chromatic aberration and edge softness as independent versioned operations, profile under same common engine.
3. Compose `vintage_glass` into three operations with optional `optical_vignetting`, using expansion hash in saved recipe/provenance; expose as one selectable preset with Advanced component controls.
4. Implement movable sweet spot focus mask with progressive blur, interactive preview focus handle, safe transitions and test portraits/flora.
5. Ensure existing Camera Look and Film Stock composition remains stable; add tests combining Vintage Glass + M-Film film + previously shipped diffusion.

**Exit gate W5:** Vintage Glass is genuinely geometrical/spatial, not a LUT; each of three operators can be detected in individual tests; Lensbaby focus point moves correctly. All previous old and new effects still pass; stack rerenders are reproducible and indexed to PhotoPrism.

## Wave 10 — Tilt-Shift, full integration and release

**Implement:** `tilt_shift_miniature`; complete API/web hardening, performance and visual QA for **all** effects.

Tasks:
1. Implement rotatable sharp band with progressive variable blur and controlled optional vividness. Add preview band handles and final 12/24/45MP tests as supported by source images.
2. Test composition permutations: all old six + new 7; all required camera looks/films; no-op and double-halation/double-vignette guards; 16-item stack; calibrated/no-source behavior.
3. Validate direct browser upload NEF/DNG, PhotoPrism original folder/album selection, rerender previous roll, output folder+album, index and existing album UID association.
4. Color-manage all effect outputs; audit deterministic source analysis, coordinate handling after crop/rotation, preview/full spatial scaling and mixed hardware fallback differences.
5. Produce release preset bundle, before/after contact sheets, documentation, performance report (p50/p95, peak RSS, 12MP and largest test RAW) and all schema/API examples.
6. Turn off feature flags only after each module passes its exit gate. Cleanly migrate historical v0.5 recipes; ensure user can open old Web Darkroom history.

**Exit gate W10:** 13 standalone effects (original 6 + new 7) and 1 Vintage Glass compound preset (with 3 functioning operators) all installed in *the existing Linux server*; no stubs; all exposed through the existing Optical Effects step; every required effect produces full-quality output and publishing flow; no dependence on CHDK effort.

## Per-wave reporting format

For each numbered wave supply: code commit(s); replaced/added functions; effect registry descriptors and parameter ranges; sample original/processed outputs; screenshots of existing Web Darkroom; migrations; test commands and results (`PASS/FAIL/BLOCKED`); CPU/RAM benchmarks; exact PhotoPrism publication evidence; limitations; next wave hand-off. Do not call a wave complete based solely on JSON descriptions or static UI screenshots.

## Prioritization note

The sequence is practical and test-driven; all requirements remain in scope. Agent may reorder atomic subtasks to accommodate working code, but **must not silently defer Wave 10 or remove specialized modules**. If performance is poor, optimize or explicitly lower quality in a labeled preview mode; full-resolution capabilities and deferred job execution remain mandatory.


## v0.7 curated combo overlay on these waves (SERVER ONLY)

After each effect wave has passed, activate catalog entries with `wave_required <= current_wave` only if their film IDs resolve and their own visual tests pass. Do not treat a catalog entry as evidence that an operator is implemented. Canonical source: [`contracts/curated-combos-v07.yaml`](../../contracts/curated-combos-v07.yaml). Tasks and gates: [37](../37-combo-waves-and-acceptance.md). All existing v0.6 effect development remains mandatory.
