# 19 — Mandatory Camera Look Catalog and Modeling Guidelines

Every entry in the table is a **required functional Linux preset**, not an aspirational future slot. Implement independently tunable color, tone, and (where appropriate) texture parameters and supply visual regression fixtures. Camera-specific look names are identification labels for independently authored emulations, not manufacturer-provided profiles.

| Stable ID | Inspiration | Initial rendering character / development targets | Distinct validation focus |
|---|---|---|---|
| `leica_m8_ccd` | Leica M8 | Dense midtone contrast, characteristic muted-vs-rich color separation, cool-neutral shadows (tune from reference rather than asserting universal traits) | red clothing vs skin, foliage, neutral gray |
| `leica_m9_ccd` | Leica M9 | Rich color separation, deep-but-detailed shadows, controlled reds and bright skin transitions | red/saturated patches, face/highlight crossover |
| `fujifilm_s5_pro` | Fujifilm FinePix S5 Pro | Soft highlight shoulder, conservative skin chroma, gentle portrait tonality | gradient highlights, skin under daylight/tungsten |
| `nikon_d200_ccd` | Nikon D200 | Early digital CCD aesthetic, firmer contrast and vivid hues, restrained shadow noise styling | foliage, sky, low-to-mid ISO color |
| `pentax_645d_ccd` | Pentax 645D | Landscape/medium-format inspired tonal separation, subdued sharpening, rich muted midtones | foliage/stone/sky, highlight neutrality |
| `ricoh_gr_iii_positive` | Ricoh GR III Positive Film | Assertive contrast, saturated but selective color, crisp urban rendering | blue sky vs reds, concrete, skin neutrality |
| `sigma_dp2_merrill_foveon` | Sigma DP2 Merrill | Fine-texture emphasis, high perceived microcontrast, idiosyncratic color separation under good light | textures, fine detail, metamerism limitations |
| `fujifilm_xpro3_classic_negative` | Fujifilm X-Pro3 Classic Negative | Stronger tonal contrast and distinctive consumer-negative-inspired color separation | sunlit urban scenes, shadow hue, skin and green |
| `fujifilm_x100vi` | Fujifilm X100VI (Reala Ace / X-Trans 5) | Ultra-high resolution modern digital clarity, wide highlight headroom, neutral-warm fidelity | high-detail street, architecture, natural skin tones |
| `hasselblad_500cm` | Hasselblad 500 C/M (Zeiss Planar 80mm) | Medium-format tonal gradation, silky highlight roll-off, refined microcontrast, warm organic skin rendering | studio portraiture, fabric texture, highlight roll-off |
| `leica_m6_rangefinder` | Leica M6 (Leitz Summicron 35mm) | High optical microcontrast, deep authoritative blacks, documentary street snap, warm highlight glow | street scenes, high-contrast monochrome/color, edge bite |
| `contax_t2_sonnar` | Contax T2 (Carl Zeiss Sonnar 38mm) | Punchy 90s flash/snapshot contrast, deep saturation, cool deep shadows, crisp highlight bite | fashion flash, vibrant street, cool blue shadows |
| `mamiya_7_ii` | Mamiya 7 II (Sekor 80mm L) | Ultra-sharp flat-field neutrality, high dynamic headroom, velvety midtones, pristine architectural clarity | landscape horizon, architecture, fine texture fidelity |
| `olympus_om1_zuiko` | Olympus OM-1 (OM Zuiko 50mm) | Vintage Japanese glass warmth, lifted gentle shadow toe, warm golden highlights, organic soft microcontrast | golden hour portraits, foliage, warm amber highlights |
| `pentax_k1000` | Pentax K1000 (SMC Pentax 50mm) | Super Multi-Coated flare resistance, deep clean blacks, natural neutral-warm daylight balance | outdoor scenes, natural skin, high-contrast daylight |
| `pentax_67` | Pentax 67 (SMC Takumar 105mm) | Dreamy medium format portraiture, velvety shallow-depth roll-off, rich dimensional microcontrast, flattering warm skin | shallow DOF portraits, skin tone fidelity, highlight roll-off |
| `rolleiflex_28f_tlr` | Rolleiflex 2.8F TLR (Zeiss Planar) | Classic 6×6 TLR portraiture, smooth highlight compression, gentle toe, warm amber/sepia leaning midtones | classic portraiture, creamy bokeh transition, soft contrast |
| `zenit_e_ttl` | Zenit E / TTL (Helios-44 58mm f/2) | Vintage single-coating character, swirly bokeh glass tonality, amber flare warmth, lifted earthy shadow floor | backlit portraits, vintage foliage, swirly edge highlights |
| `zorki_4` | Zorki 4 (Jupiter-8 50mm f/2) | Carl Zeiss Sonnar heritage, luminous wide-open glow, creamy highlight bloom, warm vintage midtones | low-light portraits, luminous skin, classic street |
| `polaroid_sx70_instant` | Polaroid SX-70 Instant Folding SLR | Compressed dynamic range, chemical cyan-green tinted shadows, warm creamy highlights, organic emulsion dye feel | snapshot portraits, diffuse daylight, cyan-green shadows |
| `lomo_lca` | Lomo LC-A (Minitar-1 32mm) | High punchy contrast, saturated lomography color pop, deep crushed gritty blacks, warm-shifted snapshot grit | street snapshots, vivid saturated colors, deep blacks |
| `neutral` | Internal baseline | Identity camera look (not identity input normalization) | reference control |

