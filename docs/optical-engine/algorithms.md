# Optical Effects Engine — Algorithm Specifications (Linux)

This subordinate engineering reference expands **the existing** `docs/21-optical-effects.md`. Use the deployed M-Film server renderer and its image/color operators. All algorithm sketches are implementation targets, **not** assertions that existing M-Film already provides them.

## Common assumptions for every module

- Input: full-resolution, color-managed linear-light RGB float image or tiles, with HDR values retained until tone mapping; image coordinates are always normalized relative to the *oriented and cropped* active image.
- Preserve alpha/mask semantics explicitly and use well-defined linear-light blending. No global 8-bit operations before output encoding.
- `intensity=0` means numerical bypass. For any effect, keep source original unchanged, and compare output in a controlled fixture.
- Distance/radius controls are proportional to image dimensions or diagonal. A 720px preview and a 4000px full render should have the same photographic composition, while fine texture may differ with scale.
- Use blur pyramids, separable convolutions, downsampled light maps or bounded-ROI PSF kernels, not large unbounded square convolution over a full 12–45MP image.
- Separate source detection and effect generation. Detect bright spots after normalization and exposure (and optionally before highlight compression) to capture genuinely energetic lights, preserving source coordinates across preview and final.
- Support `auto`, `manual`, `auto_plus_manual`, `off` source modes where appropriate. Manual source is a 2D normalized point with radius/weight. Exclusion masks can remove false-positive sources.
- A light source partly/outside frame must be supported with a manual coordinate range beyond [0,1] only if explicitly enabled in a future contract; the current recipe validates [0,1], so initial outside-frame effects are driven by boundary luminance and in-frame anchor.

## A. NEW — `optical_vignetting`

**Purpose:** subtle/strong intentional corner falloff, portrait subject emphasis, vintage-lens rendering. This is an exposure-domain effect, distinct from M-Film stock baked-in vignette and from camera/lens *correction*.

**Inputs:** `strength_stops` (0–3 EV, signed positive for darkening), `inner_radius` (0–1 normalized), `feather` (0.01–1), `center_x`, `center_y`, `aspect_ratio` (elliptical shaping), optional `shape_power` (rounded-rectangle to circular via superellipse), `highlight_protection` (0–1). UI default is subtle (e.g. 0.45 EV), with global optical strength 0 unless selected.

**Algorithm:** for pixel `p`, compute normalized elliptical radial distance `r(p)` around adjustable center. `w = smoothstep(inner_radius, inner_radius + feather, r)`; `gain = exp2(-strength_stops * w * master_strength)`; multiply linear RGB by `gain`, optionally protect high-luminance highlights through a documented mask. Smooth continuity at threshold. Do not hardcode photographic center if the user supplies another center.

**Verification:** neutral at 0 EV; center unaltered inside radius; corners monotonically darker; symmetric fixture for default center; no seams on tiles. When film-profile vignetting exists, use `vignette_policy=film|optical|stacked|disabled` or a clearly labeled equivalent resolved policy to prevent unintended double darkening.

## B. NEW — `lens_flare_ghosting`

**Purpose:** recognizable geometric reflections associated with a light source, especially low sun, windows and point emitters. Distinct from broad `vintage_veiling_flare`.

**Inputs:** `amount`, `ghost_count` (2–12), `spread`, `radius_fraction`, `chromatic_separation`, `hue_bias`, `aperture_blades` (4–12; optional rounded geometry), `softness`, `source_threshold`, `auto_source_limit`, per-source weight and manual anchors. User may adjust angle/axis offset if source geometry cannot be inferred.

**Algorithm:** from each selected source centroid `s` and image/optical center `c`, generate a reproducible family of reflection positions along a documented optical-axis proxy, e.g. `g_i = c + alpha_i (c - s)`; distribute positive/negative `alpha_i` deterministically from calibrated model coefficients. Render elliptical/circular/aperture-shaped smooth PSFs with varying scale, translucency, chromatic fringe and softness; attenuate based on source energy and global strength; composite into scene-linear buffer. `alpha_i` and ghost hue/radius must **not** be random from render to render. Use local highlight signal and edge masks so a uniformly bright wall does not create a cascade of phantom sources.

**No-source behavior:** automatic mode outputs baseline if no plausible compact source; manual source still works. Limit total energy and prevent clipped geometric stickers.

