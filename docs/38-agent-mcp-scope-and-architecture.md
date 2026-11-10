# 38 — AI Agent Control: MCP/API Scope and System Architecture

**Revision:** v0.8, 2026-11-10. **Implementation scope:** existing Linux M-Film server and Web Darkroom only. **Current assignment:** implement Claude-compatible MCP tooling, not image-processing features or CHDK changes. **Status:** normative implementation specification; not a claim of deployed code.

## Goal

Enable Claude Code (and any compatible MCP client) to develop real photos using the already-running M-Film Linux server: discover assets or PhotoPrism albums, inspect available Camera Looks / Film Stocks / Optical Effects / curated combos, create and update **Render Recipe v2** drafts, request image previews, compare variants, submit final full-resolution render jobs, monitor progress, and optionally publish results to a chosen PhotoPrism folder/album after explicit user approval.

The browser UI and MCP MUST use one application service, one recipe validator, one render engine, one queue, one asset catalog, and one publisher. **Never create a second M-Film renderer, catalog, recipe dialect, PhotoPrism connection pool, or effects menu for agents.** MCP is a protocol adapter / orchestration surface, not a new photo editor.

## Baseline repository contracts to preserve

- `docs/08-linux-service.md`: FastAPI-equivalent backend, native C renderer, DB-backed job worker.
- `docs/23-recipe-compatibility-api.md`, `contracts/render-recipe-v2.schema.json`: canonical `schema_version: 2` recipe, fixed seed, validated camera/film/optical parameter sets.
- `docs/27-web-darkroom-product.md`–`docs/34-web-implementation-and-acceptance.md`: sources (upload, rolls, PhotoPrism), preview jobs, final jobs, and two independent PhotoPrism destination selectors.
- `docs/35-curated-combination-presets.md`–`docs/37-combo-waves-and-acceptance.md`: curated combos and provenance labels.
- `contracts/openapi-web-darkroom.yaml`, `contracts/openapi-creative-extension.yaml`: **proposed** HTTP contracts, not proof that exact routes exist in current implementation. Discover actual server API before wiring calls; prefer direct domain-service invocation if backend code is co-located. Record adapters in a route compatibility matrix.

## Reference implementation: LightCraft (what exists versus what M-Film will implement)

LightCraft source: https://github.com/storytold/lightcraft; MCP specification: https://github.com/storytold/lightcraft/blob/main/docs/mcp.md; code: `crates/mcp/src/{lib,server,tools,backend,headless}.rs`; companion control protocol: `docs/control-protocol.md`.

Verified LightCraft design patterns:

1. UI, CLI, JSON-lines control endpoint and MCP call a shared engine **command registry** with stable IDs and JSON arguments.
2. Headless MCP embeds an engine session; connect mode forwards to a running desktop app using a loopback control channel. These are LightCraft-specific modes, **not requirements to reproduce a graphical UI in server-only M-Film**.
3. Helper tools (`command_list`, `command_run`, `command_batch`, `render_preview`, etc.) and optionally one generated `cmd_*` tool per registered command. `--compact` limits tool list.
4. Previews can be returned as actual MCP image content; structured results include machine-readable JSON and `isError` on tool failures.
5. Read-only resources expose snapshots of state / controls; command results are checked; export has progress/cancellation and avoids partial output files.
6. The upstream docs explicitly warn that annotations like `readOnlyHint` are hints, not authorization boundaries; live-app actions may be non-idempotent and ambiguous after a lost connection.

**Adopt:** command registry, compact high-level tools, structured schema introspection, image previews, headless operation, testable errors, progress, non-destructive edits. **Do not copy:** GUI automation (`click_widget`, `press_key`, screenshots), LightCraft's own RAW engine or library format, legacy control TCP port, its photo-ID/selection semantics, or its unconditional file-path export behavior.

## Target data flow

```text
Claude / other MCP client
    │ MCP stdio (MVP; local process)  [remote authenticated HTTP optional later]
    ▼
M-Film MCP Adapter (new; thin, stateless per request)
    │ strict tool schema + auth context + audit
    ▼
Existing M-Film Application Commands / Domain Services
    ├── Catalog / PhotoPrism source index
    ├── Camera/Film/Optics/Combo catalog + Render Recipe v2 validator
    ├── Preview cache + current native C film/optics pipeline
    ├── Final render queue + worker + immutable renditions
    └── PhotoPrism publisher (existing verified folder/album workflow)
```

No dependence on the user's web-browser presence. No user image bytes are passed to the LLM unless the user initiates an inspect/preview tool call and access is permitted. The LLM never directly accesses server-side arbitrary file paths, database tables, provider credentials, C renderer internals, or shell commands.

## Command registry principle

Introduce a server-internal typed `MFilmCommandBus` or equivalent service-level facade if one is not already present. Stable command IDs (e.g. `assets.search`, `recipes.update`, `renders.preview`, `publishing.publish`) resolve to typed handlers. Web HTTP routes and MCP tools map to these handlers. A command owns parameter validation, identity/permission checks, atomic persistence, domain events, output DTO and error taxonomy. **Do not make HTTP route handlers the primary business-logic implementation.** In an existing FastAPI project, both HTTP and MCP may call the same Python service functions, which orchestrate the pre-existing native film engine.

Expose a **compact, curated MCP tool list** as default. Do not mechanically expose every internal command or user-visible slider as its own MCP tool: tool-list explosion increases token cost and risks accidental writes. `list_capabilities` and `get_recipe_schema` provide introspection; `recipe_update` uses a schema-backed partial patch; `command_batch` is optional after atomic edit semantics exist.

## Session and identity model

MCP transport/session identity is **not** an editing session or persistent user identity. Every operation targets explicit `asset_id`, `draft_id`, `job_id`, `render_id`, `photo_uid`, `album_uid` or `folder_id`. A user-scoped, durable draft exists on the M-Film backend, with immutable `source_asset_id` and monotonically increasing `revision`/ETag. Concurrent web and Claude clients must see revision conflicts (`CONFLICT_REVISION`) rather than overwrite each other's updates. A resumed Claude conversation may retrieve its authorized drafts by ID; never infer an implicit globally selected photo.

## Non-goals

- No camera firmware, CHDK port, Wi-Fi, PTP, on-camera interface or on-camera model inference changes.
- No direct agent modification of RAW originals or in-place image replacement.
- No autonomous publication/delete/album mutation without user authorization and the explicit tool call flow.
- No replacement of existing PhotoPrism albums/search with a second photo-library database.
- No agent-only image processing: Claude chooses parameter values; M-Film does the actual rendering.
- No requirement to add a neural aesthetic scoring model in this release. Claude may visually compare preview images; automatic quantitative scoring is a separately gated extension.

## Definition of done

From Claude Code, the user can ask: "Find three NEF photographs from my chosen PhotoPrism album, try Leica M9 + Portra 400 and S5 Pro + Gold 200, show previews, finalize the preferred version, then publish into my requested PhotoPrism album." The agent must discover real asset and profile IDs, render actual previews, show job state, and publish only when the user has explicitly authorized the destination/action. No placeholder images, simulated success or silent alterations of originals.
