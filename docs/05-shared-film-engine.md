# 05 — One Shared Film Engine: Algorithm and Render Parity

## Mandatory design principle

The Linux developer and on-camera offline developer must compile the **same portable C film core** (same source revision, profile math, seed derivation and profile parameter bundle). Two independently written approximations (for example a server Python PIL filter and a camera Lua filter) **do not satisfy** this requirement.

The M-Film repository's camera-side code and film definitions are the upstream basis. Its closed-source `Darkrooms` desktop app is **not part of the source code** and must not be reverse-engineered as a requirement or included as a runtime dependency. The new host developer is an independent open implementation built from legally reusable upstream camera code.

## Shared core contract

Example C interface, **proposed only**:

```c
int mf_core_init(const mf_profile_bundle *bundle, const mf_recipe *recipe);
int mf_core_process_tile(const mf_linear_tile *input,
                         const mf_tile_context *context,
                         mf_output_tile *output);
void mf_core_shutdown(void);
```

`mf_linear_tile` must specify channel order, linear encoding, numerical range, pixel origin, border/overlap, row strides and white balance / color-space metadata. The film core must not read the SD card or call CHDK globals directly. It must be deterministic for the same tile origin, normalized pixels, versioned profile and seed.

Both builds should share the same static recipe object and test vectors. Optional host acceleration is permitted **only** if it matches the documented reference output tolerances; otherwise it is a separately named backend.

## Processing stages

1. Input adapter: DNG decode, black/white normalization, defect correction and demosaic (platform-specific with parity tests).
2. Camera-to-common space: documented linear RGB mapping, reference white/illuminant, highlight handling, exposure normalizer.
3. **Shared film core**: tone, profile color model/LUT, contrast, grain, halation and softness in documented sequence, with exact parameter calibration.
4. Output adapter: tone encoding, resizing only when explicitly requested, JPEG encoding/metadata and target color profile (usually sRGB).

Film effects can need neighborhood pixels; tile overlap or streaming/multipass design must account for halos, blurred halation and blur, without seams.

## Profile versioning

For every rendition persist: `film_profile_id`, `profile_bundle_hash`, `film_core_git_commit`, `film_core_abi_version`, `recipe_schema_version`, `grain_seed`, `raw_adapter_version`, `demosaic_mode`, `wb_mode`, `output_width`, `output_height`, `jpeg_quality`, `developed_by` (`linux` / `camera`), `development_timestamp`, original SHA-256.

The camera and Linux must **refuse silent profile mismatches**. If bundles differ, server can (a) render using the exact archived bundle, (b) request/copy compatible bundle, or (c) report mismatch and queue re-development; **never silently substitute a newer profile** for an old roll.

Third-party LUTs require a separate rights audit (M-Film includes upstream film LUT references). Only distribute verified redistributable assets; missing LUTs should produce explicit unsupported-profile errors.

## Deterministic grain and `render_id`

Generate per-frame seed from a cryptographic hash of `device_id + roll_id + frame_id + profile ID + recipe_version + user_seed`, not from wall clock. Implement coordinate-based pseudo-random grain or deterministic tiled RNG so chunk/tile order does not change the look.

Render identity = hash of canonicalized `original_asset_hash + recipe_json + film_core_version + profile_bundle_hash + target_output_spec + input_normalization_version`. A camera offline JPEG at 1280 px and server JPEG at 4000 px are **distinct renditions** of the same frame.

## Parity criteria

- Exactly identical profile metadata, processing order, LUT content and deterministic seeds between builds.
- For the **same normalized input tile and same output settings**, compare stage outputs: expected pixel differences from fixed/float paths must be bounded; target `>=99.9%` of 16-bit channel values within ±1 where fixed-point reference mode is used; any exception documented.
- For end-to-end DNG processing across distinct decode paths, use image quality comparisons (color patches, neutrals, grain statistics, highlight behavior and tile seams). Provisional thresholds such as median DeltaE2000 <= 1.5 and SSIM >= 0.98 are **targets to calibrate against approved fixtures**, not retroactive proof of equivalence.
- The same algorithm does not imply byte-identical JPEG files due to metadata and encoder differences. Compare normalized pixel data and film-stage outputs.
- A lower-resolution offline version must preserve profile semantics, but will not have identical grain microstructure to a larger server rendition; test profiles at matched output sizes for parity claims.

## Exported user preference

Canonical output: Linux 4000×3000 JPEG (for 4:3) when valid source geometry permits. On camera: measured safe output and explicit quality label (`offline_preview`, `offline_standard`, etc.). Original is always retained so Linux can re-develop later.
