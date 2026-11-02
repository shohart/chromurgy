# M-Film CHDK Edition — Server-First Film Lab

**English engineering specification · Revision 0.3 · 2026-11-02 · Status: design, not implemented**

Target device: **Canon PowerShot SX510 HS** (Canon DryOS / CHDK). Primary developer: **self-hosted Linux service**. Offline developer: **same film-processing core, ported to the camera**. Library destination: **PhotoPrism**.

## Non-negotiable product model

1. Load a virtual 12-, 24-, or 36-frame film roll, choose its film profile, and shoot RAW/DNG without seeing unprocessed images.
2. Camera processing **does not run in the capture path**. When a roll is finished, upload the **original RAW/DNG** to a reachable Linux receiver. The receiver develops it at the best available resolution, stores the originals, and publishes finished JPEGs to PhotoPrism.
3. **Internet is not required:** a local LAN connection to the Linux server is sufficient. The SX510 HS has built-in 2.4 GHz Wi-Fi, but arbitrary CHDK TCP/IP support on this particular port remains **unproven**. USB/PTP and SD ingest are required fallbacks.
4. When the server is unavailable, the user may invoke **Develop on Camera** for the completed roll, using the **same film algorithms and profile definitions** as the server. Do not quietly switch to unrelated Canon effects or generic LUTs.
5. Server-developed images may later be synced **back** to the camera to populate its developed gallery. Offline-developed images are usable immediately; on reconnect, the server should still archive RAW and may create an additional full-resolution rendition without overwriting the offline result.
6. Canon's built-in JPEG generation and playback require investigation. The no-preview policy must be **implemented and hardware-verified**, not assumed; the original DNG must never be destroyed in the attempt.

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
| [contracts/](contracts/) | API and example manifests |
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
