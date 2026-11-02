# Implementation Agent Contract

Read `README.md`, `docs/00-scope-and-success.md`, `docs/02-system-architecture.md`, `docs/05-shared-film-engine.md`, `docs/14-implementation-roadmap.md`, then the document relevant to the task. This repository initially contains **specification only**; do not report it as implemented.

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
