# M-Film CHDK Edition — Server-First Film Lab

**English engineering specification · Revision 0.7 · 2026-11-09 · Status: design, not implemented**

Project target device: **Canon PowerShot SX510 HS** (Canon DryOS / CHDK). **Current v0.6 implementation assignment: Linux server only; no CHDK development.** Primary developer: **self-hosted Linux service**. Offline developer: **same film-processing core, ported to the camera**. Library destination: **PhotoPrism**.

## Non-negotiable product model

1. Load a virtual 12-, 24-, or 36-frame film roll, choose its film profile, and shoot RAW/DNG without seeing unprocessed images.
2. Camera processing **does not run in the capture path**. When a roll is finished, upload the **original RAW/DNG** to a reachable Linux receiver. The receiver develops it at the best available resolution, stores the originals, and publishes finished JPEGs to PhotoPrism.
3. **Internet is not required:** a local LAN connection to the Linux server is sufficient. The SX510 HS has built-in 2.4 GHz Wi-Fi, but arbitrary CHDK TCP/IP support on this particular port remains **unproven**. USB/PTP and SD ingest are required fallbacks.
4. When the server is unavailable, the user may invoke **Develop on Camera** for the completed roll, using the **same film algorithms and profile definitions** as the server. Do not quietly switch to unrelated Canon effects or generic LUTs.
5. Server-developed images may later be synced **back** to the camera to populate its developed gallery. Offline-developed images are usable immediately; on reconnect, the server should still archive RAW and may create an additional full-resolution rendition without overwriting the offline result.
6. Canon's built-in JPEG generation and playback require investigation. The no-preview policy must be **implemented and hardware-verified**, not assumed; the original DNG must never be destroyed in the attempt.


## v0.4: Camera Look + Optical Engine (REQUIRED ON LINUX)

The new work extends the existing server-first M-Film project, **not replaces it**. Linux must implement all eight artistic camera rendering profiles (Leica M8/M9, Fujifilm S5 Pro, Nikon D200, Pentax 645D, Ricoh GR III Positive Film, Sigma DP2 Merrill, Fujifilm X-Pro3 Classic Negative) plus independent optical bloom, sunlight glow, Ricoh HDF, veiling flare, diffusion-filter emulation, halation and Orton. Preserve the original M-Film Film Stock layer. Composite presets include **Golden Haze**.

The camera/CHDK must store and transmit complete **recipe v2** selections when its UI port is available. Camera-native rendering of these new effects is **experimental and non-blocking**; preserve server-first/full-quality and existing film-only offline fallback. No real camera firmware or signed ROM modification is required to implement Linux effects.

**Start with [`docs/25-creative-implementation-roadmap.md`](docs/25-creative-implementation-roadmap.md) and [`docs/20-creative-pipeline.md`](docs/20-creative-pipeline.md).**

## v0.5: Web Darkroom and bidirectional PhotoPrism (REQUIRED ON LINUX)

A browser-based development studio is now part of the **mandatory Linux deliverable**. Its workflow is **Select Source Material (upload DNG/NEF/other supported RAW, PhotoPrism folder or album, or M-Film roll) → Select Camera Look → Select Film Stock → Optional Optical Effects → Low-resolution Preview → Full-resolution Develop → Publish to PhotoPrism**. A PhotoPrism album and filesystem folder are distinct; source selection and output album/folder must be independently configurable. Existing PhotoPrism RAWs must be usable without browser re-upload, with non-destructive versioned renditions. See [27](docs/27-web-darkroom-product.md), [28](docs/28-web-darkroom-ui.md), [29](docs/29-photoprism-source-and-destination.md), [30](docs/30-web-raw-ingest.md), [31](docs/31-web-previews-and-jobs.md), [32](docs/32-web-publication.md), [33](docs/33-web-security-deployment.md), [34](docs/34-web-implementation-and-acceptance.md).

**Start implementation with `AGENTS.md` and `docs/34-web-implementation-and-acceptance.md`.**

## Spec navigation

