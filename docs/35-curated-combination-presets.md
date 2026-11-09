# 35 — Curated Camera × Film × Optics Combos (v0.7)

**Server-only integrated extension to v0.6, NOT a standalone module or new optical-effects pane.**

Existing code already has Camera Looks, Film Stocks, the original six and the seven additional Optical Effects plus Vintage Glass. This spec adds **21 editable, curated multi-layer presets** to the *same render recipe v2 and existing Web Darkroom*. All old preset IDs, IDs of the 13 standalone effects, optical stacks, and PhotoPrism behaviours remain unchanged.

## User story

User opens the existing Web Darkroom, selects a RAW/NEF/DNG (or a PhotoPrism source), then sees **Suggested Combos** above the existing editable Camera / Film / Optics controls. Selecting a Combo fills in all three layers, shows the reason/conditions/evidence confidence, and generates a reduced preview. User can adjust every strength, switch/remove film, disable or reorder an effect through the existing graph, and save the changes as a private custom preset. Full develop and PhotoPrism publish use the identical frozen recipe.

No one-click overwrite of RAW, no hidden change to an original roll's film stock, no duplicated processing service.

## Catalog overview

| # | Preset | Camera emulation | Film profile | Optics | Earliest wave | Evidence class |
|---|---|---|---|---|---|---|
| 01 | **Portra Soft Portrait** | `fujifilm_s5_pro` | `kodak-portra-400` | black_pro_mist_like | 1 | component_backed_editorial |
| 02 | **Leica Portra Daylight** | `leica_m9_ccd` | `kodak-portra-400` | optical_vignetting | 1 | component_backed_editorial |
| 03 | **Golden Haze II** | `fujifilm_s5_pro` | `kodak-gold-200` | soft_sun_glow, vintage_veiling_flare | 1 | component_backed_editorial |
| 04 | **Classic Negative Gold Street** | `fujifilm_xpro3_classic_negative` | `kodak-gold-200` | optical_vignetting | 1 | direct_recipe_family_adapted |
| 05 | **GR Positive HDF Street Soft** | `ricoh_gr_iii_positive` | `none` | ricoh_hdf_diffusion | 1 | component_backed_editorial |
| 06 | **D200 Tri-X Documentary** | `nikon_d200_ccd` | `kodak-tri-x-400` | optical_vignetting | 1 | component_backed_editorial |
| 07 | **645D Ektar Landscape** | `pentax_645d_ccd` | `kodak-ektar-100` | optical_vignetting | 1 | component_backed_editorial |
| 08 | **Merrill Detail Clean** | `sigma_dp2_merrill_foveon` | `none` | optical_vignetting | 1 | editorial_only |
| 09 | **M8 Warm Everyday** | `leica_m8_ccd` | `kodak-portra-400` | optical_vignetting | 1 | component_backed_editorial |
| 10 | **800T Neon Halo** | `leica_m9_ccd` | `cinestill-800t` | film_halation_extra | 1 | component_backed_editorial |
| 11 | **Woodland Orton Atmosphere** | `pentax_645d_ccd` | `fujichrome-velvia-50` | orton_glow | 1 | component_backed_editorial |
| 12 | **Windowlight Portra Veil** | `fujifilm_s5_pro` | `kodak-portra-400` | vintage_veiling_flare | 1 | component_backed_editorial |
| 13 | **Leica Sun Ghosts** | `leica_m8_ccd` | `kodak-gold-200` | soft_sun_glow, lens_flare_ghosting | 2 | component_backed_editorial |
| 14 | **Night Walk Cross Screen** | `nikon_d200_ccd` | `cinestill-800t` | starburst_cross_screen | 2 | component_backed_editorial |
| 15 | **Blue Streak Neon** | `leica_m9_ccd` | `cinestill-800t` | anamorphic_streak | 3 | component_backed_editorial |
| 16 | **Summer 1998 Light Leak** | `nikon_d200_ccd` | `kodak-gold-200` | analog_light_leaks | 3 | component_backed_editorial |
| 17 | **Superia Vintage Glass** | `nikon_d200_ccd` | `fujicolor-superia-400` | vintage_glass_barrel_distortion, vintage_glass_chromatic_aberration, vintage_glass_edge_softness, optical_vignetting | 5 | component_backed_editorial |
| 18 | **Sweet Spot Floral** | `fujifilm_s5_pro` | `kodak-portra-400` | lensbaby_sweet_spot | 5 | component_backed_editorial |
| 19 | **Miniature Rooftops** | `ricoh_gr_iii_positive` | `none` | tilt_shift_miniature | 10 | component_backed_editorial |
| 20 | **Highlands Velvia** | `pentax_645d_ccd` | `fujichrome-velvia-50` | optical_vignetting | 1 | component_backed_editorial |
| 21 | **GR HDF Evening Lights** | `ricoh_gr_iii_positive` | `none` | ricoh_hdf_diffusion, starburst_cross_screen | 2 | component_backed_editorial |