**Tests:** move a bright point across a synthetic frame and verify ghosts follow the expected axis; compare against veiling-only output; multiple lights create multiple appropriate ghost groups; deterministic seed and tile invariance.

## C. NEW — `starburst_cross_screen`

**Purpose:** 4-, 6-, or 8-point stars around small bright lights, analogous to star filters or aperture diffraction.

**Inputs:** `points` enum {4,6,8}, `angle_degrees` (0–180), `ray_length_fraction`, `ray_width`, `falloff`, `highlight_threshold`, `knee`, `max_sources`, `amount`, per-source control.

**Algorithm:** build smooth bright-point candidate map from highlight luma and a compactness/local-contrast test. For each candidate, convolve source energy with an oriented cross-ray PSF with `N` radial arms and decaying intensity, performed as a sum of efficient directional line blurs or sparse kernel application. Preserve compact center; multiple rays angle-locked to user setting; smoothly clamp brightness. Use finite support, not image-wide bright lines crossing every pixel.

**No-source/negative:** uniform white field should not produce dozens of stars; an ordinary portrait without compact highlight should remain largely neutral. Verify exactly N rays, angle rotation and source-position alignment.

## D. NEW — `anamorphic_streak`

**Purpose:** directional blue/white/amber cinematic streaks from exposed light sources, distinct from star-rays and general veil.

**Inputs:** `angle_degrees` (default 0 horizontal), `length_fraction`, `core_width`, `falloff`, `tint_rgb` or documented chromatic selector, `chromatic_split`, `threshold`, `knee`, `amount`, `auto_source_limit`.

**Algorithm:** create smooth light-only mask; apply fast 1-D anisotropic convolution along specified angle with a long-decay kernel, optionally use multiple frequency/radius kernels for bright core plus weak long tail. Tint signal in linear light and combine with source image using bounded energy-preserving or artistically controlled additive blend. If source detection is off but selected manually, anchor streaks only at supplied points and weights.

**Tests:** 0 degrees horizontal, 90 degrees vertical, wrap equivalence of 0/180, multiple sources, image-border extension, no streak from low-light source.

## E. NEW — `analog_light_leaks`

**Purpose:** irregular warm edge fogging inspired by accidental film light leaks; *not* a second LUT or non-licensed overlay texture.

**Inputs:** `seed_offset`, `amount`, `edge` enum {left,right,top,bottom,auto}, `coverage`, `width_fraction`, `feather`, `warmth`, `hue_variance`, `irregularity`, `bleed`, `frame_variation`, optionally `pattern_id` (versioned), alpha.

**Algorithm:** construct spatially smooth, physically plausible edge-anchored masks from low-frequency deterministic procedural noise / spline fields and one or more edge-origin gradients. Ensure random field is sampled in **global normalized coordinates** from `hash(original_sha256, recipe.seed, pattern_id, frame_id)` so changing image size, preview scale, worker count or tile order preserves its overall shape. Apply linear-light colored exposure/fog with soft shoulders and restrained channel response; optionally model multiple nested warm bands. Never use unlicensed stock texture files. Avoid a literal uniform orange overlay.

**Tests:** identical pattern for same source/recipe/seed; different seed changes pattern; preserved structure across preview/final; no unexplained central leak in edge-anchored mode; 0 strength is bypass.

## F. NEW — `lensbaby_sweet_spot`

**Purpose:** a movable sharp zone within gradually increasing softness, suitable for intimate portraits, flowers and still life.

**Inputs:** `focus_x`, `focus_y`, `focus_radius_fraction`, `transition_width`, `max_blur_radius_fraction`, `falloff_power`, `edge_bloom` optional, `amount`. Do not require a depth map.

**Algorithm:** evaluate a smooth radially increasing out-of-focus mask around the chosen sweet spot (not fixed center); build a multiresolution blur stack with kernels approximating circular aperture PSF or controllable Gaussian proxy. Blend per-pixel using mask, keeping focus center sharp, with anti-halo compositing near high contrast edges. Respect image orientation and output crop. Explicitly note it is a **2D artistic emulation** and cannot reconstruct real 3D defocus/occlusion from a single RAW without a depth map.

**Tests:** moving focus point moves sharp island; zero blur is neutral; a sharp target within focus radius retains measurable MTF/edge contrast; no abrupt transition rings; hair/faces not mutilated by layer bleed.

## G. NEW — `tilt_shift_miniature`

