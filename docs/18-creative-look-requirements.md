# 18 — Creative Camera Looks and Optical Effects: Product Requirements

**Implementation status:** NEW requirements for v0.4. These are *not* existing M-Film features. Implement on the **Linux server**. On the Canon PowerShot SX510 HS, only recipe selection/storage is an immediate requirement; rendering is an explicitly experimental option.

## Product objective

Enhance the existing Server-First Film Lab with a composable, repeatable creative workflow:

`SOURCE RAW → input camera normalization → target Camera Look → optical-light simulation → original M-Film film stock → rendition`.

The exact mathematical order is specified in [20 — Pipeline](20-creative-pipeline.md), which takes precedence over the simplified diagram above. Preserve the current architecture: capture unreviewable RAW film rolls, develop primarily on Linux, publish to PhotoPrism, and allow an optional offline on-camera developer.

## Required separation of responsibilities

1. **Input camera calibration** (Canon SX510 HS, actual DNG): technical, device-specific, neutral. Never misuse the *target* camera's RAW matrix as input calibration.
2. **Camera Look**: a creative rendering intended to evoke another camera's *output character*, not its sensor physics; selectable as `camera_look_id` with adjustable mix strength.
3. **Optical Effects**: independent scene-light and lens/diffusion approximations; multiple effects may be combined with documented order and bounded controls.
4. **Film Stock**: existing 72 M-Film stocks where legally available; film appearance remains independently selectable and can be set to `none`.
5. **Export**: full-resolution JPEG (with optional 16-bit TIFF/PNG for verification); a versioned recipe and provenance sidecar.

Do not conflate Camera Look with Film Stock: Leica M9 + Kodak Portra 400 + Soft Sun Glow must be possible. Users can disable any layer (`none`). No forced grain unless requested through film or optical effects.

## Server — MUST IMPLEMENT

- All eight named Camera Looks in [19 — Profile Catalog](19-camera-look-catalog.md), plus `neutral`.
- All optical effects in [21 — Optical Engine](21-optical-effects.md), including **sun glow, highlight diffusion/HDF-style, veiling flare, halation, Orton-like glow, and diffusion-filter-like presets**.
- `Golden Haze` original composite preset and the catalog combinations in [`camera-presets.yaml`](../contracts/camera-presets.yaml).
- A shared color-managed, deterministic pipeline; real processing, **not labels attached to a neutral JPEG**.
- Server CLI and service render API; same engine code path; staged previews, comparison view and rerender from original DNG.
- Recipes stored with each roll/frame, immutable once development begins unless an explicit new rendition is requested.
- Clear differentiation between `inspired`, `calibrated` and `measured` confidence, not unsupported "pixel-accurate camera" claims.
- No third-party commercial LUT copied into the repository without appropriate rights.

## Camera / CHDK — MUST IMPLEMENT versus EXPERIMENTAL

**Must implement when the current CHDK UI is available:** choose `camera_look_id`, `film_profile_id`, `optical_preset_id`, optic-strength/intensity, and a saved composite preset; persist versioned recipe in the roll manifest; upload unchanged to Linux; show selected look and sync state. Default to neutral look / no effect on an old manifest.

**Experimental, hardware validation required:** render Camera Looks locally (start with LUT/tone-only); reduced-resolution bloom; full spatial optical effects; screen preview; camera-native gallery integration. **Do not block the Linux release** on any of these.

**Explicitly prohibited:** running expensive pixel-space filters during exposure, unverified DRYOS memory writes, modifying Canon's persistent firmware, silently dropping requested effects from an offline output. An offline image missing effects must be labeled `film_only_offline` or `partial_offline` and remain distinct from server-developed renditions.

## User journeys

- **Normal:** choose camera look + film + optics → expose 12/24/36 RAW frames without preview → seal roll → transfer original DNG → Linux develop high-resolution with full stack → PhotoPrism → optional JPEG return to camera.
- **No server:** expose roll → seal → locally develop an appropriately labeled reduced-effects version; preserve original and full recipe → later server sync → full-quality rendition automatically generated, not overwritten.
- **Rerender:** user changes one layer on Linux → new `render_id`, no change to source DNG or original roll recipe; user can compare versions and select a publication default.

## Required outputs

- `camera_looks` listing (metadata, version, availability and evidence tier).
- Original and developed JPEGs paired with a machine-readable recipe and stage provenance.
- Photoprism originals per rendition, sane grouping avoiding clutter by default.
- Linux CLI supports `--camera-look`, `--camera-look-strength`, `--optical-preset`, `--optical-strength`, `--film`, `--recipe` and `--output`.
- Optional GUI may come later; CLI/API and correctness are first-class.

## Non-goals

Physical recreation of a CCD, Super CCD, Foveon stacked sensor, lens coatings, optical flare geometry without reference measurement, or recovery of clipped detail absent from source RAW. No physical camera-brand endorsement. Match *appearance*, not electronics.

## v0.6 required expansion without replacing earlier look engine

Add seven named standalone optical effects and the Vintage Glass compound preset via [the current optical engine](21-optical-effects.md), keeping the original eight Camera Looks, seventy-two M-Film Film Stocks and all six original optical modules. **Server implementation is mandatory; camera implementation is not requested in this revision.** Each new effect is independent of Camera Look/Film Stock and may be combined with either.
