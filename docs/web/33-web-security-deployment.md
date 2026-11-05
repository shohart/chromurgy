# 33 — Web Deployment, Authentication and Security

## Service topology

`Browser -> M-Film Web API (FastAPI or similar) -> durable jobs -> shared native C renderer -> private archive -> PhotoPrism connector -> PhotoPrism`.

- Web UI and API may be bundled into Linux receiver container/service; do not expose camera-facing endpoint credentials to browsers.
- One configured PhotoPrism endpoint or several named instances (optional). Backend owns and manages connectivity, not arbitrary user-supplied URLs per job. Expose connector health and capabilities, no credentials.
- For same-host deployment, bind-mount `originals` read-only for input and separately allowlisted output path read/write; if permissions conflict, use PhotoPrism WebDAV for publishing. Document container UID/GID and safe volume mapping.
- Deployment can run on a local LAN without public Internet. Internet exposure requires HTTPS, authenticated app access and hardened reverse proxy.

## Security requirements

1. Authenticate users for web darkroom; role-check read PhotoPrism sources and write destination albums/folders. Never assume because connector uses admin account the web user has permission to see every album.
2. Store PhotoPrism API token / WebDAV app password in secrets/environment files with restrictive permissions. PhotoPrism's API client access tokens and WebDAV credentials are **not identical**; configure separately if necessary. Rotate secrets and verify scopes.
3. Allowlist server PhotoPrism hostname/IP and mounted path. Validate redirects, block SSRF, verify TLS certificates; never accept `file://`, `http://169.254...` or arbitrary external URL for source acquisition.
4. Sanitize names, reject `..` traversal, symlinks outside mounted root and absolute user-supplied paths. Normalize Unicode safely; preserve display names in metadata, generate safe physical filenames.
5. Restrict max file count, per-file bytes, pixels, rendering time, concurrent workers and storage quotas. Scan magic and use sandboxed/constrained RAW decoding; worker crashes must not terminate API.
6. Protect browser state against CSRF if cookie auth, and against XSS in user file/album names. Preview/download endpoints require authentication. Set SameSite and secure cookies as appropriate.
7. Never send raw originals into client-side JS for preview, only reduced JPEG images generated server-side. Use expiring preview URLs or authenticated fetch; do not cache photos in shared HTTP proxies.
8. Keep upload temp and private originals off PhotoPrism exposed content until deliberate publication. Never delete or overwrite originals as a cleanup measure.
9. Audit source read, render request, output publication, album changes and failures without logging credentials or full bearer tokens.

## Observability and recovery

- Readiness vs liveness checks for web API, worker, decoder, PhotoPrism connectivity and queue.
- Configured periodic reconciliation for pending indexing and album membership, idempotent API and retry keys, bounded exponential backoff.
- Database migrations, backup and disaster recovery tested for existing camera roll queue and v2 recipes.
