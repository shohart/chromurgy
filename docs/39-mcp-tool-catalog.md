# 39 — MCP Tool Catalog and Typed Contracts

Every tool below belongs to **the same backend** as existing Web Darkroom operations. These are proposed MCP names to be implemented, not claims of already-existing functions. Implement all tools in Waves 1–3 unless explicitly marked optional. Expose small, stable input schemas (`additionalProperties: false`) and machine-readable response schemas. Use opaque IDs returned from actual catalog queries. `limit` pagination must be bounded.

## Read-only discovery (Wave 1)

| MCP tool | Required inputs | Structured output | Notes |
|---|---|---|---|
| `mfilm_status` | none | engine/build/schema versions, service health, PhotoPrism availability and authorized feature flags | Sanitized; no secrets, absolute data roots or token values. |
| `mfilm_list_sources` | `kind?`, `cursor?`, `limit?` | source/roll/user-upload identifiers, types and pagination | Filter to assets authorized for caller. |
| `mfilm_search_assets` | `source`, `query?`, `album_uid?`, `folder_id?`, `camera_model?`, `format?`, `cursor?`, `limit?` | `asset_id`, thumbnails refs, metadata, format, roll & PhotoPrism association | Never send arbitrary PhotoPrism filesystem paths back as operational handles. |
| `mfilm_inspect_asset` | `asset_id` | metadata, immutable source hash, supported edit features, preview readiness, recipe refs | Give RAW/NEF/DNG dimensions, orientation, date, ISO etc.; don't leak private location by default. |
| `mfilm_list_creative_options` | `type?` (camera_look/film/optical/combo), `query?`, `cursor?`, `limit?` | canonical IDs, display labels, versions, provenance, categories, availability | Include all currently deployed profiles/effects, not fabricated ones. |
| `mfilm_get_recipe_schema` | `schema_version?` | schema or URI, supported values/constraints, defaults, compat info | Derived from authoritative existing v2 validation and engine registry. |
| `mfilm_list_photoprism_destinations` | `instance_id?`, `kind: album|folder`, `query?`, `cursor?` | **writable** album UIDs/folder IDs and user-visible names, permissions | Must resolve to configured PhotoPrism connector. Read operations cannot mutate albums. |

`mfilm_search_assets` source types: `mfilm_library`, `roll`, `upload`, `photoprism`. `format` accepts actual implemented decoder formats (NEF/DNG mandatory for this project, others conditional on existing engine support). Queries must not imply unsupported full-text indexing. Enforce authorization and server-side pagination even if PhotoPrism itself returns more items.

## Recipe lifecycle (Wave 2)

| MCP tool | Required inputs | Result | Semantics |
|---|---|---|---|
| `mfilm_create_draft` | `asset_id`, `preset_id?`, `recipe?` | `draft_id`, `revision`, validated full `render-recipe-v2`, `recipe_hash` | Copies preset into materialized recipe; no changes to originals. |
| `mfilm_get_draft` | `draft_id` | source ID, complete recipe, revision, provenance | Read-only. |
| `mfilm_update_draft` | `draft_id`, `expected_revision`, `patch` | updated canonical recipe + revision, warnings | Atomic JSON merge patch semantics with allowlisted fields; validate entire recipe; reject unknown effect/param; no change on failure. |
| `mfilm_render_preview` | `draft_id`, `revision`, `max_side?` (default 1024, cap 1536), `format?` | **MCP image** (PNG/JPEG) + text/structured metadata, `recipe_hash`, preview id | Render actual pipeline; pure preview must not save a final rendition or alter draft. |
| `mfilm_compare_drafts` | `draft_ids` (2–4), `max_side?`, `layout?` | actual image blocks per variant or one labeled grid; IDs and hashes | Render using same original and backend for fair comparison; reject different sources unless explicitly supported. |

