# CURRENT ASSIGNMENT (v0.7): CURATED COMBINATIONS IN THE EXISTING LINUX SERVER ONLY

**This is the most recent instruction and overrides earlier/current-assignment headings where they conflict.** Extend the already integrated Camera Look + Film Stock + Optical Effects recipe workflow and its existing Web Darkroom. Implement **all 21 curated editable combo presets** in `contracts/curated-combos-v07.yaml`, keeping the v0.6 effects and all previous composite IDs intact. No new renderer, no second Optical Effects page, no CHDK/camera tasks. Add real preview, full develop, PhotoPrism publish, provenance labels and wave gates **1 → 2 → 3 → 5 → 10**. The pairings are curated editorial adaptations of documented community favorites, **not verified exact combinations**. Never claim new presets work until actual render tests. Read `docs/35-curated-combination-presets.md`, `docs/36-combo-evidence-and-provenance.md` and `docs/37-combo-waves-and-acceptance.md` first.

---

# CURRENT ASSIGNMENT (v0.6): SERVER OPTICAL EFFECTS ONLY

**This paragraph overrides the older generalized project/CHDK mission below for the current development assignment.** Do not modify camera firmware, CHDK, on-camera UI, or device services in Waves 1/2/3/5/10. The existing CHDK docs remain in this full archive solely as historical project context. Implement all new effects **inside the established Linux M-Film Optical Effects engine and current Web Darkroom Step 4**, while preserving the six old effects and all Film Stocks/Camera Looks. Read [`docs/21-optical-effects.md`](docs/21-optical-effects.md) and [`docs/optical-engine/waves.md`](docs/optical-engine/waves.md) first. Ship code/tests/full-resolution server renders and PhotoPrism integration, not a new standalone effects feature.

---

# Implementation Agent Contract

Read `README.md`, `docs/00-scope-and-success.md`, `docs/02-system-architecture.md`, `docs/05-shared-film-engine.md`, **`docs/18-creative-look-requirements.md`, `docs/20-creative-pipeline.md`, `docs/25-creative-implementation-roadmap.md`**, then the document relevant to the task. This repository initially contains **specification only**; do not report it as implemented.

## Mission

Build an open, reproducible, **server-first film camera** for the Canon SX510 HS using CHDK and upstream M-Film film algorithms. Implement a Linux receiver and developer first; port the same core to CHDK as an offline fallback. Never replace M-Film film models with guessed filters to make a milestone appear complete.

## Work rules

1. Inspect actual upstream source and record Git commit hashes before coding. Source paths in this spec are research leads, not a guarantee that the newest upstream layout is unchanged.
2. Start with runnable Linux artifacts and a RAW/DNG fixture, not with speculative camera firmware patches.
3. Build reusable **C reference modules** for film look, profile data, deterministically seeded grain, and test vectors. Use a thin Python/server wrapper if useful. Share exact source with device build; document any `#ifdef` differences.
4. Separate verified facts (`VERIFIED`), reasoned proposals (`PROPOSED`), and hardware-blocked items (`HARDWARE-TEST REQUIRED`). Do not claim success from compilation alone.
5. CHDK module API, RAW behavior, Wi-Fi calls, actual free RAM, UI interception, write paths and Canon gallery compatibility must be validated on the actual camera and exact Canon firmware revision.
6. Preserve source DNG, protect the stock Canon software, and use an expendable SD card for first hardware experiments. Never flash nonvolatile memory or write unverified addresses without explicit owner approval.
7. Every completed milestone must include source, reproducible build instructions, tests, logs, measured constraints, limitations, and the next actionable milestone. Use `templates/phase-report.md`.
8. No private camera RAW, firmware ROM, LUT without redistribution rights, credentials or personal images in Git. Check M-Film GPL-2.0 and third-party licensing before copying assets.
9. On-network synchronization is **camera-initiated** and resumable. LAN is sufficient. Device power-off means no activity until next startup. Use USB/PTP or SD ingest as fallback while Wi-Fi feasibility is investigated.
10. Do not ask for user decisions on routine implementation details. Ask only when physical actions, a sample SX510 HS DNG, firmware version, deployment credentials, or potentially risky camera operations are actually required.

## Suggested first execution batch

