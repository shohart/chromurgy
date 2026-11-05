# 27 — Web Darkroom: Product Specification

**Status: implementation required on Linux, not an optional research item.** This adds a web application to the existing M-Film server-first architecture. It does not replace roll ingestion, the same C film engine, or offline CHDK development. See [28 UI](28-web-darkroom-ui.md), [29 PhotoPrism](29-photoprism-source-and-destination.md), [30 RAW](30-web-raw-ingest.md), [31 Jobs](31-web-previews-and-jobs.md), [32 Publishing](32-web-publication.md), [33 Security](33-web-security-deployment.md), [34 Delivery](34-web-implementation-and-acceptance.md).

## Scope and defining user journey

The core web interaction is **(1) Source Material → (2) Camera Look → (3) Film Stock → (4) Optional Optical Effects → Preview → Develop → Publish**. Source material means original input images; it is *not* an additional color preset. Sources:

- Upload one or multiple local RAW files via browser, with at least `.DNG` and Nikon `.NEF` supported. Accept CR2/CR3/RAF/ARW only after decoder/corpus verification. Allow multiple selections, drag/drop and upload progress.
- Browse an authenticated, already-connected **PhotoPrism** library: choose **an originals folder** or **an album**, then select all or a subset of its images with supported RAW originals. The user need not manually download/re-upload PhotoPrism files to develop them.
- Choose an existing M-Film camera roll, its archived originals, or already-imported assets from the local server inventory. All three inputs use the same rendering pipeline.

The web application shall also provide independently chosen **PhotoPrism output folder and/or output album**. A source selection NEVER implies that original files can be overwritten. Default output is a managed `MFilm/Developed/...` folder and, if the source is an editable manual album, optionally its current album. Destination folder and album may both be set.

## Core functional requirements

1. Material browser shows file count, RAW support, model and exposure metadata where present, filesize, thumbnails (when available), and count of ineligible items. Provide concise error reasons and skip unsupported files without losing the batch.
2. Load all eight camera looks from the v0.4 catalog: Leica M8, Leica M9, Fuji S5 Pro, Nikon D200, Pentax 645D, Ricoh GR III Positive Film, Sigma DP2 Merrill, Fuji X-Pro3 Classic Negative; include Neutral.
3. Load all original usable M-Film film profiles (catalog target: 72). Film selection is independent of Camera Look and may be None if engine supports a neutral film stage.
4. Support independently configurable optical effects: Soft Sun Glow, Ricoh HDF, Black Pro-Mist, Vintage Veiling Flare, Film Halation, Orton Glow, Golden Haze as an optional composite preset. Render recipe conforms to v2 contract and all selected options are genuinely processed, not metadata-only.
5. On any relevant edit, provide an **on-demand, debounced, reduced-resolution preview** through the same processing pipeline, with optional before/after wipe and zoomed crop. Do not pretend PhotoPrism thumbnails are final previews.
6. **Develop** schedules high-quality jobs from immutable original RAW sources. Final output is independently rendered in full requested resolution, never upscaled from preview. Support per-image and entire-batch execution.
7. After valid completion, optionally publish outputs to a selected PhotoPrism folder, album, or both, retaining source originals and all prior developed versions.
8. Display persistent render jobs with progress, cancellation, retry, failed/skipped reasons, per-image status, provenance and links to finished results in PhotoPrism.
9. Allow re-development of existing photos with a different recipe, storing a new rendition and leaving previous edits intact. Duplicate requests with identical sources+recipe+versions do not create redundant files.
10. Desktop and mobile-responsive browser UI, keyboard-accessible, no camera Wi-Fi required for upload or PhotoPrism-sourced work.

## Film-roll semantics

- M-Film camera rolls remain available as a batch source. A manually uploaded NEF collection is a web development batch, **not** a fake CHDK camera roll. Optionally group uploads into a named web roll, with independent metadata.
- A PhotoPrism album is a virtual selection, not a disk folder; snapshots of its selected photo UIDs and source file identifiers must be persisted at job acceptance, so edits to the album mid-job cannot silently change the batch.
- RAWs imported from Nikon and other cameras use camera-specific LibRaw calibration and then the same shared M-Film creative processing; emulated camera look is not inferred from EXIF manufacturer.

## Hard non-goals

- No direct editing, deletion, moving or overwriting source files in PhotoPrism.
- No copying third-party proprietary LUTs without a license; evidence-tier labels for camera emulation remain mandatory.
- No pretending JPEG-only PhotoPrism entries have RAW data. If RAW is absent, show 'RAW unavailable'; JPEG creative reprocessing is an explicitly separate, opt-in pipeline and not part of RAW-MVP acceptance.
- Do not expose PhotoPrism credentials in browser code or provide unconstrained URL fetch/SSRF.