Use existing `render-recipe-v2.schema.json`: `camera_look`, `film`, `optical.stack`, `render`, `seed`, etc. An `mfilm_update_draft` patch must not remove unknown fields behind a broad replacement. Input patch **does not** accept untrusted file URLs, arbitrary Python expressions, code fragments, or remote image locations. Every preset is expanded and pinned to the catalog version/profile hash at draft creation. `seed` and processing versions remain stable for repeatable comparisons.

## Rendering / publication (Wave 3)

| MCP tool | Required inputs | Result | Semantics |
|---|---|---|---|
| `mfilm_start_development` | `draft_id`, `revision`, `idempotency_key`, `output?` | `job_id`, queue state, frozen recipe/source hash | Final native-resolution job in **existing** worker queue; never overwrite RAW. |
| `mfilm_get_job` | `job_id` | state, progress, warnings, `render_id?`, actual output info | Polling; no completion claim until validated durable result. |
| `mfilm_cancel_job` | `job_id` | cancellation accepted/status | Best-effort; no accidental deletion of completed work. |
| `mfilm_publish_render` | `render_id`, `destination`, `idempotency_key`, `approval_token?` | publication state, server `publication_id`, verified PhotoPrism UID/album membership once complete | Requires explicit user authorization (see doc 43); no default remote publication. |

`mfilm_start_development` writes only M-Film managed output under the existing renderer's storage policy; a relative `output` hint is allowed only if backend already supports one and validates it. No arbitrary absolute `path`, `directory`, `command`, or `url` input. Publishing is separate from rendering so an agent can show the finished image before external publication. If the user explicitly requested both render and publish in one utterance, the client UI/host may treat that as an authorization only to the approved destination; server still checks scopes and approval mode.

## Optional ergonomic tools, not required for MVP

- `mfilm_list_drafts` — recover drafts after Claude restarts.
- `mfilm_get_render` — inspect output format, size and provenance; may return small image thumbnail.
- `mfilm_batch_develop` — bounded batch operation with per-item job state; enable only after per-item safety and queue limits are proven.
- `mfilm_list_jobs` — paginated jobs authorized for caller.
- `mfilm_suggest_variants` — deterministic curated preset suggestions based on film/camera metadata, not pretend image understanding or a new generative model.

## Resources / prompts

Optional read-only MCP resources (`mfilm://...`) can include `/capabilities`, `/catalog`, `/recipe-schema/v2`, `/drafts/{id}`, `/jobs/{id}`. **Explicit identifiers** are necessary: no `mfilm://photo/active` global mutable selection. Resources return JSON snapshots; no promise of live subscriptions unless implemented. Keep default tool payload compact. A single optional MCP prompt `try_three_looks` may guide an agent to (a) inspect (b) create three drafts (c) preview (d) compare (e) ask before finalizing; it must never authorize publishing automatically.

## Output and error contract

For JSON tools, return an MCP text content block containing compact JSON plus `structuredContent`. For preview, return actual `{type: "image", data: <base64>, mimeType: "image/png"}` with a text block giving `draft_id`, revision, source hash, recipe hash, dimensions, and approximate effective scale. Never return local file paths as a substitute for an image. Apply quotas to image byte size and dimensions. Preview may be delivered as a resource link when a client cannot accept images; URL must be short-lived and authorized.

Errors: JSON-RPC protocol faults (`-32700`, `-32600`, `-32601`, `-32602`) remain protocol errors; execution failures return `isError: true` and a stable domain code such as `ASSET_NOT_FOUND`, `UNSUPPORTED_RAW`, `UNKNOWN_PROFILE`, `RECIPE_INVALID`, `CONFLICT_REVISION`, `QUOTA_EXCEEDED`, `RENDER_FAILED`, `JOB_UNKNOWN`, `PUBLISH_NOT_APPROVED`, `PHOTOPRISM_UNAVAILABLE`. Attach actionable field paths and messages, but no stack traces/credentials. A timeout with unknown mutation outcome requires the caller to inspect job/publication status using the idempotency key; never retry blind writes.
