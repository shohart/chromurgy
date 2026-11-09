# Optical Effects Engine — In-place Integration, Color and Compositing

**There shall be one M-Film server renderer.** New optics are feature modules inside the existing creative pipeline, not a separate postprocessor. Preserve old film-only, camera-look-only, and existing six-effect jobs byte-for-byte when their engine version is pinned, or document and explicitly version migration when exact compatibility is impossible.

## Architecture / component contracts

Existing HTTP/API and job queue remain authoritative:

```text
Browser upload / PhotoPrism asset / M-Film roll
  -> existing authenticated job / source resolver / original digest
  -> existing RAW + camera-ICC normalization (scene linear, HDR headroom)
  -> integrated optical staging graph (old 6 + new 7 + Vintage Glass components)
  -> Camera Look (existing)
  -> M-Film Film Stock (existing 72 profiles)
  -> film grain / halation finishing (existing; no duplication)
  -> output color transform, encode, source EXIF + recipe sidecar
  -> existing history, cached preview, PhotoPrism publication
```

Maintain one `OpticalEffectRegistry` whose descriptors include `id`, `implementation_version`, `parameters` (range/default/domain/units), `supported_source_modes`, `mask_capabilities`, `stage_type`, `preview_cost`, `supports_batch`, `license_reference` and recommended usage labels. The API does not claim an effect is available until the production Linux worker can render it.

Define narrow interfaces (illustrative, not a new separate HTTP service):

```c
typedef struct mf_optical_ctx mf_optical_ctx;
typedef struct mf_image_tile mf_image_tile;
typedef struct mf_optical_effect mf_optical_effect;

mf_status mf_optical_prepare(mf_optical_ctx*, const mf_optical_effect*, const mf_scene_stats*);
mf_status mf_optical_render(mf_optical_ctx*, const mf_optical_effect*, const mf_image_tile*, mf_image_tile*);
void mf_optical_release(mf_optical_ctx*);
```

`prepare` computes global source detection / random fields / blur pyramids / full-frame stats once per render where needed. `render` works with stable global tile origins and declared halos. Single-frame operators may use whole-frame processing if bounded memory and benchmark gates justify it. The same descriptor/implementation is called from CLI, REST worker, and Web Darkroom preview.

## Physical/numerical ordering

Do not impose user-defined arbitrary execution order: validate a dependency graph and serialize canonical order into actual execution provenance. A suitable reference graph:

1. RAW decode, sensor black/white, demosaic, white balance, color characterization, exposure, lens *technical correction*.
2. **Geometry** (Vintage Glass barrel distortion), then **channel warping** (Vintage Glass CA), then **spatial softening / focus** (`vintage_glass_edge_softness`, `lensbaby_sweet_spot`, `tilt_shift_miniature`). Document whether chosen creative distortion occurs before or after crop/rotation; use one orientation convention everywhere.
3. **Source-map detection** on an appropriate early scene-linear image (before strong tonemapping): compute luminance, localized bright-source candidates and optionally a source-energy pyramid. Preserve source positions through geometric warps via the recorded transform; recompute when necessary.
4. **Pre-tone source-dependent light optics:** `lens_flare_ghosting`, `starburst_cross_screen`, `anamorphic_streak`, `soft_sun_glow`, `ricoh_hdf_diffusion`, `black_pro_mist_like`, `vintage_veiling_flare`. `orton_glow` is a broad spatial branch with explicitly declared exposure-domain placement.
5. **Pre-tone edge/film phenomena:** `analog_light_leaks` models an extra light exposure in scene-linear space; film-specific `film_halation_extra` may need film-domain placement, handled by the film-finishing stage rather than duplicated here.
6. **Lens vignetting** is an exposure adjustment. Default to placement after creative geometric warp but before artistic tone mapping, with explicit `vignette_policy` resolution; this can be expressed as a dependency edge rather than a rigid global index.
7. Existing Camera Look and M-Film Film Stock stages in their established validated order; existing grain/halation finishing, output gamut mapping and encoding.

