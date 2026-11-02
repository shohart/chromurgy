# 14 — Implementation Roadmap and Agent Work Packages

## Dependency strategy

**Critical path:** source audit -> common film core -> Linux RAW/DNG developer -> ingest/store/job queue -> PhotoPrism publication -> camera CHDK probe -> roll capture -> device-sync fallback -> offline developer -> optional native Wi-Fi.

Do not start with Wi-Fi reverse-engineering. Avoid tying success of rendering/archival to hardware network feasibility. Agent should implement concrete tasks in order, not produce endless plans.

### P00 — Upstream inventory and reproducibility

- Pin M-Film and CHDK revisions; inspect `PORTING.md`, `ml-dev/filmos/`, `ml-dev/films/`, `fos_dev.c`, `fos_jpeg.c`, `fos.h`, simulator and licensing.
- Build simulator (`make -C ml-dev/filmos/sim` if current). Record actual command, dependencies and binary output.
- Generate a component-by-component reuse table: portable, requires refactoring, unusable, third-party data with rights concerns.

**Deliver:** source audit, `LOCKFILE` with commit hashes, reproducible host build, G0 evidence.

### P01 — Shared C renderer

- Extract or adapt authentic M-Film film algorithms and generator-backed profile data into portable C independent of Magic Lantern and CHDK.
- Define structured recipe, deterministic RNG and versioned profile bundle. Build a host CLI and testable C ABI; compile device-side stub with toolchain if viable.
- Golden vector tests for 3 representative films (color negative, reversal, monochrome), then all permitted profiles.

**Deliver:** shared source, tests, profile metadata and parity harness.

### P02 — Linux RAW pipeline

- Implement validated SX510 HS DNG reader via robust host parser, color/geometry adapter and JPEG writer using shared film core.
- Request real DNG from owner only when required; use legal public test fixture initially, label model-specific untested.
- Produce genuine 4000×3000 JPEG (assuming valid native active source) and sidecar provenance.

**Deliver:** working `mfilm-develop` host CLI, baseline quantitative metrics and output samples.

### P03 — Linux service / SD ingestion / PhotoPrism

- Implement receiver persistence, SQLite migrations, content-hash-based archive, worker processes and retries.
- Implement `mfilmctl import-card` and render on sealed roll, stage and publish to a test PhotoPrism instance using configured originals/index or WebDAV.
- Build API protocol in parallel with fake camera simulator: manifest and resumable upload, status and result download.

**Deliver:** G1 end-to-end **server-first** system with a sample SD directory, reproducible install and systemd unit.

### P04 — CHDK port and roll capture

- Determine camera Canon firmware and select exact CHDK build; create hardware probe.
- Implement stable roll UI, 12/24/36 frame counts, profile selection, manifests/journals and actual DNG file linkage. Verify no Canon JPEG corruption.
- Research/implement blocking preview with safe approach. Report limitation if stock Playback cannot be reliably controlled.

**Deliver:** G2 on-camera capture with verified original images.

### P05 — Offline developer / local gallery

- Port same film C core and supported profiles to CHDK; create constrained DNG reader or raw adapter, tile memory management, JPEG output and resumable development.
- Create developed-only gallery, test Canon stock gallery only if useful and validated. Present explicit offline resolution limit.

**Deliver:** G3 local 1-roll proof, profiles, logs, resource benchmarks.

### P06 — Host-assisted device sync

- Implement CHDKPTP USB transfer if hardware allows; otherwise reliable SD ingest/return receipts. Support server result download/copyback.
- Reconcile remote/offline versions, test wrong hash and repeated uploads.

**Deliver:** G4 end-to-end round trip.

### P07 — Wi-Fi native transport (parallel research after G2)

- Study DryOS symbols and historical SX510 HS research; confirm network bring-up, memory resources, IP/HTTP capabilities and test a small packet.
- If feasible, implement transfer and download, pairing, network config and power controls.
- If infeasible without high-risk firmware modification, document evidence and retain USB/SD as supported transports.

**Deliver:** G5 evidence or explicit technical blocker report.

### P08 — Quality / release

- Optimize 5 MP/8 MP local development subject to memory and timing; full-size 12 MP host canonical remains mandatory.
- Run validation matrix; package CHDK card files with version gates, Linux server service templates, migration/backup instructions and rollback guide.

**Deliver:** public-ready release with limitations, SPDX/license notices, user manual and tested install paths.

## Parallelism

After P00/P01 interface stabilization: server ingestion team can work on P03 with dummy asset bytes, while RAW developer works on P02. Camera work can begin P04 as soon as user has hardware, but must not claim later stages done. Transport work P07 should not block P03/P05.

## Each phase report must state

What built and runs; exact sources and commits; measured result; `PASS/FAIL/BLOCKED/NOT TESTED`; outstanding risks; concrete next execution steps. See [`phase-report.md`](../templates/phase-report.md).
