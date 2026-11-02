# 11 — PhotoPrism Publishing and Library Policy

## Objective

PhotoPrism receives **developed, validated** JPEGs only. Linux receiver retains original DNG in an archive path outside PhotoPrism's `originals` by default. This prevents undisplayed RAW imports and allows different film renditions without replacing original sensor data.

## Preferred integration: direct originals tree

1. Receiver stores canonical JPEG under private `renders/` after completion.
2. Publisher creates intended path under PhotoPrism-mapped originals only after JPG validation/hash check (copy into temporary adjacent file, fsync if supported, atomic rename on same filesystem).
3. Use an index job or configured scheduled index to make new files visible. If originals are mounted read-only to PhotoPrism, ensure service directory permissions are correct; do not assume PhotoPrism can import in that configuration.
4. Use unique path with camera, year, roll and `render_id` or stable filename, never replace an earlier version.

Example:

```text
photoprism/originals/MFilm/SX510HS/2026/ROLL_<shortid>/
  F0001_PORTRA400_<render-shortid>.jpg
  F0002_PORTRA400_<render-shortid>.jpg
```

## Alternative: authenticated WebDAV

PhotoPrism supports WebDAV uploads to `originals/` or `import/`; default automatic indexing may run after a safety delay and depends on server configuration. Do **not** rely on incomplete partial files being scanned. Upload only complete JPEGs and finalize before exposing them. Authenticate with an app password or appropriate configured credential; use HTTPS outside a private LAN.

## Choosing PhotoPrism behavior

- **Originals/index mode** keeps stable filenames and directory layout. Recommended for reproducible renditions.
- **Import mode** can rename and deduplicate; preserve cross-reference identifiers and use import receipts if chosen.
- Only one canonical server rendition per frame should publish automatically by default. Camera-offline renditions can remain archived alternatives; optional extra profile renditions should publish only on request to avoid a duplicate-heavy PhotoPrism gallery.
- Keep original shooting EXIF and add software/film source metadata where the output encoder supports it. Verify `DateTimeOriginal`, ISO, exposure time, aperture, focal length and orientation.
- Contact sheets are optional separate artifacts and should not appear as ordinary camera images by default.

## Trigger / verification

- First select known native PhotoPrism indexing behavior, e.g. auto-index after WebDAV upload or configured scheduled rescan; avoid overlapping index runs.
- For direct filesystem publication, use documented PhotoPrism CLI/management feature compatible with deployed version; do not invent unsupported HTTP endpoints.
- Mark `PUBLISHED` only when file is committed to the correct watched location. Mark `INDEXED` separately after observed confirmation from PhotoPrism if the integration can query it; indexing failures must not roll back RAW archive or render.
- Test server restarts, duplicate publication, PhotoPrism offline, read-only mode, gallery rescan and metadata consistency.

## Archival extension

Offer separate opt-in backup of DNG (NAS/Nextcloud/S3-compatible) outside PhotoPrism; do not delete camera DNG automatically. Integration must not bake in a specific NAS hostname or user secrets.

## Documentation reference

PhotoPrism WebDAV and indexing: https://docs.photoprism.app/user-guide/library/webdav/ and https://docs.photoprism.app/user-guide/library/originals/
