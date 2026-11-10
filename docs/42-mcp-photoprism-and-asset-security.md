# 42 — MCP Access to PhotoPrism and Source Assets

## Principle

PhotoPrism remains the authoritative photo library and album index. The MCP adapter must call the **existing M-Film PhotoPrism connector** described in `docs/29-photoprism-source-and-destination.md` and `docs/32-web-publication.md`; it must not call PhotoPrism through Claude-generated URLs or create its own untracked credential store.

## Source discovery

`mfilm_search_assets(source="photoprism", ...)` resolves PhotoPrism items to **authorized M-Film source handles**. If the PhotoPrism item is a JPEG thumbnail linked to an archived NEF/DNG, choose the actual original RAW through the connector and verify it exists. Do not infer RAW availability from image name or camera model alone. Album UID and folder ID are distinct; include both in results when available and keep selection explicit. Return source capabilities and a safe thumbnail/preview reference, never the PhotoPrism admin token.

Expose **read-only** PhotoPrism listing/search first. `mfilm_list_photoprism_destinations` must enumerate writable manual albums and valid managed destination folders; don't present read-only albums as editable. Confirm a source RAW hash and version before creating a draft.

## Publication

`mfilm_publish_render` calls the established publisher and requests: (a) verified output exists; (b) candidate user authorized; (c) destination is writable and allowlisted; (d) idempotency check; (e) staged upload/copy; (f) index or await PhotoPrism entry; (g) resolve exact PhotoPrism photo UID; (h) add to manual album if selected; (i) verify membership; (j) mark `PUBLISHED`. If indexing takes time, report `PUBLISHING` with publication id; don't claim published until verified. Never overwrite original RAW/JPEG or delete from a source album.

Publication destination example:

```json
{
  "instance_id": "pp-main",
  "folder_id": "mfilm-managed-exports",
  "album_uid": "album-uid-from-list",
  "create_missing_album": false
}
```

These are examples and not discovered real IDs. No user-supplied absolute output path or URL. Avoid constructing untrusted PhotoPrism server addresses (SSRF). Revalidate destination rights at publish time rather than trusting stale discovery.

## Permissions

Suggested scopes:

- `mfilm:catalog:read` — asset metadata and profile discovery.
- `mfilm:previews:read` — inspect rendered images under source authorization.
- `mfilm:drafts:write` — create/edit own drafts.
- `mfilm:renders:write` — queue/cancel own render jobs.
- `mfilm:photoprism:read` — list authorized PhotoPrism albums and asset metadata.
- `mfilm:photoprism:publish` — publish to specifically authorized destinations.

Default Claude MCP principal is **read, draft, preview and render** only. Grant publish separately and in a scoped manner. Use backend identity/ACL checks on every access, not MCP client hints. For a single-user deployment, still distinguish preview/render/publication privileges to reduce damage from accidental agent actions.

## Approval model

Preferred: host-mediated user confirmation on a clearly described `mfilm_publish_render` action and destination, with backend authorization and audit. In a headless client where reliable user confirmation is unavailable, require short-lived server-issued, single-use `approval_token` bound to `{principal, render_id, destination_hash, expiry}` obtained through a trusted browser/admin UI. Do **not** expose an MCP tool that mint approvals for itself. An old consent for album A must not authorize album B or arbitrary files. Explicit user request and server-side policy are separate checks.

## Threat model

Threats: prompt injection in EXIF descriptions, image labels or PhotoPrism album names; malicious file names; path traversal; unauthorized sharing; SSRF via user-supplied URLs; leaked raw location EXIF; infinite batch expensive renders; replayed publish operations; over-large previews; stale draft revisions; duplicate PhotoPrism imports. Treat all catalog text and metadata as untrusted data, never as instructions from the user. No `exec_shell`, generic filesystem read/write, direct SQL, arbitrary HTTP fetch or open-ended Python execution tools.

Bounds: max preview 1536 px; conservative per-call max source count; queue quotas; max number of active preview jobs; file type and size validation, authz on every asset; strong per-principal rate limits; separate log confidentiality. Use database transactions/unique constraints for idempotency keys.