**Purpose:** familiar narrow focus band / miniature-city impression, particularly high-angle city views.

**Inputs:** `band_center_x`, `band_center_y`, `angle_degrees`, `sharp_band_width_fraction`, `transition_width`, `max_blur_radius_fraction`, `falloff`, `amount`, optional `vividness_boost` default **0** (do not force toy saturation).

**Algorithm:** compute signed distance from a rotated sharp-band centerline; output blur weight `w=smoothstep(half_width, half_width+feather, abs(distance))`. Build levels of blur, blend masked levels with smooth spatial transitions, optionally highlight-shaped bokeh where performance allows. The band must be rotatable and offset. Preserve sharpness inside selected band even on portrait-oriented images. Optional saturation is a separate control.

**Tests:** horizontal/diagonal/vertical bands; preserved sharp line, progressive top/bottom blur; crop/rotation invariance; no tile seams or depth-claim overstatements.

## H. REQUIRED COMPOSITE — `vintage_glass`

**Purpose:** a consistent period-lens character built from three **actual** suboperators and optional existing vignette. Do not represent it with a single LUT or saturation shift.

### H1 — Radial chromatic aberration (`vintage_glass_chromatic_aberration`)

- Controls: `red_shift_fraction`, `blue_shift_fraction`, `radial_power`, `center_x`, `center_y`, `amount`.
- Resample red and blue channel sampling positions radially using continuous interpolation and a center-dependent field. Use inverse mapping, explicit border strategy and document that this is lateral CA, not arbitrary hue shift. No magenta fringe pasted along every edge; strength defaults modest. Works on linear RGB after camera correction.
- Test: center region stable, increasing displacement toward edge, symmetric edge chart, no large color holes.

### H2 — Edge softness (`vintage_glass_edge_softness`)

- Controls: `center_clear_fraction`, `edge_blur_radius_fraction`, `falloff_power`, `amount`.
- Compute position-dependent blur radius increasing toward frame edges; reuse scale-space blur pyramid. Retain subject center. No blanket downsampling or poor JPEG encoding as a surrogate.
- Test: center resolution target sharp, outer target progressively softer, no ring transition.

### H3 — Barrel distortion (`vintage_glass_barrel_distortion`)

- Controls: `k1`, optional `k2`, `center_x`, `center_y`, `crop_mode` enum {transparent_edge,auto_crop,extend}, `amount`.
- Apply radial coordinate warp with inverse sampling: `r_distorted = r * (1 + k1*r^2 + k2*r^4)` and solve target-to-source consistently to avoid holes. Define coefficient sign via a calibration fixture; the apparent barrel direction must be correct in documentation. Interpolate at float precision; prevent invalid coordinates; account for crop and lens correction already applied upstream.
- Test: straight-grid deformation direction, frame corner policy, no holes/discontinuous bands; EXIF focal length stays original.

### H4 — Compound recipe

A `vintage_glass` **preset** expands deterministically into H3 geometric warp -> H1 CA -> H2 edge softness -> optional `optical_vignetting`. Each component remains independently adjustable in Advanced controls and stored in the same recipe `optical.stack`. The recipe must preserve exact expansion and version for future re-renders. It may stack with the existing six effects subject to explicit conflict warnings.

## Preserve existing six as six independent operators

Do not replace `soft_sun_glow`, `ricoh_hdf_diffusion`, `black_pro_mist_like`, `vintage_veiling_flare`, `film_halation_extra`, or `orton_glow`. Their detailed contracts remain in the previous revision of `docs/21-optical-effects.md`; v0.6 incorporates them through a stable lookup table. Keep reference images and old defaults for migrated recipes.

## Technical references (implementation patterns, not code licenses)

- darktable 5.6 Lens Correction documents simulation of distortion, TCA, vignetting: https://docs.darktable.org/usermanual/5.6/en/module-reference/processing-modules/lens-correction/
- darktable Diffuse or Sharpen describes spatial diffusion and limitations at reduced preview sizes: https://docs.darktable.org/usermanual/development/en/module-reference/processing-modules/diffuse/
- Ricoh HDF official sample comparison: https://www.ricoh-imaging.co.jp/english/products/gr-3/special/hdf/
- Obtain compatible licensed assets/code only after verifying actual license and attribution requirements. Commercial filter names and camera names are descriptive references, not proof of calibrated equivalence.