| Document | Purpose |
|---|---|
| [AGENTS.md](AGENTS.md) | Instructions for implementation agents |
| [00 Scope](docs/00-scope-and-success.md) | Product boundaries and acceptance gates |
| [01 User experience](docs/01-user-experience.md) | Camera, development and sync flows |
| [02 Architecture](docs/02-system-architecture.md) | Shared core, component boundaries and data flows |
| [03 CHDK device](docs/03-chdk-camera-port.md) | Hardware port, safety and feasibility |
| [04 Roll / persistence](docs/04-roll-and-storage.md) | State machines, manifests, filenames, durability |
| [05 Shared film renderer](docs/05-shared-film-engine.md) | One algorithm, two targets, parity and versioning |
| [06 RAW pipeline](docs/06-raw-dng-pipeline.md) | DNG decode, color, geometry, JPEG |
| [07 Development / gallery](docs/07-development-and-gallery.md) | Server-first / offline fallback / return sync |
| [08 Linux server](docs/08-linux-service.md) | Receiver, worker, DB, deployment |
| [09 Sync API](docs/09-sync-api.md) | Idempotent resumable protocol |
| [10 Transports](docs/10-transports.md) | Wi-Fi research, USB, SD |
| [11 PhotoPrism](docs/11-photoprism.md) | Publishing, indexing and re-rendering |
| [12 Security / recovery](docs/12-security-and-recovery.md) | Threats, safe defaults, integrity |
| [13 Tests](docs/13-testing-and-acceptance.md) | Host CI, reference corpus, hardware gates |
| [14 Roadmap](docs/14-implementation-roadmap.md) | Agent tasks, dependencies and deliverables |
| [15 Risks](docs/15-risks-and-open-questions.md) | Unknowns, alternatives and decision gates |
| [16 References](docs/16-references-and-licensing.md) | Source URLs, confirmed vs. unconfirmed claims |
| [17 Glossary](docs/17-glossary.md) | Naming and terminology |
| [18 Creative scope](docs/18-creative-look-requirements.md) | Server requirements and device experimental scope |
| [19 Camera looks](docs/19-camera-look-catalog.md) | All eight mandated look specifications |
| [20 Render pipeline](docs/20-creative-pipeline.md) | Color management, composition, performance |
| [21 Optical engine](docs/21-optical-effects.md) | Bloom, HDF, veil, sun glow, halation, Orton |
| [22 CHDK creative](docs/22-camera-chdk-creative.md) | Required device metadata vs experimental rendering |
| [23 Recipes & API](docs/23-recipe-compatibility-api.md) | Recipe v2, v1 migration, rerender API |
| [24 Creative tests](docs/24-creative-test-plan.md) | Numeric, visual and hardware acceptance |
| [25 Creative roadmap](docs/25-creative-implementation-roadmap.md) | Concrete work packages for agent |
| [26 Sources & licenses](docs/26-creative-sources-licensing.md) | Reference validation and asset legal constraints |
| [27 Web product](docs/27-web-darkroom-product.md) | Web-based full RAW developer and PhotoPrism source/destination |
| [28 Web UI](docs/28-web-darkroom-ui.md) | Material, Camera Look, Film Stock, Optics, preview and publishing UX |
| [29 PhotoPrism connector](docs/29-photoprism-source-and-destination.md) | Select source album/folder and independent publish destination |
| [30 RAW upload](docs/30-web-raw-ingest.md) | NEF/DNG and source normalization |
| [31 Preview/jobs](docs/31-web-previews-and-jobs.md) | Reduced previews, final jobs and provenance |
| [32 Publishing](docs/32-web-publication.md) | PhotoPrism folder/album output |
| [33 Web security](docs/33-web-security-deployment.md) | Authentication, path isolation and deployment |
| [34 Web roadmap](docs/34-web-implementation-and-acceptance.md) | Mandatory tasks and acceptance cases |
| [contracts/](contracts/) | API, example manifests, creative recipes, preset registry, proposed initial artistic parameters and creative endpoint extension |
| [templates/](templates/) | Hardware probe and phase report templates |

## Key decisions

- **Server-first**, not camera-first. Upload original DNG, **then** render on Linux; do not upload only a low-resolution already-developed JPEG.
- **One portable C film core** compiled into host and camera binaries. Linux may use Python/FastAPI for orchestration, but not an independently reimplemented film look.
- On-camera rendering is a deliberate **offline fallback**, not mandatory after every exposure; lower offline output resolution is allowed only if explicitly labeled.
- **Film-locking** at roll creation and immutable RAW originals. Re-development creates a new rendition, never rewrites history.
- Network access is a research milestone, not a premise. An unavailable or powered-off camera cannot push files and is not a continuously running server.
- **No automatic deletion** of originals, either after upload or after development.

## What this ZIP is

A complete **implementation specification and example wire contracts**, not a firmware build, running service, or licensed copy of M-Film / CHDK. Obtain and audit upstream code separately. For verified upstream facts and caveats, see [sources](docs/16-references-and-licensing.md).

## v0.6: Server Optical Engine in-place expansion (MANDATORY)

**Current task is Linux/server only.** Extend the **existing** six Optical Effects, not a separate extension or renderer. Required: seven new standalone effects (`lens_flare_ghosting`, `starburst_cross_screen`, `anamorphic_streak`, `analog_light_leaks`, `optical_vignetting`, `lensbaby_sweet_spot`, `tilt_shift_miniature`) plus `vintage_glass` compound (actual barrel distortion, radial chromatic aberration, edge softness, optional vignette). All old six, all Camera Looks and Film Stocks continue to work. Existing Web Darkroom Step 4 and PhotoPrism integration are reused.

Start at [docs/21-optical-effects.md](docs/21-optical-effects.md) and the detailed [Wave 1/2/3/5/10 implementation plan](docs/optical-engine/waves.md). Other subordinate Linux engineering references live in [docs/optical-engine/](docs/optical-engine/). The machine-readable effect registry is [contracts/optical-effects-catalog.yaml](contracts/optical-effects-catalog.yaml).

This archive contains the **full previous v0.5 specification amended in place**; existing CHDK documentation is preserved for project continuity but the new Wave 1–10 work does **not** require any camera implementation.


## v0.7: Curated camera + film + optics presets (MANDATORY, SERVER ONLY)

Add **21 fully editable, source-annotated composite recipes** to the **existing** creative preset selector. The actual pairing recommendations are original informed editorial choices; do not present them as scientifically calibrated camera reproduction or directly community-tested triples. Validate and activate progressively in Waves 1/2/3/5/10 while preserving all existing effects, presets, APIs, and PhotoPrism workflow.

- [35 — Curated combos](docs/35-curated-combination-presets.md)
- [36 — Research and evidence](docs/36-combo-evidence-and-provenance.md)
- [37 — Waves, Web UI and acceptance](docs/37-combo-waves-and-acceptance.md)
- [Catalog data](contracts/curated-combos-v07.yaml) and [catalog schema](contracts/curated-combos-v07.schema.json)

**Implementation entry point: [`AGENTS.md`](AGENTS.md) and [37](docs/37-combo-waves-and-acceptance.md).** Entire specification remains server-first; this v0.7 delivery contains no CHDK implementation assignment.
