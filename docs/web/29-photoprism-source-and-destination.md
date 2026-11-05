# 29 — PhotoPrism: Browse, Select, Ingest, Re-Publish

This connector is **bidirectional**. PhotoPrism is a *source* of existing RAW media and a *destination* for new full-resolution renders. Integration is performed **server-side** by a version-adapted PhotoPrism connector. User-facing UI only calls the M-Film server; secrets remain in Linux configuration.

## Important semantics

- **Folder:** physical directory under PhotoPrism `originals`, selected by path or validated server-issued folder identifier. Directory destination means placing a new JPEG *file* in an explicitly chosen writable subdirectory.
- **Album:** a logical grouping of PhotoPrism photo records with UID; selecting an album does **not** imply a filesystem path. Album destination means adding the newly indexed photo UID to the target writable manual album.
- Source and output choices are orthogonal: choose *input album A*, *output album B*, *output folder C* in the same job. It must never overwrite or update A's existing photo bytes, even when A == B.

## Supported PhotoPrism API features (verify deployed version)

- `GET /api/v1/albums` — enumerate searchable, paginated albums.
- `GET /api/v1/photos?s=<album_uid>&merged=true...` — enumerate photos in an album (stable pagination); snapshot photo UIDs and files at render enqueue. `GET /api/v1/photos?path=<path>&merged=true...` provides folder-filtered photos; verify recursive behavior and pagination for the installed version.
- `GET /api/v1/folders/originals` — enumerate physical originals folders; alternative read-only originals mount can list folders with allowlisted root.
- `GET /api/v1/photos/{uid}` — retrieve detailed file metadata and detect RAW companion in the photo stack. `merged=true` may group several files per photo; inspect `Files` and file format, never assume primary file is RAW.
- `/api/v1/dl/{file}` uses short-lived **download tokens** for originals; obtain current token and correct file-level identifier/hash, or use authenticated WebDAV `/originals/` via server, or an explicitly configured read-only originals mount. Do not guess download URLs or store tokens indefinitely. Album download ZIP is not the preferred mechanism for RAW-by-RAW development.
- `POST /api/v1/albums` and `POST /api/v1/albums/{uid}/photos` for creating **manual** albums and attaching indexed photo UIDs. Inspect installed version response and `form.Selection` request schema; source documentation of API handlers is not a substitute for deployment test.
- PhotoPrism `/originals/` WebDAV or direct filesystem + indexing are supported publication paths. WebDAV automatically indexes after a configured safety delay by default, but indexing can be disabled or delayed.

Official references: https://docs.photoprism.app/developer-guide/api/search/ , https://docs.photoprism.app/developer-guide/api/ , https://docs.photoprism.app/developer-guide/api/auth/ , https://docs.photoprism.app/user-guide/library/webdav/ , https://docs.photoprism.app/user-guide/organize/albums/ .

## Source browsing and staging algorithm

1. Authenticate and validate instance/capabilities using server-side credentials. Show available folders and editable/manual albums. List photos with pagination and thumbnail URLs proxied or signed using valid authorization; never expose credentials in response JSON.
2. User selects folder or album, then photos. Resolve each selection to immutable PhotoPrism photo UID + **specific RAW file UID/path/hash**. Cases: embedded/multifile RAW+JPEG stack; standalone RAW; JPEG without RAW; unsupported RAW. Mark eligibility distinctly, show counts before the user commits.
3. For each eligible source, take a snapshot of the original file identity and digest/mtime/size. Prefer read-only bind mount under allowlisted `originals` path for same-host deployment; otherwise stream verified source through authenticated WebDAV or original-file download API. Copy to private staging/archive if stable immutability cannot be guaranteed. Do not follow untrusted symlinks outside root. Source path strings are never raw arbitrary server filesystem paths from client.
4. Optionally resolve an M-Film archived DNG associated with a PhotoPrism JPEG via known provenance mapping. Only use it if association is verified by source digest/asset mapping; do not assume same basename. Never label a JPEG conversion as RAW processing.
5. Render using the single shared film+camera+optical engine and recorded versioned recipe. Save canonical rendition and sidecar before attempting PhotoPrism publication.

## Destination and album association algorithm

1. Choose destination folder via browse/validated allowlisted folder, default `MFilm/Developed/<year>/<batch-id>/`. If user chooses only an album, still publish into a dedicated managed output directory: albums cannot store files by themselves.
2. Stage verified JPEG and sidecar in private render store. Publish full file to PhotoPrism destination via atomic placement or complete WebDAV upload, never letting indexer see an incomplete `.jpg`.
3. Trigger/await library indexing using documented configured method, then **reconcile** published file to PhotoPrism photo UID by stable path and/or file checksum, not fuzzy basename search. Keep `publish_state=INDEXING` until actually indexed.
4. If album selected: create target manual album only on explicit user request (idempotent creation/lookup), then add indexed new photo UID via supported API. Album membership cannot occur reliably before indexing. Keep `album_association_state=PENDING` and retry independently of rendering and file transfer.
5. Final UI success: `Rendered` / `Published to folder` / `Indexed` / `Added to album` are distinct statuses. Return PhotoPrism album/photo deep link based on verified deployed base URL and returned IDs. Never invent a success link.
6. If outputs merge into an existing RAW/JPEG stack unexpectedly, record and fix naming/folder strategy; never overwrite original or mutate preexisting PhotoPrism photo record just to appear successful.

## Configuration and compatibility gates

- Read-only library source permissions and write destination permissions may use different PhotoPrism accounts/scopes; prefer least privilege. API client tokens and WebDAV app passwords have different supported authentication semantics. Verify installed PhotoPrism version, auth scopes, read-only/public mode and indexing settings.
- Prefer shared filesystem for self-hosted same-machine installation, but never assume deployment shares volumes. If shared access absent, WebDAV must work. Offer a `Test PhotoPrism Connection` action that tests album enumerate, folder enumerate, raw access, output write and album association separately.
- If PhotoPrism album API is unavailable or permissions insufficient, disable album destination visibly with an actionable error while folder publication remains usable. Do not claim folder == album.
