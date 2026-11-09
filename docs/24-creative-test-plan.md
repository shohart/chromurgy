# 24 — Creative Engine Tests, Quality Gates and Evidence

## Build/test matrix

Required baseline: Linux x86_64, Python orchestration if used, portable CPU C engine, tests runnable offline, fixture images in lawful redistribution format or generated charts; CHDK hardware tests separate and explicitly NOT TESTED until run.

### Functionality — MUST PASS

- Every **eight named Camera Look IDs** and `neutral` resolves and actually changes controlled calibration images when strength > 0 (unless neutral). No placeholder labels or blank slots.
- Every **six optical modules** and `none` resolves and changes appropriate fixture images. For a flat low-luminance fixture at low strengths, spatial-light-effect contribution is bounded as documented.
- Every shipped composite preset loads and develops at least one 12MP (4000×3000) SX510-compatible DNG to JPEG once real sample is available; until then use a public test DNG and mark SX510-specific tests BLOCKED.
- Camera-only, film-only, optics-only, all-three and all-none operations are supported and produce different hashes when meaningful.
- `strength=0` returns identical output to bypass within declared float tolerance.
- User controls use range validations; unknown profile ID must fail rather than silently switch to neutral.
- v1 recipe migration produces legacy-equivalent film-only output and maintains film grain/halation controls.
- Full-resolution output must not be a resized low-resolution preview. Test high-frequency resolution chart; compare edge frequency against baseline.
- Crop, orientation, EXIF date, ICC/sRGB gamut metadata, bit depths and raw source integrity verified.
- 100% camera-look strength plus high-contrast film must not routinely overflow or create black/white channel wraps; gamut mapping should be stable and tested.
- All PNG/TIFF/validation exports correctly use the designated output gamma/profile.

### Quality — initial measurable targets

- **Tile seams:** max seam error <= 2/255 in 8-bit rendered border under same scene and recipe, unless verified reference demonstrates legitimate sample mismatch; aim 0.
- **Determinism:** same source+recipe+engine+threads+tile shape gives same pixels/grain; camera-vs-host exactness is required only for shared film core on normalized identical tiles within original spec tolerances.
- **No-op baseline:** use per-pixel difference thresholds and image metadata checks.
- **Camera Look diversity:** selected color chart, portrait, sunset, city, foliage; for each look record chroma/contrast/tone-delta vs neutral. Visual reviewers must confirm intentional distinctness on at least 3 of 5 categories.
- **Optical effects:** bloom spatial influence proven by impulse and bright-window fixture; low-intensity unaffected patches not materially altered, no hard halo/contour or obvious edge ghosts.
- **Hold-out calibration:** any claim of `measured` or `validated` look requires a held-out reference corpus, documented illuminants, camera settings and color metrics (DeltaE2000 distribution, patch median/95th percentile, optionally perceptual LPIPS). Do not invent accuracy numbers for inspired profiles.
- **Performance:** record p50/p95 for 12MP per stage on reference Linux CPU, RSS and bytes written; no hard time quota until baseline evidence exists.

### Human visual QA sheet

Generate contact sheets for each look (neutral, 25%, 50%, 100%; and combined with Kodak Portra 400), and each optical effect (no effect, 25%, 50%, 100%) from multiple sources; include edge crops and daylight/tungsten/night scenes. Reference panel must be traceable to asset license and revision. Use sRGB color-managed preview display for review.

### Camera hardware gates

- RCP1: v2 recipe saved to SD, power-cycle restore; on-screen profile and optical selection, manifest read by Linux.
- RCP2: RAW transferred unchanged; full recipe reaches server; server render matches CLI recipe.
- RCP3 (experimental): small on-camera LUT stage does not crash, preserves raw and measures RAM/CPU.
- RCP4 (experimental): bloom/HDF offline render if safe; store applied stages and compare matched-size render to host. Failure does not block release, but implementation may not falsely claim parity.

### Failure/resilience tests

Corrupt recipe JSON; unknown or outdated preset; wrong bundle digest; 0-byte RAW; missing ICC; offline camera with unavailable optic; partial upload; rerender collision; PhotoPrism index failure; system restart mid-rendition; repeated idempotent job. RAW originals never modified or deleted.

## Evidence folder layout

`tests/fixtures/` synthetic chart / licensed test images; `tests/golden/` versioned stage vectors; `reports/creative/` visual contact sheets and metrics; `reports/chdk/` actual camera probes. Every result tagged `PASS`, `FAIL`, `BLOCKED`, or `NOT TESTED`.

## v0.6 mandatory optical expansion gates (server only)

The optical suite now covers **the original six PLUS seven new standalone effects and three Vintage Glass suboperators**. The old six golden baselines run after each Wave 1, 2, 3, 5 and 10. Add per-effect mechanical/no-op/source/seed/tiling tests and preview-to-full geometry parity using [the Linux optical validation matrix](optical-engine/validation.md). Wave 10 requires every required module in production Linux worker, existing Web Darkroom preview, real full-resolution render and PhotoPrism publication, not just effect metadata or UI cards. CHDK changes are not part of these gates.
