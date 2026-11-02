# 07 — Development Policy and Gallery Semantics

## Routing decision

**Default:** server develops the roll when its **complete original DNG set** reaches Linux and roll is sealed. No slow on-camera development during shooting.

**Offline fallback:** user selects `Develop on Camera` only when server is unavailable, or explicitly prefers local development. Offline jobs run serially and can be suspended/resumed. They use the exact shared core; output resolution may be reduced with explicit label.

**Auto fallback setting (optional):** offer auto-local-develop only if *server unavailable for a user-configured period* and camera has adequate battery/storage. Default off; silently starting hours of CPU work is unacceptable.

Server development does **not** require the camera to remain awake after RAW upload and verification. A powered-off camera cannot receive results until a later sync session.

## Server-first execution

1. Seal roll on camera; verify all available frame files.
2. During idle sync, send manifest and original DNG files; hashes must match and server must issue durable receipts.
3. Receiver marks roll input-complete after comparing expected frame IDs/count/hashes.
4. Worker chooses recorded film recipe and matching profile bundle, runs full-resolution render for each frame, writes JPEG, validates dimensions and EXIF, then commits.
5. Roll is `server_developed` only if all targeted frames have committed results (partial success reported distinctly).
6. Publisher stages and atomically publishes verified results to PhotoPrism; server retains links to source DNG and render manifest.
7. Next camera sync receives result index and optionally preview-size or full JPEG for **developed gallery**. Downloaded results get separate hash receipts.

## Offline execution

1. User selects a sealed roll and `Develop Here`.
2. Camera checks DNG readiness, battery/memory, available SD space, profile bundle hash.
3. Sequentially process each frame with same core; write `*.part` then verify and commit; record per-frame stage and errors.
4. Local gallery shows only successfully developed frames; a partially developed roll is clearly labeled `INCOMPLETE`.
5. Next server sync **always prioritizes original DNG upload**. Optionally upload local JPEG as an alternate rendition; Linux may create full-size version as the canonical server rendition, preserving local output.

## Gallery model

Gallery is a **view over rendition records**; never simply list every JPEG on SD. Frame visibility requires verified `rendition.status == COMMITTED` and source/roll association. When a server result is ready but not yet downloaded, show a metadata-only entry `Available on server`, not an image pretend-played locally.

Target A: Canon Playback using appropriately recognized DCF image only if proven. Target B: CHDK app rendering actual developed JPEG thumbnails, storing cached previews and full-resolution paths when available. Never guarantee Canon Playback registration without tests.

## Recipe changes and version reconciliation

- Each frame originally belongs to a frozen roll profile. Re-develop with another profile makes a **new rendition**, not a new exposure.
- If server uses newer `film_core_version`, render exact original recipe where possible and preserve provenance. No automatic upgrade that changes historic look unless user chose `Refresh to current film version`.
- If camera and Linux profile bundles differ, stop or negotiate supported common bundle. A `render_id` must never refer to differing pixels under the same declared recipe/output spec.

## Renders returned to camera

Support `return_policy=none|thumbnail|camera_compatible|full_jpeg`. Default `camera_compatible`, whose actual resolution depends on gallery decoder/memory and may be an explicitly derived preview from canonical server JPEG. Store mapping from camera preview asset to full original server rendition. Camera gallery shows quality/source labels.
