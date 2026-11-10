# 40 — End-to-End Claude Workflows and Renderer Parity

## Workflow A — interactive single RAW

User: "Use my Nikon D5100 NEF, try Portra 400 with Leica M9, and make the sunset glow softer."

1. `mfilm_status` -> confirm service, engine version, PhotoPrism connector if relevant.
2. `mfilm_search_assets` -> locate the actual NEF; reject ambiguous matches and ask the agent user to select if necessary.
3. `mfilm_inspect_asset` -> confirm valid decoder, metadata, rights and color capabilities.
4. `mfilm_list_creative_options` -> resolve **real** profile IDs and supported parameters; `mfilm_get_recipe_schema`.
5. `mfilm_create_draft` with canonical combo or explicit Render Recipe v2.
6. `mfilm_render_preview` -> receive actual small rendered image and return it to Claude for visual inspection.
7. `mfilm_update_draft` e.g. reduce `soft_sun_glow` optical strength with `expected_revision`.
8. `mfilm_render_preview` -> inspect change, optionally compare two drafts.
9. User chooses; `mfilm_start_development` -> durable job; `mfilm_get_job` until success; final output remains in M-Film library.
10. If explicitly asked, list permitted PhotoPrism destinations, resolve target album/folder, seek approval, then `mfilm_publish_render` and poll until indexed/membership confirmed.

The agent must not claim to have seen an image if it only received a JSON job ID. The preview tool must return image bytes or a real client-accessible image resource. No fabricated aesthetic grading or false statements about the photo.

## Workflow B — PhotoPrism album batch

User: "From album `Autumn 2026`, choose the portraits, try Fuji S5 Pro + Gold 200, show a contact sheet before publishing to `Edited Favorites`."

- `mfilm_list_photoprism_destinations` for album selection + `mfilm_search_assets(source=photoprism, album_uid=...)` with pagination.
- Confirm selection with user if criteria are subjective or require unimplemented face/subject analysis. Merely filtering by folder names is not portrait recognition.
- Create independent drafts for selected images; process with fixed bounded concurrency (configured, default <= 3 previews, <= 2 full renders; tune after benchmarks).
- Return 2–4 representative previews and their recipe hashes. Use deterministic contact sheet if implemented in existing backend; otherwise show individual images.
- Final render jobs remain persisted if Claude disconnects; `mfilm_get_job` recovers outcome.
- Publish to the explicit selected destination only after authorization. Each output is a separate version; originals and old PhotoPrism items stay untouched.

## Workflow C — compare and curate

User: "Show three looks for this frame: Portra Soft Portrait, 800T Neon Halo, Golden Haze II."

Agent looks up the canonical IDs, makes three drafts with the **same** `asset_id`, and calls `mfilm_compare_drafts`. Result includes each image with source identity and profile composition. If one preset references an unavailable effect, report that it is unimplemented; **do not substitute** a different effect silently. User then chooses one for full develop. Store the chosen full recipe, not only the preset display name.

## Non-destructive, deterministic semantics

- Source identity is a stable asset key with SHA-256 hash; originals are immutable.
- Draft recipe is versioned and canonicalized with pinned camera look/profile/effect versions.
- Identical source + canonical recipe + renderer/build + profile bundle + output settings + seed produces equivalent output given the same runtime configuration; record known non-bit-exact hardware differences.
- Preview and final use the same core C film algorithm; differences permitted only due to scale, color management, downsampling or documented approximate stages. Preview is always labeled as preview.
- `preview_cache_key = source_sha256 || canonical_recipe_hash || core_version || profile_bundle_hash || max_side || colorspace || crop` (unambiguous length-prefixed encoding + SHA-256 recommended).
- Avoid applying Camera Look LUTs in a different order in MCP than in Web Darkroom.
- Never perform film/effect calculations in MCP middleware or in Claude instructions.
- Existing Web Darkroom sidecar provenance and PhotoPrism publication behavior must be identical whether the request originated in the browser or Claude.

## Coordination with Web UI

MCP edits and Web UI edits are **not** the same implicit 'currently open photo'. They may share a draft via an explicit `draft_id` and optimistic revision. If the web UI edits revision 7 while Claude still holds revision 6, MCP must receive `CONFLICT_REVISION` and reload instead of silently overwriting. The UI may show agent-created draft versions as part of the edit history. Web-UI and agent previews should match within documented rendering tolerances for identical source/recipe/size.

## Agent-facing interaction policy

Agent asks only when a decision affects user intent: ambiguous source, choice between preview candidates, or publication destination/authorization. Parameter exploration, safe read-only inspection and preview do not require permission each time if the user granted session access. Publishing, destructive file movement or overwrites must not be inferred from vague artistic instructions. If PhotoPrism is offline, render locally and preserve `PUBLISH_PENDING`; do not misreport delivery.
