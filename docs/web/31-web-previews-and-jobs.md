# 31 — Preview Pipeline, Background Jobs and Provenance

## Preview processing is real processing

Preview must use the **same C M-Film shared film algorithms, Camera Looks, optical effects and same normalized source** as the final renderer. A fast separate lower-quality demosaic may be allowed only if visual differences are documented and measured; exact image parity is not a required equality when downsampling, but effects, color and seed behavior should be close.

- Default preview long edge <= 1280 px, configurable server caps. Generate from full RAW source, downsample appropriately before creative stages if look definitions permit, with correct scale normalization of blur radii / optical artifacts.
- Cache key: `source_sha256 + canonical_recipe_hash + core_version + profile_bundle_hash + preview_width + colorspace + crop`. Do not use display file name as identity.
- Browser requests preview with idempotent job creation and polls or uses SSE to receive results. Cancel/reject stale requests when recipe changes; UI must not show a stale preview as current.
- User-controlled seed is stable for reproducible grain; if grain pattern is resolution-dependent, specify spatial mapping to avoid changing coarse look between preview and full-size output.
- Optional before/after compare uses a neutral render from the same RAW and same baseline white balance/color management; do not compare with an unrelated PhotoPrism thumbnail that may have a different camera JPEG tone curve.

## Final development

- Create immutable render job with selected asset snapshot and validated recipe v2. `Develop` never changes existing RAWs or prior outputs. Final render source is original RAW, not cached preview.
- Queue: `QUEUED -> DECODING -> RENDERING -> VALIDATING -> STAGED -> PUBLISHING -> INDEXING -> ALBUM_LINKING -> COMPLETE`; support `FAILED`, `CANCELLED`, `RETRYABLE` and partial batch states. Rendering and publication are separate retryable operations.
- Fast UI API acknowledgement (202) and background worker jobs; do not hold one HTTP request open while processing 36 full-size NEF files. Use RQ/Celery/Arq or an equivalent persistent worker engine with SQLite or PostgreSQL for durable jobs. Worker concurrency defaults conservative and is configurable, avoiding OOM.
- Store per-image step, progress when measurable, logs with sensitive paths filtered, timestamps and failure codes. SSE preferable, polling fallback. Stop/cancel must not leave partially published JPEG.
- Dedup identity includes original digest, actual decoded input processing settings, complete recipe, core+profile bundle versions, final dimensions, encoded color format and seed; `publish_destination` is not part of render identity.
- A user may rerender to different album/folder without recomputing identical bytes; publication is idempotent per output/target combination.

## Result verification

- Validate output JPEG with independent decoder, dimensions and ICC, ensure metadata preservation (capture date, ISO, shutter, aperture, actual original camera model) and add human-readable creative recipe metadata only if safe. Never replace real EXIF camera manufacturer/model with emulated Camera Look; store look in separate metadata field.
- Attach authoritative provenance JSON with original SHA-256, PhotoPrism source IDs, complete recipe v2, core/profile revisions, seed, rendering timings, export format and output SHA-256.
- Provide secure thumbnail/download endpoints for finished results, and link to confirmed PhotoPrism library entry when indexing/album association completed.