- Fork / pin M-Film and CHDK; inspect `PORTING.md`, `ml-dev/filmos`, the SX510 HS port and dependent libraries.
- Compile the original PC simulator (`make -C ml-dev/filmos/sim` if still supported).
- Define a shared film-core C ABI; generate stable profiles and fixtures. Document which film code can actually be reused and which parts must be adapted.
- Implement a Linux CLI: `mfilm-develop --input source.dng --profile ID --recipe recipe.json --output result.jpg`, with machine-readable errors. A DNG decoding dependency on Linux is acceptable, but the film look must come from the shared core.
- Implement Linux receiver DB, per-roll ingest and CLI-based import from local SD/USB path before networking is available.
- Write camera capability probe for actual firmware and CHDK build, run only after owner supplies access.

## Definition of done

A milestone is **DONE** only after actual evidence is supplied. The entire project is not DONE until the acceptance gates in `docs/13-testing-and-acceptance.md` are met. If Wi-Fi is impossible on this CHDK port, complete the supported USB/SD workflow and state the Wi-Fi limitation explicitly.

## v0.4 directive: implement creative features on Linux now

The user explicitly requests **execution**, not another research proposal. Audit the actual in-progress M-Film/Linux code, then implement **all eight Camera Looks** and **all six named Optical Effects**, including composite presets and server rerender integration, through the existing film engine. All eight profiles may initially be original *inspired* artistic approximations; document limitations and progressively calibrate, but **do not leave any required profile as an unimplemented stub**. See [25](docs/25-creative-implementation-roadmap.md). Do not block host work on CHDK. The camera must preserve recipes; local heavy effects are strictly experimental. Never steal commercial LUTs or claim physically exact CCD/Foveon reproduction.

## v0.5 mandatory web + PhotoPrism scope (read before implementation)

1. Implement the browser-based Web Darkroom according to [`docs/27-web-darkroom-product.md`](docs/27-web-darkroom-product.md) through [`docs/34-web-implementation-and-acceptance.md`](docs/34-web-implementation-and-acceptance.md). This is **REQUIRED ON LINUX**, not CHDK experimental work.
2. The exact user workflow is **Select Material → Camera Look → Film Stock → Optical Effects (optional) → Preview (small) → Develop full size → Publish to PhotoPrism**. Source materials include local RAW upload (`.NEF` Nikon D5100, `.DNG` Canon SX510 HS), existing M-Film roll RAW, and an **existing PhotoPrism folder or album**.
3. The PhotoPrism browser must enumerate live albums/folders from the configured server and let users select full or partial RAW-backed photo sets. Resolve source RAW on server via authorized PhotoPrism access and never require re-uploading files from PhotoPrism to browser.
4. Independently select destination PhotoPrism **folder** and/or editable **album** (existing/new/same as source). A logical album is not a filesystem folder; photo UID association occurs only after publishing and successful indexing. No input originals overwritten.
5. All previews are reduced-resolution real renders using the same M-Film/C Camera Look/film/optics engine; full-size output reprocesses original source. Display failures honestly and do not claim JPEG-only media has RAW.
6. Existing CHDK/camera functionality is unchanged by these web tasks. Never block Linux feature delivery on DIGIC 4 performance or unfinished Wi-Fi access.
7. Follow staged work plan W01–W07 in [`docs/34-web-implementation-and-acceptance.md`](docs/34-web-implementation-and-acceptance.md). Add host/PhotoPrism integration tests, API schema and deployment instructions. Only owner-supplied secrets may be used for real connections; no test-only dummy credentials in released configurations.

## v0.6 STRICT SERVER-ONLY INTEGRATION DIRECTIVE

The current request is **not** for a new optical extension product or a camera/CHDK implementation. Amend the existing Linux M-Film service, its existing `optical.stack` and Web Darkroom Step 4. Preserve six old effect IDs and old film/camera-look profiles. Implement **all seven new standalone effects + editable Vintage Glass composite with three real suboperators**, delivering by mandatory Wave **1, 2, 3, 5, 10**. Read [`docs/21-optical-effects.md`](docs/21-optical-effects.md), [`docs/optical-engine/algorithms.md`](docs/optical-engine/algorithms.md), [`docs/optical-engine/integration.md`](docs/optical-engine/integration.md), [`docs/optical-engine/web-api.md`](docs/optical-engine/web-api.md), [`docs/optical-engine/waves.md`](docs/optical-engine/waves.md) and [`docs/optical-engine/validation.md`](docs/optical-engine/validation.md) before coding. Implement real pixel operations, not catalog entries. No CHDK changes required. Never claim server engine done until Wave 10 passes.