## Quality policy

- All 21 are **proposed artistic starting points** until actual RAW-to-JPEG preview/full-resolution test renders are reviewed. No false READY / community-verified status.
- Source-to-look color input normalization occurs **once**, prior to both camera look and film color. No physical "CCD conversion" claims.
- Heavy film simulation + heavy camera look can double contrast/chroma; intentionally restrained look strengths, especially Classic Negative + Gold, are part of the recipe. Keep skin and highlight protection test gates.
- `none` film is a deliberate *camera-look-only* mode. Do not fabricate a film stock to satisfy a menu label.
- The film aliases Ektar 100, Velvia 50 and Superia 400 are **candidate names**; must resolve against upstream M-Film inventory by actual ID and license. Disable related cards with an explicit reason until resolved; NEVER silently replace unavailable film.
- Where a film already includes grain/halation/vignette, coordinate ownership via existing scale and policy fields. `800T Neon Halo` explicitly disables film halation in favor of the existing optical operator.
- Deterministic per-frame seed is derived from source digest + preset ID + version + user variation, with the same source-normalized positions for preview/final. Explicit user seed overrides derived default.
- For automatic light-source effects, no detected compact bright source means **zero ghost/star/streak contribution**, not random artificial disks.
- Use currently available operator IDs exactly; do not rename original v0.6 effects. Preset revisions are append-only and historical recipe hashes immutable.

## Detailed creative briefs

### 01. Portra Soft Portrait (`portrait-portra-gentle-v07`)

- **Scenario:** natural-light portraits, skin, shaded daylight.
- **Avoid:** hard direct noon sun or deep night with clipping.
- **Rationale:** Popular Portra family, gentle portrait gradation and restrained optical diffusion.
- **Evidence:** `fxw-2025`, `fujifilm-filmsim`, `tiffen-bpm`; grade `component_backed_editorial`.
- **Look strength:** 0.48; **film:** `kodak-portra-400`; **optics:** `black_pro_mist_like`.
- **Depends on:** Wave 1. A component-grounded editorial combination. Does not reproduce a specific Fujifilm camera + film capture.

### 02. Leica Portra Daylight (`leica-portra-daylight-v07`)

- **Scenario:** street portraits, architecture with people, travel.
- **Avoid:** saturated studio gels requiring faithful color.
- **Rationale:** M9-inspired dense color tempered by Portra gentle palette.
- **Evidence:** `fxw-2025`, `reddit-fuji-thread`; grade `component_backed_editorial`.
- **Look strength:** 0.42; **film:** `kodak-portra-400`; **optics:** `optical_vignetting`.
- **Depends on:** Wave 1. 

### 03. Golden Haze II (`golden-haze-ii-v07`)

- **Scenario:** backlit golden hour outdoors, sunlight on hair.
- **Avoid:** flat low-light interiors or already blown-out skies.
- **Rationale:** Refinement of existing Golden Haze; intentionally distinct ID to preserve old Golden Haze output.
- **Evidence:** `fxw-2025`, `reddit-fuji-thread`, `ricoh-hdf`; grade `component_backed_editorial`.
- **Look strength:** 0.45; **film:** `kodak-gold-200`; **optics:** `soft_sun_glow`, `vintage_veiling_flare`.
- **Depends on:** Wave 1. Never overwrite the pre-v0.7 golden_haze preset ID.

