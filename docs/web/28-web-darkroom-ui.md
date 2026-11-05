# 28 — Web UI and Interaction Design

## Main pages

- `/darkroom` — guided workspace, five-step progress and current jobs drawer.
- `/darkroom/jobs` — active/recent queue, completed galleries and retries.
- `/darkroom/history` — prior renders by source, recipe, date, destination and outcome.
- `/settings/photoprism` — connector status and permitted root/output destinations (administrator configuration; tokens never returned to browser).

## Workspace layout

**Step 1 — Material (required).** Tabs `Upload RAW`, `PhotoPrism`, `M-Film Rolls`.

- Upload: drag/drop or native file picker; `.nef`, `.dng` recognized, other types displayed only when supported by the deployed decoder. Display count, size, filename, duplicate/invalid warnings and progress. Multi-file upload. Backend stages files before processing; browser must not decode multi-hundred-MB originals.
- PhotoPrism: folder/album tabs, searchable and paginated selection. Display folder breadcrumb or album title, cover, item count, photo thumbnails and `RAW available` badges. Separate `Select all eligible` and `Select visible` actions; support exclude checkbox for individual frames and server-resolved selections beyond the visible page. Show number selected and RAW candidates; preserve selection across pages.
- M-Film Rolls: list of uploaded rolls/archived assets with status and number of source RAWs.
- Optional filter: camera make/model, capture date, raw-only. Importing from PhotoPrism is a backend-to-backend fetch or read-only mount; never download raws to browser and re-upload.

**Step 2 — Camera Look (required).** Neutral + eight catalog profiles. Cards contain short factual/aspirational description, visual reference (licensed assets only), evidence tier, intensity 0–100%. Camera Look is independent of actual camera manufacturer and the original file stays unchanged.

**Step 3 — Film Stock (required).** Searchable M-Film film stock list with profile family, grain and contrast info. Preview card controls are not substitutes for actual render. Control selection persists in a canonical recipe v2. Film strength/grain only if exposed by shared core.

**Step 4 — Optical Effects (optional).** Independent enable/order and intensity controls for Bloom/Sun Glow, HDF, Black Pro-Mist, Veiling Flare, halation, Orton, plus bundled Golden Haze. Warn about duplicate halation application; enforce core's legal effect order, not arbitrary UI filter ordering.

**Step 5 — Preview, Develop, Publish.**

- Select representative frame or manually pick any frame; fast preview at max 1280 px long edge by default, optionally 720 px. Interactive original-vs-treated slider and 1:1 crop at requested preview scale.
- `Refresh Preview` explicit action; auto-refresh after debounce, cancel/stale preview requests upon recipe change, never block the browser. Show recipe hash, preview resolution and that it is not export-quality.
- Specify final format JPEG, quality, output dimensions (`Original` default) and optional variants. Display source/target counts, expected output count and rough compute/storage estimate when actually measured, not invented.
- Destination controls: `Save on server`, `PhotoPrism folder`, `PhotoPrism album` (existing or new). Choose either or both; `Do not publish` remains allowed. Separate source location from destination location. Display chosen PhotoPrism instance and privilege checks.
- `Develop selected` enqueues asynchronously. Success shows finished images, a link into PhotoPrism when indexed/attached, download of individual JPEGs or batch ZIP, and option to regenerate with revised recipe.

## Interaction states

- PhotoPrism not configured/permission denied/offline; source folder or album empty; no RAW among selected; unsupported NEF encoding; partial input batch; preview pending / stale / failed; queue waiting / decoding / film rendering / publishing / indexed / album-associated; disk full, insufficient access.
- Disable job submit when zero eligible originals or recipe invalid. **Never silently substitute a camera original JPEG for an NEF**.
- Preserve user's recipe and source selection after refresh (server-durable job draft or local state as appropriate); do not cache credentials or original RAW bytes in browser persistent storage.
- All status changes must be grounded in backend job state. Preview thumbnails must have controlled caching by source hash + recipe hash + engine version + size, not stale visual placeholders.

## UX acceptance examples

1. Select PhotoPrism album `Autumn Trip`, select three NEF-backed photos, Leica M9 camera look, Portra 400, Sun Glow, preview one, develop all, publish to new album `Autumn Trip — M-Film`; resulting gallery includes three new non-destructively edited photos.
2. Select originals folder `2024/Family`, filter RAW-backed images, choose Neutral + Fuji Classic Negative, compare before/after, publish to dedicated MFilm output folder without modifying the source folder.
3. Drag/drop ten `.NEF` Nikon D5100 files, preview, choose Ricoh Positive Film + HDF, develop and publish to PhotoPrism folder and an existing manual album.
