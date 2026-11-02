# 08 — Linux Service: Primary Developer

## Operational role

An always-on **self-hosted Linux service** owns primary RAW archiving, full-resolution film development, status reporting and PhotoPrism publishing. The camera does not need public Internet access: LAN connectivity is enough. Support local SD import and USB/PTP before Wi-Fi client integration is finished.

## Proposed implementation stack

- **Receiver/API:** Python 3 + FastAPI (proposal), or equivalent low-resource HTTP service.
- **Database:** SQLite in WAL mode, single deployment; migrations versioned. If multi-user concurrency later requires PostgreSQL, keep repository interface decoupled.
- **Worker:** separate process/queue invoking a **native C development CLI/shared library**. Python may manage jobs but may **not** independently reimplement film colors/grain.
- **Store:** per-device/per-roll immutable DNG archive and render outputs; staging and publication dirs on same filesystem when relying on atomic renames.
- **Linux service manager:** systemd units for `mfilm-receiver` and `mfilm-worker`; optional Docker Compose only if no requirement for physical USB passthrough.
- **Observability:** structured logs, health endpoint, progress reporting, failure reason and job retry counters.

## Service workflow

1. Pair/register device; issue scoped credential (security details in doc 12).
2. Accept `roll_manifest` and `render_recipe`, enforce schema and size/rate limits.
3. For each original DNG, allocate resumable upload session; append validated chunks; hash on complete; inspect DNG metadata and commit immutable source path/DB row.
4. Mark roll `INPUTS_COMPLETE` when sealed manifest and every required original are available and verified.
5. Enqueue render jobs **automatically** (no manual UI needed). Use stored exact film core/profile bundle version.
6. Process frames with limited parallelism to keep Linux CPU/memory/disk healthy; report per-frame progress and job logs.
7. Commit full-size JPEG after validation; store EXIF and rendition provenance.
8. Export committed JPEGs to PhotoPrism with idempotent publication, queue indexing.
9. Expose result metadata/download to camera and administrative CLI.

## Data model (minimum)

`devices(id, key_id, status, last_seen_at)`; `rolls(id, device_id, sealed_at, expected_frames, manifest_hash, state)`; `frames(id, roll_id, ordinal, capture_time, original_asset_id)`; `assets(id, sha256, bytes, mime, path, created_at)`; `uploads(id, device_id, declared_sha256, offset, state, updated_at)`; `recipes(id, json, core_revision, bundle_hash)`; `renders(id, frame_id, recipe_id, output_spec, asset_id, origin, state)`; `jobs(id, render_id, attempt, state, error_code, timestamps)`; `publications(id, render_id, destination, status)`.

Use unique constraints on `device+roll`, `roll+frame ordinal`, `asset sha256`, `render_id`, and publication destination. Introduce proper transactional state transitions. Never treat successful HTTP response before disk commit as an ACK.

## Admin CLI (first-class)

```text
mfilmctl import-card /media/camera
mfilmctl list-rolls --state pending
mfilmctl develop <roll_id>
mfilmctl verify <roll_id>
mfilmctl publish <roll_id>
mfilmctl device-pair --name sx510hs
mfilmctl reprocess <roll_id> --profile <id> --new-rendition
```

These are **proposed commands**, not existing binaries. Build CLI before relying on Wi-Fi. Include dry-run for import, health checks, and `--json` output for automation.

## Deployment conventions

Use separate service user, directory permissions, backup rotation, resource caps, no public port by default, path validation and data disk space alarms. Provide `config.example.toml`, `.service` units, migrations, health checks, and a one-command local test with fixtures. Document how to point publisher to PhotoPrism originals/import path and what user/group owns it.

## Handling offline renders

Camera-local developed JPEGs are uploaded as a different `origin=camera` rendition with its original file hash, exact recipe and output size. Do not treat them as proof that Linux canonical full-resolution development occurred. By default Linux still develops from archived DNG and publishes a canonical `origin=linux` result; offline image may be retained as alternate, optionally unpublished to avoid gallery duplicates.
