# 04 — Roll Model, Durable Storage and State Machines

## Identifiers

- `device_id`: stable, pseudonymous ID generated for the app; never publish Canon serial number by default.
- `roll_id`: UUIDv4 or equivalent random unique ID generated at film load.
- `frame_id`: UUID or `<roll_id>-0001` stable per successful shutter operation (retain counter even after failed write with explicit error).
- `asset_id`: SHA-256-based canonical content identity after bytes verified; include media kind.
- `render_id`: SHA-256 of canonical recipe + original hash + renderer version + output size/format (see renderer document).
- `profile_bundle_hash`: version hash of all binary profile assets and implementation metadata.

## Separate orthogonal state machines

**Roll:** `NEW -> LOADED -> CAPTURING -> SEALED -> READY_FOR_SYNC`, with independent flags `server_developed`, `offline_developed`, `gallery_ready`. One roll is SEALED only after its frame list is finalized, even if hashes are still pending (then marked `manifest_pending`). A new roll can be loaded while older ones await upload or development.

**Frame original:** `CAPTURE_PENDING -> WRITTEN -> VERIFIED -> QUEUED -> UPLOADING -> UPLOADED`, with recoverable `ERROR`/`RETRY` states; no `VERIFIED` without file sanity and hash.

**Server development:** `WAITING_FOR_INPUTS -> QUEUED -> RUNNING -> COMMITTED -> PUBLISHED` or `FAILED_RETRYABLE` / `FAILED_TERMINAL`.

**Camera offline development:** `NOT_REQUESTED -> QUEUED -> RUNNING -> COMPLETE` or `PAUSED` / `FAILED`.

**Result-return sync:** `NONE -> AVAILABLE_REMOTE -> DOWNLOADING -> VERIFIED_LOCAL -> GALLERY_READY`.

Never collapse these into a single ambiguous status like `SYNCED`: a roll can have all originals uploaded but development still running, or local developed pictures without server archive.

## Camera storage layout (logical)

```text
A/CHDK/MFILM/
  CONFIG/device.json
  FILMS/bundle.bin
  ROLLS/<roll_id>/manifest.json
  ROLLS/<roll_id>/journal.log
  ROLLS/<roll_id>/gallery-index.json
  CACHE/temporary*.part
  LOGS/app.log
  QUEUE/sync.json
A/DCIM/...                # Canon-created JPEG / CHDK DNG, preserve locations
```

Use actual CHDK path semantics and filesystem restrictions determined by the port. The manifest holds real `source_path` references; moving RAW out of `DCIM` is optional and gated by testing. No accidental overwrite of Canon DCF numbering. On FAT, consider journaling with sequence, checksums and atomic-ish rename using explicit recovery tests; do not assume desktop `fsync` semantics.

## Server storage layout

```text
/var/lib/mfilm/
  incoming/<upload_id>.part
  originals/<device_id>/<roll_id>/<frame_id>.dng
  offline-renders/<device_id>/<roll_id>/...
  renders/<device_id>/<roll_id>/<render_id>.jpg
  manifests/<device_id>/<roll_id>.json
  db/mfilm.sqlite3
  logs/
```

Server maintains separate **archive** vs **PhotoPrism-visible exports**. PhotoPrism input directory receives only fully committed finals. Prefer an external backup of immutable RAW archives.

## Atomicity rules

1. Write manifest update to staged file + flush where supported + rename; include monotonic generation/sequence and CRC or hash.
2. Never advance frame `VERIFIED` without checking existence, size and content hash.
3. Server receives to staging; hash, validate DNG structure, then atomically moves into canonical archive and commits SQLite transaction.
4. Receipt is generated **after** commit; repeat request returns the same receipt.
5. Render to temporary path; decode JPEG for validation; compare expected dimensions, then atomically promote and update DB.
6. Do not delete local originals automatically, even after server ACK. Any future retention feature must be opt-in, separately designed and tested.

## Example format

See [`contracts/roll-manifest.example.json`](../contracts/roll-manifest.example.json). Contract examples show logical paths only; implement a versioned schema and validate on both server and host tools.