`ricoh_gr_iii_hdf` is a **composite camera preset**, not a separate CCD-look transform: `ricoh_gr_iii_positive` or `neutral` + `ricoh_hdf_diffusion`. See [21](21-optical-effects.md). The artistic `golden_haze` combination is an original creative preset, not a historical camera profile.

## Provenance tiers

- `inspired`: independently tuned against descriptive references or a small public sample collection. This is the initial allowed launch tier for *all* looks; avoid "accurate reproduction" marketing.
- `measured`: reference target-camera JPEG/DNG and SX510 RAW calibrated with charts and repeatable illuminants, documented processing settings and sample rights.
- `validated`: passing perceptual and color metrics on a withheld scene corpus with a documented lighting and exposure domain. Even this does not imply optical/sensor equivalence.

Every look must carry provenance metadata, version, `reference_manifest`, `profile_params_hash`, allowed illuminants, quality tier and known failure modes. A default starting parameter set is fine; it must actually modify images and yield differentiable outputs. No placeholder implementation returning the neutral profile.

## Modeling methodology

1. Normalize SX510 DNG to a common **linear working RGB** color space with a verified Canon source profile. White balance is always applied before creative camera-look mapping.
2. Implement the target creative response as a deterministic rendering transform: tone curve / shoulder / toe, per-hue chroma shaping, luma-dependent color shift, selective saturation and optional local microcontrast or noise character.
3. Use a tunable, explicitly versioned `camera_look_strength` in range `[0,1]`. Define the blend domain (see [20](20-creative-pipeline.md)); do not mix nonlinear sRGB code values without a documented reason.
4. Where target-camera matching material is available, fit scene-to-output transform on calibration data and use **held-out images** for validation. Never train and judge on the same images.
5. Keep spatial optical effects out of `camera_look` to avoid hard-coded double glow, grain or halation. `sigma_dp2_merrill_foveon` may include a separately identified local-detail component; it must be disableable.
6. Expose a machine-readable neutral mode for regression and show whether a look is `inspired` vs `measured` in CLI/API.

## Reference directions and legal restrictions

- Cobalt CCD Fever lists Leica M8, Leica M9, Fuji S5 Pro, Pentax 645D and Nikon D200 as emulation subjects. It is evidence that the *idea* exists, **not an asset supplier**: https://www.cobalt-image.com/product/ccd-fever-for-adobe/
- Ricoh documents Positive Film as an Image Control mode: https://www.ricoh-imaging.co.jp/english/products/gr-3/spec/
- Fujifilm X-Pro3 documents Classic Negative as a built-in simulation: https://fujifilm-dsc.com/en-int/manual/x-pro3/menu_shooting/image_quality_setting/index.html
- Some independent Fuji LUTs are CC BY-NC-SA 4.0 and therefore **must not be copied into unrestricted distributable bundles** without a compatible license/use model: https://github.com/eowynring/fujifilmcameraprofiles

Do not download copyrighted professional LUT packs, reverse-engineer commercial plugins, redistribute comparison photographs without permission, or represent a generated look as an official camera manufacturer's profile. Develop original parameters or use clearly licensed sources after auditing their precise license scope.

## Minimum test scenes for each look

ColorChecker/reference gray under D65; skin of varying tones with proper permissions; high-contrast midday sky; foliage; dusk artificial light; saturation stress chart; low-ISO fine textures. Compare baseline neutral, look-only, film-only and combined-stack results. See [24](24-creative-test-plan.md).
