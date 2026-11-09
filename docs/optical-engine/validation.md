# Optical Effects Engine — Linux Validation, Quality and Performance

This is a required extension of existing [`docs/24-creative-test-plan.md`](../24-creative-test-plan.md) and [`docs/34-web-implementation-and-acceptance.md`](../34-web-implementation-and-acceptance.md), not a separate QA service.

## Test assets

- Synthetic linear floating-point charts: black/white/saturated gradients; discrete bright point at center/corner; two bright points; highlight disk and diffuse white wall; concentric circles; rotated grids; portrait-sized eye/skin/hair detail; cityscape-like horizontal lines; high-angle miniature street fixture; signal impulse and masked region.
- Real rights-cleared RAW/NEF/DNG from at least two cameras when fixtures available, including a Nikon D5100 NEF and Canon SX510 HS DNG if supplied. Unknown input raw must be marked `BLOCKED`, not invented. Preserve privacy and do not commit personally identifiable imagery without permission.
- Cases: day/sunset/night, indoor tungsten, backlit portraits, light-free image, empty/exhausted source list, high-resolution portrait orientation, wide aspect ratio, rotated EXIF, multiple bright sources, crop at image edge.
- Version `tests/golden/optics/` linear stage vectors, preview/final images, resolved recipe, registry bundle hash and reference engine commit.

## Existing six regression gate (every wave)

For each existing effect ID, render old v0.5 recipe, including strength 0 / 0.5 / 1 and relevant Film Stock. Compare to pinned historical outputs in stable reference path. A reworked kernel must not silently alter old saved recipe output: version the effect and keep old implementation selectable for archive rerenders, or provide explicit migration with human-approved visual baseline. Validate halation policy and overlap warnings, and existing `Golden Haze` preset.

## New effect-specific mechanical tests

| Effect | Required objective checks |
|---|---|
| `optical_vignetting` | monotonic radial exposure falloff; center control; elliptical symmetry; ±0.02 EV outside affected area at weak default where applicable; no-op at zero |
| `lens_flare_ghosting` | geometry moves with manual source; ghost location tracks axis; count and aperture changes; no-source neutral output; not equal to veiling-only render |
| `starburst_cross_screen` | count of distinct oriented ray arms matches selected 4/6/8; rotated rays respond to angle; white wall yields no false galaxy |
| `anamorphic_streak` | source-aligned directional extension; 0° vs 90° orientation; blue/white tint; no-source neutral and no clipping overflow |
| `analog_light_leaks` | deterministic seed, anchored edge; preview/full normalized mask overlap; output changes with `seed`; 0 intensity identical to baseline |
| `lensbaby_sweet_spot` | preserved center sharpness and falloff; focal center moves; no ugly hard rings; blur bounded |
| `tilt_shift_miniature` | sharp band angle and position; blur gradient both sides; no forced saturation; orientation/crop invariance |
| Vintage Glass CA | chromatic displacement grows toward edges, negligible at center; no invalid border samples |
| Vintage Glass softness | point spread increases toward edge, central sharpness preserved |
| Vintage Glass barrel | calibrated grid deformation sign/magnitude; no holes; consistent crop policy |
| Compound Vintage Glass | expands to real operators + optional vignette; each subcomponent can be toggled; saved preset reproducible |

### Required global invariants

1. **Neutral:** `enabled=false` or `strength=0` reproduces bypass pixels within declared float tolerance and does not mutate RAW, EXIF, thumbnails or original timestamps.
2. **Determinism:** same source checksum, recipe, profile/engine versions, seed, output spec produces identical normalized decoded pixels (and ideally bytes with controlled metadata). Tile shape / worker count must not alter random masks.
3. **Preview/final spatial correspondence:** vignetting centroid, star angles, streak orientation, flare points and leak pattern shape coincide in normalized crop coordinates within 1% of image diagonal; high-frequency grain need not be identical if explicitly downsampled.
4. **Tile overlap:** target max seam pixel difference <=2/255 in equivalent 8-bit image, aim zero; no lens warp discontinuity or Gaussian blur hard seams.
5. **No hallucinations:** no automatic ghost/star/streak in a scene without an identifiable compact source; manual mode is allowed and documented.
6. **Range robustness:** reject negative radii, non-finite values, invalid enum flags, wild output dimensions, invalid points, >16 stack items or abusive source counts with 4xx/422 and readable message, no crash.
7. **Color validity:** scene linear remains floating-point HDR through optical layers; sRGB/P3 ICC and tone mapping applied only as needed; no RGB overflow wrap/clamp artifacts, preserve natural skin under moderate effects.
8. **Mixing:** test at least old HDF + new Ghosting, old Veil + new Starburst, old Glow + new Anamorphic, old Halation + Film Stock, Vintage Glass + new Vignetting, Tilt-Shift + Film Stock. Warnings on conflicting overlaps but permitted by explicit user choice.
9. **Full resolution:** result generated from original RAW and contains actual source spatial detail; upscaled preview must fail an MTF/resolution-chart check.
10. **PhotoPrism:** deliver with intended destination album/folder and recipe metadata, idempotent publish, no duplicate reindex, no overwrite of source RAW.

## UI tests

- Old saved recipe opens and renders with unchanged optical UI labels and parameter semantics.
- Existing Step 4 shows 13 optical effect cards organized by group; Vintage Glass composite appears there with Advanced controls, not a new main page.
- Light-source overlay manual selection and removal; focus point and tilt band handles correctly patch recipe and refresh preview.
- Original-vs-effect slider and side-by-side comparisons work for each and stacked selections; cancellation while preview/final running cleans temp data.
- PhotoPrism source via RAW-backed album and folder, direct `.NEF/.DNG` upload, full-quality export and album association preserve existing behaviors.
- Output history shows effect versions, applied stack, source checksum and chosen album/folder, supports rerender to a new version without deleting the old.

## Performance and reliability

- Measure for each stage and composite: p50/p95 wall time, peak RSS, temporary disk bytes, parallel worker CPU, output size at preview, 12MP source and largest available 24–45MP NEF. Note exact reference host hardware and versions.
- Do not invent universal millisecond targets. Set target after baseline; require bounded memory, cancellation, and predictable queue behavior under large batch jobs and system restart.
- Compare CPU reference path with SIMD/GPU if used; test quality tolerance and determinism. Control `num_threads`, tile size, image pyramid scale and auto-source count in reproducibility runs.
- Fuzz parser/recipe/asset references; include negative tests for unsupported raw encoding, missing ICC, malformed masks, invalid source coordinates, extreme geometry coefficient, missing PhotoPrism credentials and interrupted indexing.
- Run CI with old six regression suite after every wave; no waiver because new effect was added.

## Evidence and traceability

For all 13 effects and Vintage Glass: attach control definitions, source sample license, reference result image, actual M-Film worker output path, tested recipe, commit ID, engine version, source hash, pixel metrics, timing and known limitations. Human visual approval must check exaggerated/max strengths plus restrained default strengths. Never claim physical accuracy of trademarked filters or camera optics without measured evidence.
