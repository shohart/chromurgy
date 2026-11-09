# 21 — Optical Effects Engine: Integrated Linux Requirements (v0.6)

**Scope: the existing Linux M-Film development engine and its existing Web Darkroom. This is an in-place expansion, not another processor, plugin host, separate UI, service, or independent category.** Existing M-Film Film Stock and Camera Look stages stay intact. CHDK and camera firmware work is explicitly out of scope for v0.6.

## Product requirement

Implement **every effect in the existing six-effect catalog and all seven newly requested standalone effects**, plus the **Vintage Glass** compound preset, inside the **same existing `optical.stack` of render recipe v2**. Keep one discovery API (`GET /api/v1/creative/optical-effects`), one effect registry, one render queue, one reduced-resolution preview, one full-resolution render pipeline, one cache-key policy, and the existing PhotoPrism publication process. No mock effects, duplicate algorithms hidden under new labels, hard-coded JPEG overlays, or off-line-only prototypes may be treated as delivered.

**Preservation requirement:** existing six stable identifiers, default meanings, saved recipes, API consumers, and visual regression fixtures MUST continue to work. When refining an old effect, version the implementation, record observable changes, and test backward-compatible behavior. Never silently rename IDs or drop configuration keys.

### Unified catalog (13 standalone modules + one compound preset)

| Existing effect ID (unchanged) | Main mechanism | Required status |
|---|---|---|
| `soft_sun_glow` | Multi-scale warm highlight bloom | Retain, test, support stacking |
| `ricoh_hdf_diffusion` | Highlight diffusion, local softness/veil | Retain, test, support stacking |
| `black_pro_mist_like` | Subtle diffusion, black lift, highlight spread | Retain, test, support stacking |
| `vintage_veiling_flare` | Broad veiling glare, decreased contrast | Retain; explicitly separate from geometric ghosts |
| `film_halation_extra` | Red/orange highlight edge spill | Retain; enforce halation policy |
| `orton_glow` | Soft blurred exposure-mix branch | Retain, test, support stacking |
| **New:** `lens_flare_ghosting` | Source-linked geometric internal reflections | **Implement** |
| **New:** `starburst_cross_screen` | Directional star rays for bright compact emitters | **Implement** |
| **New:** `anamorphic_streak` | Directional cinematic light streak | **Implement** |
| **New:** `analog_light_leaks` | Procedural seeded edge fog/leaks | **Implement** |
| **New:** `optical_vignetting` | Controlled radial/elliptical exposure falloff | **Implement** |
| **New:** `lensbaby_sweet_spot` | Selective focus-region softness | **Implement** |
| **New:** `tilt_shift_miniature` | Adjustable focal band and progressive defocus | **Implement** |

**Compound preset `vintage_glass`:** an editable stack/preset combining **radial chromatic aberration**, **edge softness**, **barrel distortion**, and optionally `optical_vignetting`. The three optical submechanisms are **required implementations** as internal registered operations or independently addressable sub-effect IDs (`vintage_glass_chromatic_aberration`, `vintage_glass_edge_softness`, `vintage_glass_barrel_distortion`); the composite `vintage_glass` itself is a selectable preset, **not** a replacement for the original six. Do not present its three components as unrelated headline effects unless UI implementation merits an Advanced section.

No new top-level “Optical Extensions” product is permitted. The Web Darkroom continues to use the existing **Optical Effects** step after Material / Camera Look / Film Stock. Group existing and new modules there by `Diffusion & Glow`, `Flares & Streaks`, `Light & Film Artifacts`, `Lens Character`, and `Creative Focus`. These are **navigation groups within the existing selector**, not separate workflows.

## Architecture and authoritative references

- Original stage order and color contracts: [`20-creative-pipeline.md`](20-creative-pipeline.md).
- Implementable numerical algorithms: [`optical-engine/algorithms.md`](optical-engine/algorithms.md).
- Pipeline placement, compositing, mask logic, back-compat: [`optical-engine/integration.md`](optical-engine/integration.md).
- Web controls, API, PhotoPrism and preview semantics: [`optical-engine/web-api.md`](optical-engine/web-api.md).
- Exact incremental work sequence: [`optical-engine/waves.md`](optical-engine/waves.md) — **Wave 1, 2, 3, 5, 10**, all mandatory.
- Deterministic fixtures, acceptance and benchmarks: [`optical-engine/validation.md`](optical-engine/validation.md).
- Machine-readable registry, constraints and shipped defaults: [`../contracts/optical-effects-catalog.yaml`](../contracts/optical-effects-catalog.yaml).
- Recipe example with original and new effects: [`../contracts/render-recipe-v2.optics-example.json`](../contracts/render-recipe-v2.optics-example.json).

## Mandatory engine behavior

1. Process RAW/NEF/DNG through the **existing** Linux RAW developer, preserve linear-light scene information before film look; do not build a second decoder.
2. Share one processor registry and versioned ABI, reuse existing spatial masks / blur pyramid / temporary allocation / stage timers. Add genuinely new operators only where required.
3. Zero intensity is a mathematically neutral bypass; **none of the new effects is on by default for historical recipes**.
4. Numerical controls are validated server-side against the registry; backend is the source of truth, not the browser. Reject unsupported parameters and invalid points rather than silently ignore them.
5. Every bright-source effect works with automatic source detection **and** manually selected highlight positions, if meaningful. No invented random suns when the photo lacks a source. Allow masks and negative selections.
6. Preview (e.g. 720 or 1280 px long edge) and final render use the **same implementations and pinned parameters**; for scale-sensitive source detectors, normalize to the full-resolution source or cache source coordinates. Final render always derives from the original RAW.
7. Every random effect uses a stable seed plus source digest and fixed global coordinates; tile splitting, retries, threads and preview dimensions cannot pick a new random pattern.
8. Correctly composite multiple effects (including more than one flare), and warn on overlapping glow, vignette, and halation mechanisms; no global 'force one effect' limitation. Keep stack cap at least 16.
9. Export non-destructively with original EXIF camera model preserved, recipe/provenance sidecar, output checksum and PhotoPrism publication exactly as previous versions.
10. CPU-only reference path and reproducible image fixtures are mandatory. SIMD/GPU acceleration is optional and must be parity-tested.

## Existing effects: do not regress

- `soft_sun_glow`: soft-knee bright mask, warm spill and multiscale bloom; preserve dark detail and suppress edge ringing.
- `ricoh_hdf_diffusion`: diffusion inspired by Ricoh HDF, not a claim of equivalent optical hardware.
- `black_pro_mist_like`: modest black lift and subdued highlight spread; compare independently with HDF rather than sharing one hardcoded filter.
- `vintage_veiling_flare`: broad additive/contrast-reducing veil; **do not implement new `lens_flare_ghosting` as a mere alias of this effect**. Move any optional legacy ghost behavior behind a documented compatibility switch if it already exists.
- `film_halation_extra`: a separate red/orange highlight rim and `halation_policy=film|optical|stacked|disabled`. Do not add it accidentally when M-Film Film Stock already provides halation.
- `orton_glow`: broad painterly softness, with edge and skin protection.

## Delivery definition

Each effect is complete only when it is selectable via **the existing Web Darkroom**, persisted in recipe v2, produces distinct demonstrable pixel output at full resolution in production Linux worker, previews consistently, handles neutral/no-source cases safely, saves/publishes to PhotoPrism, passes all stated tests and appears in the operator catalog with version, controls, source licensing, samples, and documentation.

**Wave 10 exit gate: every original and newly required effect plus Vintage Glass is available in production, with no CHDK implementation dependency.**
