# 36 — Community evidence, provenance and limits

**Scope:** curated combo presets inside the **existing Linux M-Film developer** only. Research checked 2026-11-09.

## A critical distinction

- **Community-proven building blocks**: Portra 400, Kodak Gold 200, Tri-X and related Fuji film-simulation recipe families are demonstrably popular. This is supported by Fuji X Weekly's most-viewed 2025 ranking and community discussions.
- **Manufacturer-confirmed effect behaviour**: Ricoh HDF's bright-area diffusion, Black Pro-Mist highlight bloom/contrast and CineStill 800T halation are documented by their makers.
- **M-Film combination presets**: the *precise* camera-emulation + film-emulation + digital-optics triples in this file are **original editorial interpretations**. Do **NOT** label them "community-proven recipes" unless actual direct evidence for that exact configuration exists. In particular, no evidence demonstrates that a digital Leica M9 can physically expose Kodak film; the layers here are software artistic simulations.
- **Numerical values** are proposed safe starting defaults, not measured calibration or source-provided values. They must be visually validated before publication.
- Engagement metrics for a published recipe **do not** prove its objective color fidelity or universal photographic merit.

## Evidence grades

- `direct_recipe_family_adapted` — a closely related, publicly documented camera-simulation/film-style pair exists (e.g., Fuji Classic Negative with a Gold-inspired recipe); the M-Film version still is *not* an exact port.
- `component_backed_editorial` — photographic constituents and intended scenario have external support, but the triple itself is original.
- `editorial_only` — an experimental artistic proposal justified by photographic principles, without a convincing real-world popularity claim. Show as "Creative" and do not sort above the more established everyday choices.

## Primary source register

| ID | Kind | Source | What it actually supports |
|---|---|---|---|
| `fxw-2025` | community_ranked_views | [Fuji X Weekly: Top 25 Most Popular Film Simulation Recipes of 2025](https://fujixweekly.com/2025/12/15/top-25-most-popular-film-simulation-recipes-of-2025/) | Popular recipe families: Reggie’s Portra, Kodak Portra 400, Kodak Gold 200 and Tri-X; Classic Chrome and Classic Negative as recurring foundations. Does not validate M-Film combinations. |
| `fxw-mid-2025` | community_ranked_views | [Fuji X Weekly: 25 Most Popular Film Simulation Recipes of 2025 (midyear)](https://fujixweekly.com/2025/06/30/25-most-popular-film-simulation-recipes-of-2025-so-far/) | Portra, Gold, Tri-X, CineStill-inspired recipes and Classic Negative families are widely viewed; no evidence of exact triple combos. |
| `reddit-fuji-thread` | community_discussion | [r/fujifilm: Top Film Simulations mega-thread](https://www.reddit.com/r/fujifilm/comments/1bwijjh/top_film_simulations_mega_thread/) | Photographers discussing daily-use Gold, Portra and Superia recipes; anecdotal preference, not proof of exact presets. |
| `reddit-gold-classicneg` | community_recipe | [r/fujifilm: My Kodak Gold 200 recipe for Fuji X and GFX](https://www.reddit.com/r/fujifilm/comments/1x6vhqm/my_kodak_gold_200_recipe_for_fuji_x_and_gfx/) | An October 2026 user recipe explicitly combines Classic Negative with a Kodak Gold 200-inspired output. Not exact conversion coefficients for our engine. |
| `fujifilm-filmsim` | manufacturer | [Fujifilm: Film Simulation product guide](https://www.fujifilm-x.com/en-us/products/film-simulation/) | Classic Negative tonal character; portrait-friendly Pro Neg; Nostalgic Negative warm highlights. Not LUT licensing. |
| `ricoh-hdf` | manufacturer | [Ricoh official GR III HDF comparison](https://www.ricoh-imaging.co.jp/english/products/gr-3/special/hdf/) | Highlight diffusion creates a softer bright-area rendition and slightly lowered contrast. |
| `tiffen-bpm` | manufacturer | [Tiffen Black Pro-Mist overview](https://tiffen.com/products/4-x-5-65-black-pro-mist-filter) | Black Pro-Mist gently modifies highlights and contrast for photographic and cinematic uses. |
| `cinestill-800t` | manufacturer | [CineStill Film: 800T in Your Toolbox](https://cinestillfilm.com/blogs/news/cinestill-800t-in-your-toolbox) | 800T tungsten/night shooting and distinctive red halation around bright practical lights. |
| `cinestill-faq` | manufacturer | [CineStill FAQ: halation and light leaks](https://cinestill.film/pages/frequently-asked-questions) | Film halation mechanism and distinction from incidental light leaks. |
| `kodak-trix` | manufacturer | [Kodak Tri-X 400 product guide](https://www.kodak.com/en/still-film/product/professional/tri-x-400-film/) | B&W grain, contrast, reportage and street suitability. |
| `fujifilm-velvia` | manufacturer | [Fujifilm film-simulation shooting menu, Velvia](https://fujifilm-dsc.com/en/manual/gfx50r/menu_shooting/image_quality_setting/index.html) | Velvia vivid and contrasty for nature photography. |

## Licensing and representation

1. Links are **research evidence**, not LUT or image redistribution permission. No copying Fuji X Weekly photo assets, paid Cobalt LUTs, Ricoh images, Tiffen imagery or creator presets into the binary without a separate license.
2. Manufacturer camera and film names may be used descriptively with clear *unofficial-inspired look* labeling; avoid official endorsement claims.
3. Never clone named creator recipes such as Reggie's Portra under the original name without evidence and appropriate rights. Our `Portra Soft Portrait` is an **independently tuned creative preset** based on a popular direction, not Reggie's exact recipe.
4. For source confidence, distinguish `source_validated` (reference exists) from `render_validated` (the M-Film implementation was actually compared on RAW fixtures); only the second permits a READY label.
5. For every candidate, retain source URLs and an explanation of why the pairing is reasonable. Update references when upstream pages disappear.
