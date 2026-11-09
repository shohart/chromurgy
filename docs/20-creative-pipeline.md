# 20 — Color-Managed Creative Render Pipeline

This document specifies data flow for the **Linux full-quality backend**. Existing original M-Film film-profile algorithms remain the film component; do not replace them with arbitrary generic presets. Actual upstream assumptions must be inspected and documented before adaptation.

## Stage sequence (reference v1)

1. **Read** source RAW/DNG, verify file and ingest hash; preserve intact.
2. **Normalize** CFA: black subtraction, defect correction, white level, demosaic, as-shot/reference white balance, optical black/active crop, source camera characterization. Output linear Rec.2020 RGB, D65, floating-point or defined fixed-point equivalent. If another working space is chosen, document primaries/transfer/white and support all the same contracts.
3. **Exposure** compensation and scene-linear headroom. Any highlight reconstruction algorithm is optional, separately versioned, and must never falsely promise restoration of clipped raw channels.
4. **Pre-tone optical model:** veiling flare, bright-source bloom, HDF-like diffusion / soft sun glow / Orton-like diffusion. Work in scene-linear/light-referred space before output tone encoding. For glow driven by highlight energy, compute a smooth knee mask; avoid binary hard thresholds.
5. **Camera Look** rendering: apply per-hue/per-luminance transforms, tonal shoulder and toe, color separation and calibrated contrast. Convert to the exact intended working domain (linear, log or perceptual) at each operation and document conversions. Blend strength in a declared scene/perceptual space.
6. **M-Film Film Stock**: adapt existing film LUT/model into its required domain; preserve its grain/halation semantics. Separate film-color mapping from film-grain/halation timing when upstream code permits; preserve its verified look via reference regression. Film `none` is neutral.
7. **Post-film look finishing:** film-specific halation (if not already produced), film grain and softness as required by authentic M-Film. Apply any single requested halation exactly once; choose whether optical or film halation owns the effect in recipe validation. A requested additional halation layer must have an explicit `stack_halation=true` override and warning.
8. **Output** scale, gamut map with hue preservation, encode to sRGB JPEG or 16-bit TIFF, carry EXIF capture metadata and a sidecar with all recipe/profile versions. Never silently upsample a camera preview to full resolution.

**Pipeline invariant:** each stage declares input/output color space, bit depth, transfer and dynamic range. Prohibit untracked 8-bit sRGB round trips in the middle of rendering. Keep camera-neutral test fixture output identical when optional creative stages disabled.

## Core abstractions

```c
// Proposed API, adjust after inspecting actual M-Film and CHDK ABI.
typedef struct {
    const float *rgb;       /* planar or interleaved: document */
    uint32_t width, height, stride;
    uint32_t origin_x, origin_y;
    uint32_t halo_left, halo_top, halo_right, halo_bottom;
    const char *color_space_id; /* e.g. linear_rec2020_d65 */
} mf_float_tile;

typedef struct {
    const char *camera_look_id;
    float camera_look_strength;
    const char *film_profile_id;
    const char *optical_preset_id;
    float optical_strength;
    uint64_t random_seed;
} mf_creative_recipe;
```

Host modules must expose separate stage hooks for profiling/testing, e.g. `input`, `optical`, `camera_look`, `film_color`, `film_finish`, `export`, and export a shared recipe-render entry point. Film core and camera-look code may be written in portable C/C++; wrap in Python only for server operations. Host-only GPU acceleration is optional; CPU baseline is mandatory.

## Large-image strategy

- Render at source-native 4000×3000 JPEG output dimensions for 4:3 SX510 captures when the DNG active area supports it (Canon's official JPEG size). Read actual DNG metadata; do not equate raw sensor dimensions with JPEG dimensions.
- Implement multiscale Gaussian/separable convolution at reduced resolution for far-field glow and full-resolution/high-frequency refinement. Define radius in **normalized output-diagonal units** to preserve appearance across 5/8/12MP. For tiles use overlap and crop, with quantitative seam tests.
- Use scene-linear high precision (float32, optional float16 in thoroughly tested accelerated paths). Do not clamp HDR scene-linear values prematurely.
- Bounded memory/threads, cancellation checkpoints and per-stage timers are mandatory. Host can use RAM generously, but avoid unnecessary copies.
- For preview, use a comparable downsampled version of the *scene-linear* source (not a cached camera JPEG with baked Canon rendering); export matched preview and full-res previews in tests.

## Deterministic and reproducible results

- Every render identified by hash of original content digest, normalized canonical recipe JSON, all code/profile/build versions and output spec.
- Noise/grain use coordinate-dependent deterministic RNG. Distinct tile sizes and worker thread counts must not alter grain placement.
- Preset layering order fixed and versioned; default settings preserve no-look / no-effect baseline.
- Camera-local fallback is **not** required to support spatial effects until benchmarks prove feasibility, and must record actual applied stages.

## Example processing pseudocode

```text
raw = decode_and_normalize(source_dng, source_profile)
light = optical_engine.apply_pre_tone(raw, recipe.optical)
rendered = camera_look_engine.apply(light, recipe.camera_look)
film = mfilm_color_core.apply(rendered, recipe.film)
finished = finish_film_grain_halation(film, recipe, deterministic_seed)
export_jpeg(finished, color_manage='sRGB', exif=source.exif)
record_provenance(source_digest, recipe, actual_modules, timings)
```

Avoid treating `soft_sun_glow` / `ricoh_hdf_diffusion` as mere white overlays or fake decorative lens flares. Test against bright windows, the low sun and specular reflections with dark surrounds.

## v0.6 integrated optical graph (Linux only)

The optical stage described above is **the same stage**, now expanded from six to thirteen standalone effects and the Vintage Glass compound preset. It is not a second rendering route. Its earlier illustrative linear sequence is refined by an explicit dependency graph: technical lens correction and RAW normalization → creative geometrical warp/channel aberration → selective focus and spatial softness → shared source detection → pre-tone flare/streak/diffusion/leaks/vignetting → existing Camera Look → original M-Film Film Stock and finishing → export. Preserve existing six semantics and versions; see [optical integration details](optical-engine/integration.md). Existing PhotoPrism and Web Darkroom paths are unchanged. All new effect algorithms are Linux mandatory; CHDK is out of scope for this specification revision.
