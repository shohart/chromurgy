# Chromurgy

<p align="center">
  <img src="assets/chromurgy-banner.jpg" alt="Chromurgy Banner" width="100%">
</p>

<p align="center">
  <strong>An open-source digital darkroom for RAW development, film emulation and computational photography.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/RAW-Processing-orange.svg" alt="RAW Processing">
  <img src="https://img.shields.io/badge/Film-Simulation-red.svg" alt="Film Simulation">
  <img src="https://img.shields.io/badge/Sensors-CCD%20%7C%20Foveon-blue.svg" alt="Sensors">
  <img src="https://img.shields.io/badge/Optics-14%20Effects-amber.svg" alt="Optical Engine">
  <img src="https://img.shields.io/badge/Self--Hosted-PhotoPrism-green.svg" alt="Self-Hosted">
  <img src="https://img.shields.io/badge/License-GPL--2.0-blueviolet.svg" alt="License">
</p>

---

## The Philosophy of Chromurgy

> **Chromurgy** (*Chroma* [Greek *χρῶμα*, color / spectrum] + *-urgy* [Greek *-(ο)υργία*, the craft, transmutation, or transformative art as in *metallurgy* and *thaumaturgy*]) — **the art and craft of color transformation.**

Chromurgy bridges the gap between classic photochemical darkroom craft and modern computational photography. It takes unadulterated sensor RAW data and applies physically inspired color science, analog film response curves, legendary digital sensor signatures, and physics-based optical aberrations to create images with distinct artistic identity.

---

## Core Capabilities

- **RAW Processing**
  - Native handling of Canon `.CR2` / `.DNG`, Nikon `.NEF`, Sony `.ARW`, and local camera rolls.
  - High-precision demosaicing, highlight recovery, custom Kelvin / tint white balancing, and geometry correction.
  - Non-destructive processing pipeline: source RAW files remain pristine and immutable.

- **Film Simulation**
  - Authentic color and tone transfer algorithms from our shared film engine.
  - Classic stocks: Kodak Portra (160/400), Ektar 100, Tri-X 400, Fujifilm Velvia 50, Provia 100F, Classic Chrome, Ilford HP5 Plus, CineStill 800T, and more.
  - Hardware-calibrated halation and realistic film grain synthesis using seeded deterministic PRNG.

- **Camera Looks (Digital Sensor Signatures)**
  - Emulations of legendary digital sensors with unique spectral and tonal character:
    - **Leica M8 / M9** (Kodak KAF-18500 CCD color rendition)
    - **Fujifilm FinePix S5 Pro** (Super CCD SR dual-photodiode dynamic range)
    - **Nikon D200** (Classic warm CCD color science)
    - **Pentax 645D** (Kodak 40MP Medium Format CCD)
    - **Ricoh GR III** (High-contrast Positive Film look)
    - **Sigma DP2 Merrill** (Foveon X3 direct image sensor micro-contrast)
    - **Fujifilm X-Pro3** (Classic Negative profile)

- **Optical Effects Engine**
  - 14 distinct optical operators simulating vintage optics, glass flaws, and atmospheric filtration:
    - *Compound*: **Vintage Glass** (true radial barrel distortion, lateral chromatic aberration, edge softness, corner vignetting).
    - *Selective focus*: **Tilt-Shift Miniature**, **Lensbaby Sweet Spot**.
    - *Atmospheric & Flares*: **Anamorphic Streak**, **Cross-Screen Starburst**, **Lens Flare & Ghosting**, **Analog Light Leaks**, **Optical Vignetting**.
    - *Diffusion & Glow*: **Ricoh HDF**, **Bloom**, **Veiling Flare**, **Sunlight Glow**, **Orton Effect**, and **Diffusion Filtration**.

- **Curated Combination Presets**
  - 21 community-inspired, fully editable recipes seamlessly pairing Camera Look + Film Stock + Optical Stack.
  - Instant live rendering in preview resolution and full-fidelity export.

