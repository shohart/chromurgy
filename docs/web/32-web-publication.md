# 32 — Publish Results to PhotoPrism

## Web publishing is a first-class workflow

Publishing is optional at initial job creation but can be requested later from a completed rendition. The web interface shows **two independent selectors**:

1. **Output folder** inside PhotoPrism `originals` (default a managed M-Film namespace; browse writable folders and optionally create a child subfolder).
2. **Output album** (existing *editable/manual* album, newly created manual album, or no album). Selecting `Same album as input` is supported when source was album and user has permissions. Album-only output still uses a managed originals folder.

`Save only to M-Film library` permits completed web renders without PhotoPrism publication. Existing camera/sync publishing remains unchanged and uses the same publisher backend as web jobs.

## Publish algorithm

- Save JPEG and provenance sidecar in canonical M-Film store; validate/checksum first.
- Resolve selected output path strictly relative to allowlisted PhotoPrism originals root. Use deterministic unique path per render and avoid PhotoPrism automatic RAW/JPEG stacking collisions. Never mutate or replace input image. Avoid source and destination being the exact same file path even when same folder selected.
- Direct-mount: copy to temporary non-indexed filename then atomic rename on same filesystem and request/await index. WebDAV: transfer full bytes with server credentials and confirm file, respecting auto-index safety delay; do not assume synchronous indexing.
- Resolve newly indexed image's PhotoPrism UID through exact path or hash correlation. Only after that attach to manual album using PhotoPrism API. Verify new membership and record state.
- The resulting URL in UI points to verified photo/album; before index completion show `Publishing / Awaiting PhotoPrism` and retry in background.
- Preserve optional full-resolution JPEG export/download for user. Original RAW retained in private M-Film archive; optionally expose RAW in PhotoPrism only on explicit source-management workflow, never silently.

## Re-render and versioning

The same RAW can have multiple looks and films. Each new recipe results in distinct versioned JPEG, not in-place edits. If the user explicitly requests `Publish new version to the same album`, add a new photo to that album without deleting earlier renditions. `Replace album selection` is out of scope because it would require privileged destructive PhotoPrism changes.

## PhotoPrism availability failures

All modes must distinguish `rendered locally` from `published in PhotoPrism`. If PhotoPrism is temporarily offline, no output is lost: publication retries on reconnect. Lack of write permissions for a target album must be surfaced immediately when detectable; allow user to redirect to another album without re-render.