This is an initial ordering to be confirmed with existing code and golden-master images. **An individual effect belongs to a domain and a graph node**, not just a JSON list position. If physically motivated order conflicts with actual current M-Film core, document and regression-test the chosen integration. Optical halos should mostly act on scene-light before display gamma/tone compression; any film-layer-specific halation is deliberately separate.

## Compositing, masks, lighting sources

- A linear RGB source and effect branch `E` may blend as `result = base + strength * contribution`, or with physically motivated transmission/veil models. Nonlinear screen overlays are only allowed after explicit domain conversion and must be documented. No uncontrolled sRGB addition or opaque texture compositing.
- The original image must survive strength 0 and `enabled=false` without resampling when no geometry-changing stage is active. For fractional strengths, geometry operators blend between an original-resampled and warped image **only** with explicitly specified edge policy; ensure no double-image artifacts at small intensities.
- Source detector: luma soft knee + connected bright compact components / local maxima + spectral/spatial radius filter; rank by brightness, energy and contrast, cap source count, keep all source positions normalized; `confidence` exposes reason for selected candidates. Preview shall offer editable source handles and ability to ignore a candidate.
- `source_selection` (recipe per effect): `auto | manual | auto_plus_manual | off` and `points` with `x,y,weight,radius`. Manual mode must bypass ambiguous detection; mixed mode de-duplicates near-coincident points. An empty source set means neutral result for source-dependent effects, not forced decorative orbs.
- Masks: all effects support basic optional alpha mask (`whole_image`, `radial`, `linear`, `brush_mask_asset_id`) when existing renderer supports mask resources. In first release use normalized centers and bands for focus effects; brush upload is a later gated enhancement. Server must authorize ownership of mask assets.
- Guard effect combinations: do not forbid combinations without mathematical reason, but show soft UI warnings for `soft_sun_glow + ricoh_hdf_diffusion + black_pro_mist_like`, `starburst + anamorphic_streak`, and duplicate film/optical halation.
- Implement explicit halation handling: `halation_policy: film | optical | stacked | disabled`. `stacked` must be user-intentional. Use analogous `vignette_policy` when optical vignette and M-Film film vignette coexist.

## Resource and performance strategy

- CPU reference implementation is the ground truth for parity; optional vectorized/GPU execution after correct CPU golden outputs.
- Blur pyramid shared across related effects only if their source mask, color-space, and stage placement match. Avoid incorrect reuse across Color Look/Film Stock boundaries.
- Precompute all long streaks/stars/ghost maps from source centroids and limiting ROI where possible. For 45MP NEF and multiple sources, use bounded memory chunking and configurable max sources.
- Recycle buffers, use FFT convolution only when it wins for actual kernel sizes, run stage-specific memory/time counters, cancellation checkpoints, and output error codes (`invalid_recipe`, `missing_source`, `unsupported_mask`, `memory_limit`, `decode_failure`, `publish_failure`).
- Full-res render always uses RAW (NEF/DNG supported via the existing decoder); do not apply a filter to camera JPEG as a silent fallback when RAW input was selected.
- Version `effect_id + implementation_version + parameter defaults + bundle_hash + stage graph version`; hash together with existing source digest, recipe, seed, output dimensions, pipeline build and output format. Publishing to another album must **not** change render identity.

## Compatibility / migrations

- A recipe with only the original six effects must validate unchanged. Unknown new fields on an old client are not required; new fields optional with defaults.
- Keep schema number `2` because the data model extends existing optional fields compatibly. If an implementation requires an incompatible change, introduce v3 explicitly and supply migration + historical render path; do not silently reinterpret historical presets.
- Original six IDs may not be aliases to the new modules. `vintage_veiling_flare` remains contrast wash; `lens_flare_ghosting` alone adds positional ghosts. `film_halation_extra` does not become `analog_light_leaks`.
- Existing `optical.stack` `maxItems=8` must be raised to at least 16 so all new effects may be combined if deliberately requested. The UI may recommend a smaller practical number but may not arbitrarily reject valid 13-module recipes.
- Only Linux server backend changes are in scope for this delivery. Existing camera manifests can carry effect IDs opaquely but **do not** require or modify CHDK renderer or camera UI.
