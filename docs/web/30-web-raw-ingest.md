# 30 — RAW Upload and Input Normalization

## Required formats

- `.DNG`: specifically CHDK-generated Canon SX510 HS DNG; also standard DNG from supported cameras.
- `.NEF`: Nikon RAW, especially Nikon D5100 sample fixtures. Nikon variants may use differing compression; **verify** each sample with the deployed LibRaw decoder, do not rely on extension alone.
- Optional after testing: Canon `.CR2`/`.CR3`, Sony `.ARW`, Fujifilm `.RAF`, Pentax `.PEF`, TIFF/JPEG opt-in. JPEG input, if added, must be clearly labeled **non-RAW** with reduced flexibility.

## Input sources and isolation

- Browser upload: initialize upload session, stream chunks to private staging, validate declared size/limit and actual format signature, calculate SHA-256, deduplicate and commit to immutable content-addressed original archive. Never process uploaded image in web process memory directly; delegate to worker and sandbox decoder.
- PhotoPrism source: backend enumerates authorized files, resolves the RAW-bearing PhotoPrism record, then accesses the specific original through protected read-only mount, WebDAV or tokenized download. No large RAW should travel from PhotoPrism to browser and back.
- Existing roll: use original DNG and associated immutable recipe metadata, allow user to override creative settings for new rendition without modifying roll history.

## Processing

1. Validate source file by magic/decoder, not only extension; reject malformed/truncated media safely.
2. Extract basic EXIF metadata and preserve originals unchanged; map orientation and camera color calibration from the original capture, not the emulated Camera Look.
3. Use LibRaw-compatible normalizer (LibRaw / rawspeed / tested equivalent) to map each source into versioned scene-linear intermediate; avoid double application of white balance or camera curves.
4. Provide image-level error and unsupported-format reason. Keep other batch items running. Include fail-safe memory, CPU and pixel limits and timeouts.
5. Persist origin provenance: `upload | photoprism | camera_roll`, source SHA-256, PhotoPrism photo/file UIDs or roll/frame ID, input filename, camera EXIF, content size and decoded geometry.

## Retention

- Originals are retained in a private content-addressed archive according to configured policy; no auto deletion of camera DNG or PhotoPrism source media.
- Staged abandoned uploads have bounded TTL and cleanup jobs; canonical originals and completed results are separately retained.
- An optional `Keep uploaded originals` policy is explicit; for PhotoPrism-sourced inputs do not duplicate indefinitely unless needed for deterministic jobs or availability after source deletion.

## Version-sensitive tests

- Genuine NEF from D5100, genuine CHDK SX510 DNG, a damaged NEF, mismatched extension, unsupported compressed variant, orientation metadata and batch of many large files.
- Compute and retain fixtures' SHA-256; do not commit private photo content to public repository.
