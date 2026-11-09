# v0.7 (2026-11-09) — Curated combination presets (Linux server only)

- Integrated a 21-preset creative combo catalog into the current Linux M-Film recipe v2 and Web Darkroom; no new renderer.
- Added machine-readable proposed values, evidence provenance, film alias resolution requirements and immutable seed/version policy.
- Defined Web Darkroom UX, PhotoPrism publishing, acceptance gates and delivery waves 1/2/3/5/10.
- Kept all 12 previous `camera-presets.yaml` composite IDs untouched, all 13 standalone optical effect IDs and the compound Vintage Glass, and original rendering behaviour.
- Clear distinction between popular/community-documented component recipes and original *editorial combinations*. No new effects claimed implemented by this specification.

---

# Specification Change Log

## v0.6 — 2026-11-09 — Integrated Linux optical engine expansion

- **Not a separate subsystem.** Extended existing `docs/21-optical-effects.md`, render recipe v2, current Web Darkroom Step 4, single Linux render worker, PhotoPrism publish and existing test/roadmap documents.
- Preserved the six original effects and stable IDs.
- Required new standalone modules: `optical_vignetting`, `lens_flare_ghosting`, `starburst_cross_screen`, `anamorphic_streak`, `analog_light_leaks`, `lensbaby_sweet_spot`, `tilt_shift_miniature`.
- Added editable compound preset `vintage_glass` with actual distortion, CA and softness operators.
- Made mandatory Waves **1, 2, 3, 5, 10**, ending with all effects implemented in the Linux server.
- Added color-managed algorithm, numerical and compositing guidance, source detection/masks, deterministic previews and QA/performance gates.
- Extended current recipe v2 compatibly with optional source selection/masks/vignette policy and stack size 16.
- Expanded existing `openapi-creative-extension.yaml` and machine-readable optical catalogs.
- Preserved all v0.5 Web Darkroom / PhotoPrism and CHDK project documents unchanged except where integration notes apply; no new camera implementation is requested.

## v0.5 — 2026-11-05 — Web Darkroom / PhotoPrism

Original baseline archived by revision.
