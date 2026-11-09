# Optical Effects Engine — Existing Web Darkroom and API Integration

The existing Web Darkroom has the workflow **Select Material → Camera Look → Film Stock → Optical Effects → Preview → Develop → PhotoPrism**. Do not add a new page/tab/service called “New Effects”. Expand the **same Step 4** with all existing and newly required effects, and preserve preview and PhotoPrism destination logic from docs 27–34.

## Optical Effects selector (same Step 4)

- Groups inside existing panel: `Diffusion & Glow` (six existing effects as appropriate); `Flares & Streaks` (new Ghosting/Anamorphic); `Light & Film Artifacts` (Starburst/Light Leaks/Halation); `Lens Character` (Vignetting/Vintage Glass); `Creative Focus` (Lensbaby/Tilt-Shift).
- Existing six controls, saved presets, IDs and intensities must display as before. When an old recipe opens, the new effects are all disabled by default.
- Effect card contains: localized name, technical description (not overclaiming authentic physics), 1–2 use cases, default/valid range, adjustable strength, on/off, optional expandable Advanced, a small before/after **real engine output** sample with rights-cleared assets.
- Common affordances: move focal point and source positions on preview, choose sources `Auto` or `Manual`, suppress unwanted detected lights, adjust intensity, Reset effect, Copy to next image, Apply to selected set, Save as optical preset.
- Optical preset selection is additive and composable; show per-effect chips with controls. `Vintage Glass` expands to its component operations and editable controls rather than hiding a black-box transform. Existing Golden Haze remains available and unchanged until versioned revision is approved.
- Warn non-blockingly when several diffusion effects are stacked, when `film_halation_extra` overlaps stock halation, and when `optical_vignetting` overlaps existing stock vignette. Add `vignette_policy` analogous to `halation_policy`.
- Users should be able to use **multiple** optical effects in one recipe and set strength individually. The server resolves effect order from the dependency graph, not from drag order unless order is explicitly configurable and validated.

## Preview contract

- Preview is computed via the **same production optical implementation and recipe v2**, from a reduced/appropriately sampled scene-linear RAW source. Limit by configured pixel count (e.g. 1280 px long edge), show explicit PREVIEW watermark or label, do not pretend it equals final resolution.
- Use a downsampled scene-linear image rather than an old embedded JPG with baked camera look. For angle/source geometry, maintain normalized point positions. When source detection differs with reduction, compute source map once at suitable source scale and reuse for full image, or cache full-resolution source statistics.
- Stochastic `analog_light_leaks` is seeded by asset+recipe so **the same spatial pattern** appears in preview and final, scaled to image dimensions. Starburst ray length and ghost radius scale in normalized coordinates. Blur fidelity and film grain can be sample-scale-dependent but artistic composition must remain consistent.
- Interactive handles only appear for relevant effects: flare sources/ghost axis, starburst sources, streak sources, vignette center, sweet-spot focus, tilt-shift band/angle. Handle moves send recipe patch, invalidate stale previews and request cancelable rerender.
- Show no-source status for auto-detected light effects (e.g. “No suitable bright point detected; set manually”), not a blank success indistinguishable from broken implementation.
- Support crop-based high-quality preview for focus effects and 1:1 comparison using existing preview endpoint. Do not use a random fixed texture in preview and a different one in final.

## API compatibility

Existing endpoints remain stable:

- `GET /api/v1/creative/optical-effects` — expanded registry with all 13 standalone effects plus optional private advanced operations and preset catalog references; each enabled effect describes input domain, source controls, defaults, limits and implementation version.
- `GET /api/v1/creative/presets` — also expose `Vintage Glass` compound preset plus named examples; preserve other presets.
- `POST /api/v1/renders` — accepts recipes containing new `optical.stack[]` items and optional source selections; no breaking changes.
- Existing Web Darkroom preview/job endpoints — accept exactly the same recipe v2, produce thumbnail + status + run times; no new render service.
- `POST /api/v1/renders/{render_id}/publish` — existing PhotoPrism publication with same album/folder selection path. A new optical effect must never bypass that publication layer.

**Optional additive API extensions**, after existing route discovery: `/api/v1/creative/optical-effects/{id}` for detailed descriptors; `/api/v1/creative/optical-sources` (POST) for image-source detection, returning normalized candidate coordinates, energy/confidence and algorithm version; `/api/v1/creative/optical-presets` (GET/POST authorized) for listing/saving user stacks. Names must be reconciled with real existing server routes before coding. Contract definitions are in `contracts/openapi-creative-extension.yaml`.

## Recipe fields and validation

```json
{
  "optical": {
    "preset_id": "vintage_glass",
    "strength": 0.7,
    "halation_policy": "film",
    "vignette_policy": "optical",
    "stack": [
      {"id":"vintage_glass_barrel_distortion", "enabled":true, "parameters":{"k1":-0.035}},
      {"id":"vintage_glass_chromatic_aberration", "enabled":true, "parameters":{"red_shift_fraction":0.0015,"blue_shift_fraction":0.0015}},
      {"id":"vintage_glass_edge_softness", "enabled":true, "parameters":{"edge_blur_radius_fraction":0.002}},
      {"id":"optical_vignetting", "enabled":true, "parameters":{"strength_stops":0.45,"inner_radius":0.55}}
    ]
  }
}
```

This is the `optical` object **fragment** of an existing render recipe, not a new schema. `optical.stack` entries retain `id`, `enabled`, and numeric `parameters`; optional source settings are added to effect items in the existing schema, not via a separate incompatible recipe.

Input validations: known stable ID; allowed min/max and enum-coded parameters; normalized position in [0,1]; finite numeric values (NaN/Infinity prohibited); max source count; stack size <=16; known profile versions; mutually incompatible parameter pairs fail explicitly. The Python and C validation paths must agree.

## Web + PhotoPrism end-to-end

1. Select Nikon `.NEF`, Canon `.DNG`, M-Film RAW roll or RAW-backed asset from PhotoPrism folder/album.
2. Pick existing Camera Look and Film Stock as before.
3. Select **any** combination of old six and new effects inside the existing Optical Effects step; optionally expand Vintage Glass or tweak sources on preview.
4. Request preview; inspect original/processed slider, crop and per-effect source handles.
5. Submit asynchronous full-resolution job. Renderer writes output, provenance, ICC and original EXIF; film/camera/optical model IDs are recorded separately from real camera model.
6. Choose existing or new PhotoPrism folder/album independently of source; publish via existing staging/index/album-UID association. Never overwrite source RAW or another rendition without explicit version switch.
7. Re-edit the saved recipe and rerender same source into a new variant without loss of original or prior variants.

## Acceptance at UI/API level

- Existing six-effect recipe opens without changed IDs/values; new effects all disabled.
- Every new effect appears and can be independently toggled, previewed, developed, saved and published.
- A combination of old `soft_sun_glow` and new `lens_flare_ghosting` visibly contains both mechanisms rather than one overwriting the other.
- Same `analog_light_leaks` seed: preview and final mask alignment within normalized coordinate tolerance.
- PhotoPrism album/folder source/destination workflows from v0.5 continue to pass untouched.
- Server failure and per-effect unsupported state are explicit, retryable, logged; never claim success using an unprocessed JPEG.


## v0.7 curated combos

Add *existing registry* listing, inspection and resolve operations for curated combination presets, returning full expanded `render-recipe-v2`, `available`, `blocked_reason`, `wave_required`, evidence tier and exact pinned engine revisions. Prefer extension of already implemented preset routes to adding another endpoint family. API/acceptance in [37](../37-combo-waves-and-acceptance.md).
