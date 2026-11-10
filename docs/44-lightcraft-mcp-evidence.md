# 44 — LightCraft MCP: Source-Based Findings and Transfer Decisions

Research date: 2026-11-10. Source repository: https://github.com/storytold/lightcraft. These are verified architectural observations from public upstream code/documentation; actual M-Film backend implementation must be inspected locally by the coding agent.

| LightCraft evidence | Verified finding | M-Film implementation decision |
|---|---|---|
| `crates/mcp/src/lib.rs` | MCP server exposes `Headless` in-process engine and `Remote` desktop loopback adapter via common backend trait | Implement one server-side domain command adapter; no desktop remote mode required |
| `crates/mcp/src/server.rs` | JSON-RPC 2.0 initialization, tool calls, resources, progress/cancellation | Use tested MCP SDK/protocol; robust errors/progress; don't invent agent-only render method |
| `crates/mcp/src/tools.rs` | Curated helpers + generated `cmd_*` per command; structured and image results | Keep ~12–15 curated tools; defer dynamic low-level command exposure; return real images |
| `crates/mcp/src/backend.rs` | Backend trait has `call`, `has_ui`, `describe` and remote reconnect semantics | Abstract access to current M-Film domain service/HTTP; strong idempotency on writes |
| `crates/mcp/src/headless.rs` | Headless session uses same engine and export functions as app | M-Film reuses same C renderer/queue/validator as Web Darkroom |
| `docs/mcp.md` | Tools: inspect, command_list/run/batch, import/query, get/set develop, apply preset, preview/export; resource snapshots; headless and connect modes | Implement search, recipe drafts, image preview, final job, PhotoPrism publish, explicitly ID-based |
| `docs/control-protocol.md` | UI loopback JSONL, stable commands, timeouts, ambiguous post-send failure | Do **not** expose unauthenticated control port; implement durable ID / retry-safe jobs |
| `docs/mcp.md` | `render_preview` returns image without changing photo selection; tool annotations are hints; full `export` not inherently idempotent | Preview read-only; separate publication; actual backend permissions; idempotency keys |
| `docs/mcp.md` | `--compact` limits MCP tool discovery bloat; per-command tool list otherwise large | Default compact tool catalog; schema introspection instead of every slider as tool |
| `docs/mcp.md` | Persistent library mode protects state with lock; dropped connections after dispatch require inspecting state | M-Film uses DB-backed persistent drafts and durable jobs; no global active photo or blind resends |
| `docs/mcp.md` | `crates/mcp/tests/it/e2e.rs` includes real stdio and transport tests, edit -> render tests | Contract/e2e tests with actual RAW, preview image and publication |

## Boundaries of evidence

- No evidence that LightCraft directly supports M-Film profiles, PhotoPrism or our Render Recipe v2; those are local project features.
- LightCraft's Rust crate and code structure is informative, not a drop-in compatible plugin. Most functions should be designed against current M-Film services and their actual validation contracts.
- LightCraft `connect` mode is desktop automation; it is not necessary for a headless Linux film server.
- MCP tool registration details have evolved across versions of LightCraft; pin the observed upstream revision/commit before quoting command names as stable implementation interfaces.
- Never copy upstream README claims as tested results for M-Film. Run real tool calls and image renders.

## Reference URLs

- https://github.com/storytold/lightcraft
- https://github.com/storytold/lightcraft/blob/main/docs/mcp.md
- https://github.com/storytold/lightcraft/blob/main/docs/control-protocol.md
- https://raw.githubusercontent.com/storytold/lightcraft/main/crates/mcp/src/lib.rs
- https://raw.githubusercontent.com/storytold/lightcraft/main/crates/mcp/src/server.rs
- https://raw.githubusercontent.com/storytold/lightcraft/main/crates/mcp/src/tools.rs
- https://raw.githubusercontent.com/storytold/lightcraft/main/crates/mcp/src/backend.rs
- https://raw.githubusercontent.com/storytold/lightcraft/main/crates/mcp/src/headless.rs
- https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
