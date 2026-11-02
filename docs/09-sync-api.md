# 09 — Sync Protocol (Proposed Contract v1)

## Design goals

Transport-agnostic, resumable, versioned, idempotent and safe on FAT SD and intermittent links. Primary payload is **original DNG** (not already-developed JPEG). Secondary payloads: camera offline JPEG, manifests, logs (opt-in), and server-to-camera rendered JPEG/thumbnail.

The schema and routes below are **proposals**, not CHDK-supported functions. See [`contracts/openapi.yaml`](../contracts/openapi.yaml) and JSON examples.

## Authentication / discovery

- Device registered once by an explicit local pairing workflow; server returns `device_id`, scope-limited token and capability profile. Prefer TLS. See `12-security-and-recovery.md` for constrained DryOS TLS fallback.
- Camera may use configured server IP/port first; mDNS discovery is optional. Don't require DNS/internet.
- Request `GET /v1/health` and `GET /v1/capabilities` before transfer. Capability negotiation includes max chunk size, transport, protocol version, profile bundle / core hash and return JPEG options.

## API sequence

```text
GET  /v1/health
GET  /v1/capabilities
PUT  /v1/rolls/{roll_id}                # sealed manifest, idempotent
POST /v1/uploads                     # original DNG / local JPEG / auxiliary asset
PUT  /v1/uploads/{upload_id}/chunk     # octet-stream + offset header
GET  /v1/uploads/{upload_id}           # resumable offset/state
POST /v1/uploads/{upload_id}/complete  # server hash verification + durable receipt
POST /v1/rolls/{roll_id}/finalize      # all frames expected, enqueue rendering
GET  /v1/rolls/{roll_id}               # upload/render/publish state
GET  /v1/rolls/{roll_id}/renders       # renditions & download identities
GET  /v1/renders/{render_id}/file      # return camera-compatible JPEG
```

`PUT /v1/rolls/{roll_id}` with unchanged manifest hash returns the existing record. A conflicting manifest after `finalize` returns `409`, not silent replacement. `finalize` is safe to retry and only enqueues once. An upload completion ACK includes `asset_sha256`, `bytes`, `server_asset_id` and `durable=true`; client compares against declared expected hash before marking synced.

## Chunk upload

- Request creation: `{device_id, roll_id, frame_id, media_role, filename, bytes, sha256, media_type}`. `filename` is metadata, never a trusted server path.
- Server returns `{upload_id, next_offset, chunk_size}`. Choose a camera-safe chunk size after measurement; proposed default 64 KiB (not guaranteed).
- Client sends `Content-Type: application/octet-stream` with `X-Upload-Offset: N` and chunk bytes.
- Server rejects out-of-order/overlapping conflicting blocks and reports next expected offset. On retry query session; do not restart 20 MB files unnecessarily.
- Server streams to a temporary file, tracks per-session checksum and stores a durable progress checkpoint. Final SHA-256 verifies exact expected size/content.
- Do not use simultaneous uploads from camera until memory/performance verified. Host importer may parallelize safely.

## Result download

- Camera polls only during connection windows (not while powered off). Status includes per-frame render IDs, profile hash, dimensions and SHA-256.
- Download completed server gallery JPEG/thumbnail in bounded chunks to `.part`, verify, then mark locally visible.
- Do not assume server can push unsolicited data to a sleeping camera. Result retrieval happens at *next* camera sync.
- Support result policy: `none`, `thumbnail`, `camera_compatible`, `full_jpeg`.

## Error contract

- `400` malformed input; `401/403` auth/pairing; `404` missing session/asset; `409` mismatched identity or upload offset; `413` oversize; `422` bad DNG / unsupported recipe; `429` throttled; `500/503` transient receiver/worker. Provide stable JSON error code and retryable flag.
- Preserve source bytes and roll record on any network failure. Exponential backoff with jitter, battery-aware maximum attempt rate and manual `Sync Now`.
- Server-only errors do not change the local camera original's hash, identity or exposure order.

## Example manifests

- [`roll-manifest.example.json`](../contracts/roll-manifest.example.json)
- [`render-recipe.example.json`](../contracts/render-recipe.example.json)
- [`device-capabilities.example.json`](../contracts/device-capabilities.example.json)

## Compatibility

All payloads include `schema_version`; API major versions must be negotiated. Recipe/profile/core compatibility is **explicit**. Authenticated idempotency keys are scoped to device and operation, not globally trusted user input. Never accept arbitrary paths from a camera and join them into filesystem paths without canonicalization and confinement.
