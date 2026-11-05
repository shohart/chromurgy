# 34 — Implementation Plan and Acceptance for Web Darkroom

**Priority: REQUIRED. Implement now on Linux. CHDK changes are not required for this feature.** Do not delay web work while Wi-Fi research or camera hardware tests are pending. Preserve all v0.4 camera look and optical scope.

## W01 — Connector capability probe and CLI

- Pin deployed PhotoPrism API version; inspect actual auth, albums, folder listing, photos, file-level RAW, uploads/WebDAV and album association. Provide `mfilmctl photoprism doctor` with separate tests for source-read and destination-publish.
- Obtain source photos from a test album and originals folder; detect `.NEF`/`.DNG` companion. Validate album vs folder semantics.
- **Done:** discovery and RAW read succeed on actual configured instance, or clear capability error is reported. No hidden mock success.

## W02 — Web RAW upload and source catalog

- Add streaming multi-file upload, content-sniffing, LibRaw decode support, immutable storage, source IDs and PhotoPrism asset selection snapshot.
- **Done:** genuine D5100 `.NEF` and SX510 HS `.DNG` fixtures enter canonical pipeline; unsupported/missing RAWs report reasons; browser does not receive originals from PhotoPrism.

## W03 — Camera/film/effect selection

- Implement guided UI with independent controls for Camera Look, M-Film Film Stock, optical effects (plus optional preset) and recipe v2. Link engine-supported options, not hardcoded dummy controls.
- **Done:** user can select all eight mandated looks, full available film catalog and actual effects. Controls persist across preview and render.

## W04 — Preview engine

- Implement reduced-resolution preview from original RAW using production pipeline and correct versioned cache, before/after comparison, cancellation and error states.
- **Done:** changing camera look, film and Sun Glow produces visibly changed low-res image from both uploaded NEF and PhotoPrism-sourced RAW; stale previews never show as current.

## W05 — Full-res render worker and history

- Render full-size JPEG from original RAW, durable queue and provenance; expose job status, failure reasons, retry, downloads, history and non-destructive rerender.
- **Done:** a 12–36-frame batch can run in background with per-item progress, process restart recovery and no RAM spike proportional to entire batch.

## W06 — PhotoPrism source picker and publishing

- Paginated album/folder browser, photo selection, new/existing album chooser and independent destination folder picker. Publish verified outputs, await index, then associate new photo UIDs to selected album. Reconcile partial failures.
- **Done:** select source album A (with actual RAW), develop into destination folder C and album B, observe new full-resolution photos in B; original A files remain unchanged. Same-album output also works without overwriting originals.

## W07 — Security, QA and release

- Auth, credentials separation, path protection, limits, integration tests and deploy docs. Regression test camera roll workflows and offline/USB sync.
- **Done:** deployable Linux web application with documented PhotoPrism connection setup, test fixtures, migration steps, CLI and screenshots/test recordings from running instance.

## Acceptance matrix (mandatory)

| Case | Expected outcome |
|---|---|
| Upload one Nikon D5100 NEF | Preview and full-size JPEG created with selected Camera Look + Film Stock |
| Upload several CHDK DNGs | Batch preview, develop, retry per item; originals preserved |
| Browse PhotoPrism album | List its photos, detect RAW-backed items, select subset with pagination |
| Browse PhotoPrism folder | List originals paths and eligible RAW assets within selected folder scope |
| JPEG-only PhotoPrism photo | Not silently substituted as RAW; explain ineligible state |
| Select Camera Look + Film | Both applied by same shared C engine, not just labels |
| Sun Glow/HDF/halation effect | Visible meaningful preview and final effects with documented control behavior |
| Change recipe quickly | Stale preview cancelled; current preview matches recipe ID |
| Full-size development | Original RAW decoded independently of preview; no upscaling |
| Output folder selected | New uniquely named JPEG indexed there without changing source |
| Output existing album selected | Indexed new image UID associated correctly to album |
| Output new album selected | New manual album created and populated with new image UID(s) |
| PhotoPrism unavailable mid-publish | Render remains safe; publication retries, UI status accurate |
| PhotoPrism permission denied | Source/destination appropriately disabled; no private data leaked |
| Repeat same exact render | No duplicate output, idempotent re-publish |
| Rerender with new profile | New separate JPEG created, prior output and original retained |
| Server restart mid-batch | Jobs resume/reconcile without phantom success or file loss |

## Test harness

- Fast test suite using fake PhotoPrism API and synthetic DNG/NEF metadata fixtures; full integration suite with disposable PhotoPrism + sample files (do not rely solely on mocks for API assumptions); visual fixture suite for preview/final relative behavior.
- Add tests for folder permission, album access, missing RAW, merged RAW/JPEG stack, stale album membership, download-token renewal, ignored indexing, Unicode names, path traversal, repeated index and transient WebDAV failure.
- Tests run in CI and on target deployment. Where real instance isn't available, report `BLOCKED: integration not verified` explicitly.

## Agent execution priority

After initial upstream and engine audit, begin **W02 + W03 + W04** immediately using local upload and sample files, then do PhotoPrism integration. Do not require the owner to supply API credentials until actual deployment. Work independently on schema/UI/mock tests with no secrets in source.