### 04. Classic Negative Gold Street (`classic-neg-kodak-gold-v07`)

- **Scenario:** sunny cities, summer travel, candid street.
- **Avoid:** skin tones already too warm or extremely saturated shop lights.
- **Rationale:** Classic Negative + Kodak Gold-inspired combination exists as a user recipe; apply a restrained camera-look weight to prevent two heavy film color transforms.
- **Evidence:** `reddit-gold-classicneg`, `fxw-2025`, `fujifilm-filmsim`; grade `direct_recipe_family_adapted`.
- **Look strength:** 0.30; **film:** `kodak-gold-200`; **optics:** `optical_vignetting`.
- **Depends on:** Wave 1. The community recipe is for a Fuji camera, not this three-stage Linux emulation. No copied coefficients.

### 05. GR Positive HDF Street Soft (`ricoh-positive-hdf-soft-v07`)

- **Scenario:** overcast street with occasional windows, indoor cafés.
- **Avoid:** deeply dark scenes without highlights.
- **Rationale:** Official Ricoh HDF operation paired with Positive-inspired digital look; conservative optical diffusion.
- **Evidence:** `ricoh-hdf`; grade `component_backed_editorial`.
- **Look strength:** 0.70; **film:** `none`; **optics:** `ricoh_hdf_diffusion`.
- **Depends on:** Wave 1. 

### 06. D200 Tri-X Documentary (`trix-d200-documentary-v07`)

- **Scenario:** black-and-white documentary, urban texture, reportage.
- **Avoid:** precise color editorial work.
- **Rationale:** Tri-X classic reportage evidence; Nikon D200 contributes restrained tonality only, not CCD chroma after B&W conversion.
- **Evidence:** `kodak-trix`, `fxw-2025`; grade `component_backed_editorial`.
- **Look strength:** 0.18; **film:** `kodak-tri-x-400`; **optics:** `optical_vignetting`.
- **Depends on:** Wave 1. Keep camera color look strength low because film output is monochrome.

### 07. 645D Ektar Landscape (`pentax-ektar-landscape-v07`)

- **Scenario:** detailed landscape and travel scenery in clear light.
- **Avoid:** portrait skin when rich chroma makes complexions artificial.
- **Rationale:** Editorial landscape profile, not a documented community combination.
- **Evidence:** `fujifilm-velvia`; grade `component_backed_editorial`.
- **Look strength:** 0.35; **film:** `kodak-ektar-100`; **optics:** `optical_vignetting`.
- **Depends on:** Wave 1. Ektar source must resolve to a real upstream film ID; otherwise disable.

### 08. Merrill Detail Clean (`sigma-clean-detail-v07`)

- **Scenario:** texture, surfaces, fine foliage, daylight.
- **Avoid:** high-ISO noisy scenes and weakly detailed thumbnails.
- **Rationale:** Foveon-inspired microcontrast without imposed film color or artificial bokeh.
- **Evidence:** `fujifilm-filmsim`; grade `editorial_only`.
- **Look strength:** 0.55; **film:** `none`; **optics:** `optical_vignetting`.
- **Depends on:** Wave 1. 

### 09. M8 Warm Everyday (`leica-m8-everyday-v07`)

- **Scenario:** documentary street, people, small towns.
- **Avoid:** highly controlled product color.
- **Rationale:** M8-inspired rendering moderated by versatile Portra-inspired color.
- **Evidence:** `fxw-2025`; grade `component_backed_editorial`.
- **Look strength:** 0.50; **film:** `kodak-portra-400`; **optics:** `optical_vignetting`.
- **Depends on:** Wave 1. 

### 10. 800T Neon Halo (`cinestill-neon-halo-v07`)