- **Self-Hosted & PhotoPrism Integration**
  - Native bidirectional connection to [PhotoPrism](https://www.photoprism.app/).
  - Browse live PhotoPrism folders and albums directly in the Web Darkroom.
  - Direct server-side RAW resolution without re-uploading large files through the browser.
  - Versioned publishing directly into destination PhotoPrism collections.

- **Server-First with Hardware Fallback**
  - Powerful Linux backend with responsive browser-based Web Darkroom.
  - Portable C core engine (`shared/film_core`) ensuring exact rendering parity between high-performance server processing and offline camera firmware ports.

---

## Architecture Overview

```
+-------------------------------------------------------------------------------+
|                             Chromurgy Darkroom                                |
+-------------------------------------------------------------------------------+
                                      |
         +----------------------------+----------------------------+
         |                                                         |
         v                                                         v
+------------------+                                      +------------------+
|   Web Darkroom   |                                      |   Linux Server   |
| (Browser Studio) | <==== REST API / WebSockets =======> | (FastAPI Engine) |
+------------------+                                      +------------------+
         |                                                         |
         | Live Preview / Sliders / Presets                        |
         v                                                         v
+-------------------------------------------------------------------------------+
|                       Chromurgy Core Rendering Pipeline                       |
|                                                                               |
|   [ RAW Ingest ]                                                              |
|          |                                                                    |
|          v                                                                    |
|   [ White Balance & Demosaic ] (Custom Kelvin / As-Shot / Camera Profile)     |
|          |                                                                    |
|          v                                                                    |
|   [ Camera Look Layer ] (Leica M9, Fuji S5 Pro, Nikon D200, Sigma Foveon...)   |
|          |                                                                    |
|          v                                                                    |
|   [ Film Stock Layer ] (Portra, Tri-X, Velvia, CineStill, Ektar...)           |
|          |                                                                    |
|          v                                                                    |
|   [ Optical Effects Engine ] (Vintage Glass, Tilt-Shift, Flares, Bloom...)    |
|          |                                                                    |
|          v                                                                    |
|   [ Color Transform & Jittered Grain ] (Deterministically Seeded)             |
+-------------------------------------------------------------------------------+
         |                                                         |
         v                                                         v
+------------------+                                      +------------------+
| Full JPEGs / Web |                                      |    PhotoPrism    |
| (Export Library) |                                      |  (Auto-Publish)  |
+------------------+                                      +------------------+
```

---

## Quick Start

### Running the Web Darkroom

```bash
# Clone the repository
git clone https://github.com/shohart/chromurgy.git
cd chromurgy

# Set up Python environment
cd src/server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Launch Chromurgy Web Darkroom
chromurgy-web --host 0.0.0.0 --port 8766
```

Open your browser at `http://localhost:8766/darkroom/` to enter the digital darkroom.

### Command-Line Development

```bash
# Direct RAW development using recipe
chromurgy-develop --input sample.dng --profile Portra400 --recipe recipe.json --output result.jpg
```

---

## Documentation Navigation

| Document | Purpose |
|---|---|
| [AGENTS.md](AGENTS.md) | Agent contracts and active implementation assignments |
| [00 Scope & Success](docs/00-scope-and-success.md) | Boundaries, criteria, and acceptance gates |
| [01 User Experience](docs/01-user-experience.md) | Darkroom workflows, development, and sync |
| [02 System Architecture](docs/02-system-architecture.md) | Shared core, engine boundaries, and data flows |
| [05 Shared Film Core](docs/05-shared-film-engine.md) | Core algorithm parity and versioning |
| [06 RAW Pipeline](docs/06-raw-dng-pipeline.md) | DNG/NEF decoding, color spaces, and geometry |
| [11 PhotoPrism](docs/11-photoprism.md) | Bidirectional library sync and publication |
| [18 Creative Requirements](docs/18-creative-look-requirements.md) | Creative looks and optical requirements |
| [19 Camera Looks](docs/19-camera-look-catalog.md) | Specification of all eight sensor looks |
| [20 Creative Pipeline](docs/20-creative-pipeline.md) | Color management, blending, and performance |
| [21 Optical Effects Engine](docs/21-optical-effects.md) | Detailed optics algorithms and compound models |
| [27 Web Darkroom Product](docs/27-web-darkroom-product.md) | Product definition for browser darkroom |
| [28 Web UI](docs/28-web-darkroom-ui.md) | Layout, controls, and interaction design |
| [35 Curated Combinations](docs/35-curated-combination-presets.md) | 21 curated combination presets |
| [36 Presets Provenance](docs/36-combo-evidence-and-provenance.md) | Aesthetic provenance and references |
| [37 Wave Acceptance](docs/37-combo-waves-and-acceptance.md) | Release waves and verification suites |

---

## License

Chromurgy is free and open-source software distributed under the terms of the **GNU General Public License v2.0 (GPL-2.0)**.
See the `LICENSE` file for details.
