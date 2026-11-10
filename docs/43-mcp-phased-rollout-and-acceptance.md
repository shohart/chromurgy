# 43 — Implementation Waves for Claude MCP Integration

This is an **incremental extension to the existing Linux server**, not a rewrite of M-Film. Do **not** start CHDK, new RAW decoders, new optical effects, different creative profiles, a second PhotoPrism library, or a standalone AI renderer. Make an inventory of already-implemented server routes/services and implement only missing layers.

## Wave 0 — Inventory and adapters (mandatory preflight)

1. Inspect current M-Film backend, Web Darkroom HTTP endpoints, renderer, recipe validator, queue, source catalog and PhotoPrism connector.
2. Produce `MCP_GAP_REPORT.md` with actual files/functions, present endpoints and deviations from proposal contracts in `contracts/openapi*.yaml`.
3. Confirm latest deployed Render Recipe schema; preserve `render-recipe-v2` and existing preset/effect IDs.
4. Decide co-located service calls vs internal authenticated API; document tradeoff.
5. Create code skeleton, tests and `MFilmCommandBus` interface around existing services.

**Exit gate:** mapping from each proposed MCP tool to a real handler/service, with no renderer duplication.

## Wave 1 — Read-only MCP usable in Claude

- Implement stdio MCP transport, initialize, tools/list, tools/call, schema discovery, meaningful errors, stderr-only logs.
- Implement status, sources, search/inspect asset, creative options, recipe schema and read-only PhotoPrism destinations.
- Register MCP in Claude Code; demonstrate actual NEF and DNG retrieval and catalog lookups.
- Verify malformed parameters return validation errors and no writes occur.

**Exit gate:** Claude can find a real RAW and list real Camera Looks, Film Stocks, Optical Effects and 21 combos (only if deployed) without changing any state.

## Wave 2 — Drafts, visual preview and comparison

- Implement draft create/get/update, optimistic concurrency and immutable source references.
- Implement preview with actual image content returned to MCP, correct source/recipe hash and stable seed.
- Add `mfilm_compare_drafts` with per-image labels, bounded 2–4 variants and real preview data.
- Compare same asset + recipe in MCP vs Web Darkroom at matching resolution; document acceptable differences.
- On concurrent edits, backend must return conflict, not overwrite.

**Exit gate:** Claude edits a recipe and sees an actual preview; second user can safely edit a different draft and stale revision fails.

## Wave 3 — Durable full render and PhotoPrism publication

- Implement final enqueue, status, cancellation, durable idempotency key and job recovery across MCP disconnect.
- Final render uses the existing worker, same validated recipe and full-resolution original; no preview upscaling.
- Implement publication workflow through the existing PhotoPrism connector with separate, verifiable approval.
- Handle temporary PhotoPrism outage with retriable publication status and no false success.

**Exit gate:** end-to-end human-confirmed Claude → preview → full render → selected PhotoPrism album, preserving originals and preventing duplicate exports on retry.

## Wave 4 — Hardening and operator delivery

- Security test against path traversal, prompt injection in PhotoPrism metadata, unauthorized IDs, quota exhaustion and publish replay.
- Test cancelled/failed renderer state, mismatched checksum, lost tool response, server restart and concurrent 2+ clients.
- Instrument latency, cache hits and error codes; redact paths and secrets.
- Package `mfilm-mcp`/entry point with systemd-independent operation; include README, sample Claude config, minimal scopes guide and troubleshooting.
- Optionally add secured Streamable HTTP endpoint only after stdio and security gates pass.

**Exit gate:** documented reproducible deployment and acceptance suite passing on real Linux instance.

## Non-negotiable acceptance tests

| ID | Test | Expected result |
|---|---|---|
| A01 | Claude MCP lists tools | Stable compact tool set with valid input schemas |
| A02 | Search real Nikon NEF + Canon DNG | Authorized asset IDs and accurate metadata; no fabricated matches |
| A03 | Unknown profile/effect ID | Validation error; no silent replacement |
| A04 | Create two presets on one image and preview | Two real image blocks; correct provenance and readable dimensions |
| A05 | Update stale draft revision | `CONFLICT_REVISION`; original draft unchanged |
| A06 | Same recipe in Web UI and MCP | Same canonical recipe hash; visually equivalent preview within documented tolerance |
| A07 | Start final render twice with same idempotency key | One durable job / one final output |
| A08 | MCP process exits during render | Worker continues; job can be polled by a new MCP instance |
| A09 | Publish without valid approval | Denied; PhotoPrism untouched |
| A10 | Publish to album A | Verified PhotoPrism image UID and album A membership only |
| A11 | PhotoPrism unavailable midway | `PUBLISHING` / `RETRY_PENDING`, no fabricated completion or RAW loss |
| A12 | Side effects and source integrity | SHA-256 of original RAW unchanged; no overwrite of existing renders |
| A13 | Prompt injection in EXIF/album label | Treated as content; cannot change tool behavior or privileges |
| A14 | Oversized preview / pagination | Bounded by caps; service remains responsive |
| A15 | Server logs after failure | No PhotoPrism token, RAW bytes, GPS or secret fields |
| A16 | Explicit 3-way look comparison | Real three images with stable IDs; no invented aesthetic scores |

Run tests with server fixtures and *at least one real* DNG and NEF (consented test files); keep those files out of source control. Use a PhotoPrism test instance for writes, verify album membership and index status rather than assuming success from HTTP 200. Test both same-host stdio and representative transport failures. No success claim without executed test evidence.

## Developer deliverables

1. Working MCP adapter source integrated into M-Film backend repo.
2. Typed tool schemas and example input/output; minimal `mcp` tool registry.
3. CLI invocation and Claude Code registration steps.
4. A sample complete prompt transcript with *real* tool outcomes and preview rendering (redacted images or consented fixtures only).
5. Unit/integration/security/contract tests with logs.
6. API and source-mapping report; no duplicate renderer.
7. Precise known limitations / feature gates, with server-side PhotoPrism and creative profile availability checks.

**Implementation-first instruction:** start Wave 0, proceed through Wave 3 without requesting approval for routine coding tasks. Ask user only for secrets/credentials, real test RAWs, access/approval to publish and other consequential actions. Tests that require unavailable external services must be honestly marked blocked, not passing.