- **Scenario:** neon signs, tungsten shop windows, night streets.
- **Avoid:** daylight with no point sources or large white overexposed areas.
- **Rationale:** CineStill documents halation around bright tungsten/night highlights.
- **Evidence:** `cinestill-800t`, `cinestill-faq`, `fxw-mid-2025`; grade `component_backed_editorial`.
- **Look strength:** 0.22; **film:** `cinestill-800t`; **optics:** `film_halation_extra`.
- **Depends on:** Wave 1. Optical halation explicitly owns halation; disable film built-in halation to avoid duplication.

### 11. Woodland Orton Atmosphere (`misty-woodland-orton-v07`)

- **Scenario:** misty forest, forest floor, waterfall scenes.
- **Avoid:** midday harsh light or high-detail commercial architecture.
- **Rationale:** Classic painterly Orton technique with conservatively restrained Velvia saturation.
- **Evidence:** `fujifilm-velvia`; grade `component_backed_editorial`.
- **Look strength:** 0.23; **film:** `fujichrome-velvia-50`; **optics:** `orton_glow`.
- **Depends on:** Wave 1. 

### 12. Windowlight Portra Veil (`portra-windowlight-veil-v07`)

- **Scenario:** portrait near strong side window or backlit interior.
- **Avoid:** flat artificial light without identifiable direction.
- **Rationale:** Popular Portra portrait starting point with intentionally modest veiling flare.
- **Evidence:** `fxw-2025`, `tiffen-bpm`; grade `component_backed_editorial`.
- **Look strength:** 0.35; **film:** `kodak-portra-400`; **optics:** `vintage_veiling_flare`.
- **Depends on:** Wave 1. 

### 13. Leica Sun Ghosts (`sunny-leica-flare-ghosts-v07`)

- **Scenario:** sun in frame, backlit summertime travels.
- **Avoid:** no sun, no visible light source.
- **Rationale:** A physically motivated light-source-driven ghost rather than decorative overlay.
- **Evidence:** `fxw-2025`; grade `component_backed_editorial`.
- **Look strength:** 0.30; **film:** `kodak-gold-200`; **optics:** `soft_sun_glow`, `lens_flare_ghosting`.
- **Depends on:** Wave 2. 

### 14. Night Walk Cross Screen (`cross-screen-night-walk-v07`)

- **Scenario:** isolated street lamps, shop signs, Christmas lights.
- **Avoid:** wide luminous surfaces; faces lit directly from front.
- **Rationale:** Night-point-source aesthetic with real compact highlight detection.
- **Evidence:** `cinestill-800t`, `cinestill-faq`; grade `component_backed_editorial`.
- **Look strength:** 0.27; **film:** `cinestill-800t`; **optics:** `starburst_cross_screen`.
- **Depends on:** Wave 2. 

### 15. Blue Streak Neon (`anamorphic-neon-street-v07`)

- **Scenario:** night traffic, neon, car headlights.
- **Avoid:** daytime landscapes lacking compact bright points.
- **Rationale:** Anamorphic-style streaks over tungsten/night film aesthetic; editorial not physically equivalent to real anamorphic glass.
- **Evidence:** `cinestill-800t`; grade `component_backed_editorial`.
- **Look strength:** 0.16; **film:** `cinestill-800t`; **optics:** `anamorphic_streak`.
- **Depends on:** Wave 3. 

### 16. Summer 1998 Light Leak (`summer-1998-light-leak-v07`)

- **Scenario:** sunny casual summer snapshots, holiday rolls.
- **Avoid:** formal portraits, product photos, scientific records.
- **Rationale:** Creative analog camera body light leak; not inherent to Kodak Gold emulsion.
- **Evidence:** `reddit-fuji-thread`, `cinestill-faq`; grade `component_backed_editorial`.
- **Look strength:** 0.32; **film:** `kodak-gold-200`; **optics:** `analog_light_leaks`.
- **Depends on:** Wave 3. Use fixed seed. Never claim light leaks are a fundamental property of the film.

### 17. Superia Vintage Glass (`superia-vintage-glass-v07`)

- **Scenario:** casual old-compact nostalgia and family travel.
- **Avoid:** straight architectural lines near frame edges.
- **Rationale:** Superia community preference plus subtle vintage lens artifacts; no deliberate severe corruption.
- **Evidence:** `reddit-fuji-thread`; grade `component_backed_editorial`.
- **Look strength:** 0.40; **film:** `fujicolor-superia-400`; **optics:** `vintage_glass_barrel_distortion`, `vintage_glass_chromatic_aberration`, `vintage_glass_edge_softness`, `optical_vignetting`.
- **Depends on:** Wave 5. Resolve Superia stock ID from upstream; do not invent a LUT.

### 18. Sweet Spot Floral (`sweet-spot-flowers-v07`)

- **Scenario:** close flowers, portraits with one face, small details.
- **Avoid:** crowd portraits with many equal-interest faces.
- **Rationale:** Localized focus emphasis; subject selection required for reliable use.
- **Evidence:** `tiffen-bpm`; grade `component_backed_editorial`.
- **Look strength:** 0.40; **film:** `kodak-portra-400`; **optics:** `lensbaby_sweet_spot`.
- **Depends on:** Wave 5. Offer moveable focus center in preview; preset defaults to image center.

### 19. Miniature Rooftops (`miniature-rooftops-v07`)

- **Scenario:** high-angle roofscapes, railways, toy-city views.
- **Avoid:** eye-level portraits and shallow-depth real scenes.
- **Rationale:** High-angle miniature technique with movable focal band; do not force unnatural saturation.
- **Evidence:** `fujifilm-filmsim`; grade `component_backed_editorial`.
- **Look strength:** 0.35; **film:** `none`; **optics:** `tilt_shift_miniature`.
- **Depends on:** Wave 10. 

### 20. Highlands Velvia (`highlands-velvia-v07`)

- **Scenario:** mountains, lakes, green landscape, blue skies.
- **Avoid:** close-up portraits with red skin risk.
- **Rationale:** Saturated nature photography inspired by established Velvia palette.
- **Evidence:** `fujifilm-velvia`; grade `component_backed_editorial`.
- **Look strength:** 0.25; **film:** `fujichrome-velvia-50`; **optics:** `optical_vignetting`.
- **Depends on:** Wave 1. 

### 21. GR HDF Evening Lights (`ricoh-hdf-evening-stars-v07`)

- **Scenario:** isolated evening streetlights with clean sources.
- **Avoid:** clusters of blown-out LEDs or dense text signage.
- **Rationale:** Ricoh highlight diffusion combined with gentle cross-screen star; higher-risk creative editorial combo.
- **Evidence:** `ricoh-hdf`; grade `component_backed_editorial`.
- **Look strength:** 0.53; **film:** `none`; **optics:** `ricoh_hdf_diffusion`, `starburst_cross_screen`.
- **Depends on:** Wave 2. 

## Server implementation order

1. Load the authored YAML catalog as data into the **existing preset registry**, not as a separate Creative Presets microservice. Registry resolves film IDs and operator versions; validate parameters with existing typed bounds.
2. Emit immutable, fully expanded `render-recipe-v2` payload (not only a preset name), including profile bundle checksums, operator implementation versions, grain seed, stable user override values, source image digest and render-graph version.
3. Use the same render graph for preview and full develop, with resolution-invariant spatial effect parameters and masked source positions. Preview shall never be simply enlarged to become final output.
4. Add suggested-combo listing, scenario filters, readable short explanation and evidence label to the **current** Web Darkroom. Underlying Camera/Film/Optics selectors remain editable and compatible with manual recipes.
5. Add source-guided suggestions (simple tag/metadata heuristics only as an enhancement). **Do not infer subject identity, people traits or private data.** No cloud vision model required.
6. Publishing a rendition to PhotoPrism preserves input RAW, preset revision, full expanded recipe and output association. Existing same-album/new-album/folder UX unchanged.
7. Keep the previously published `golden_haze` ID and all `camera-presets.yaml` `composites` intact. The new `golden-haze-ii-v07` is opt-in, not a silent retune.

See [36](36-combo-evidence-and-provenance.md) for claim provenance, [37](37-combo-waves-and-acceptance.md) for delivery gates, and [`contracts/curated-combos-v07.yaml`](../contracts/curated-combos-v07.yaml) for authoritative initial values.
