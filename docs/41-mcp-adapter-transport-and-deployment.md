# 41 — MCP Adapter, Transport and Deployment

## Implementation options

Preferred: Python MCP server as a **thin adapter** to existing M-Film application services / FastAPI, using a mature MCP SDK or a deliberately small protocol implementation with compatibility tests. Do not rewrite native C processing code. Choose implementation after auditing the actual server stack; do not force Python if current service uses a different language. LightCraft uses a hand-written Rust stdio server (`crates/mcp`) around an engine session; its key lesson is shared domain commands, **not** that M-Film must port to Rust.

Initial transport: **stdio** for Claude Code running on the Linux server (or over SSH launching a process there). Use separate stdin/stdout strictly for protocol frames; route logs to stderr. Implement MCP initialize, capability negotiation, tools/list, tools/call, ping and cleanup; resources/list/read if implemented. Support a protocol version actually negotiated with the client (pin SDK and test). Avoid manually assuming the newest 2026-07-28 behavior if library/client only supports 2025-06-18.

**Remote transport is optional, later:** Streamable HTTP over an authenticated endpoint with proper origin validation, per-request authorization, rate limits, HTTPS and ideally VPN or tunnel. The 2026-07-28 protocol revised Streamable HTTP transport semantics; follow the exact official transport revision your chosen SDK implements. Do not expose stdio through an ad-hoc unauthenticated TCP relay or bind a development MCP HTTP listener to 0.0.0.0.

## Where MCP code lives

Suggested files, adapt to actual repository:

```text
server/
  app/
    services/commands/       # existing/create minimal shared application facades
      catalog.py
      recipe.py
      render.py
      photoprism.py
    mcp/
      __main__.py             # stdio entry point
      server.py               # tool registration and protocol
      tool_handlers.py        # thin DTO adapters / validation
      auth_context.py         # principal / scoped tokens
      schemas.py              # references authoritative existing JSON schema
      errors.py
      image_blocks.py         # preview bytes -> MCP image content
  tests/mcp/
    test_stdio_protocol.py
    test_tools_workflows.py
    test_security.py
    test_preview_image.py
  config/
    mcp.example.env           # never real tokens
```

The MCP adapter calls existing application services in process if co-located, or calls the existing API with a dedicated scoped token if distributed. HTTP clients use bounded timeouts and retries **only for idempotent reads**; writes require idempotency keys/status reconciliation. Prefer a single command-bus interface if the Web UI and MCP currently have duplicated validation.

## Claude Code registration: local server example

After packaging a real executable entry point, a user running Claude Code on the same Linux machine can register it with a command **equivalent** to (adjust paths to actual installation):

```bash
claude mcp add --scope user --transport stdio mfilm -- /opt/mfilm/venv/bin/python -m mfilm_server.mcp
```

`mfilm_server.mcp` above is a **proposed module path**, not an existing installed package; developer must implement and document actual name. For environments with remote backend API, MCP process may use `MFILM_API_BASE_URL=http://127.0.0.1:<configured-port>` and retrieve the scoped token from a secure environment/secret provider, not from an example config checked into Git.

Example project-local configuration (illustrative, do not commit secrets):

```json
{
  "mcpServers": {
    "mfilm": {
      "command": "/opt/mfilm/venv/bin/python",
      "args": ["-m", "mfilm_server.mcp"],
      "env": {
        "MFILM_API_BASE_URL": "http://127.0.0.1:8080"
      }
    }
  }
}
```

Port 8080 here is a placeholder: discover the actual M-Film port and update configuration. For Claude Code installed on a different machine, either use an SSH launcher that runs MCP on the host through stdio, or deploy the optional remote Streamable HTTP endpoint; do not assume Claude Code has access to server-local paths.

## Lifecycle and transactions

- Starting/stopping MCP **does not** start/stop the independent M-Film renderer/worker and must not kill existing render jobs.
- Every tool call resolves principal + scopes + explicit IDs, with no process-global mutable active photo.
- MCP initialization can expose server instructions that define the safe workflow but does not include private user data or hidden PhotoPrism secrets.
- Tool lists remain stable unless the enabled tool set actually changes. Return `list_capabilities` for runtime feature availability; no phantom features for profiles not yet deployed.
- No long-running render in a synchronous MCP call: enqueue and immediately return `job_id`; progress polling separate. Preview can be synchronous within limits or be async if expensive; if so provide a poll/retrieve path that returns MCP image bytes.
- Gracefully close stdio, flush only adapter-level logs; durable jobs/drafts remain in DB.
- Tool outputs: stable JSON field names, RFC3339 timestamps, normalized IDs, explicit `status` enums. Restrict thumbnail/preview data size.
- MCP telemetry/logs must be structured and correlate `request_id`, `tool`, `principal`, `asset_id`/`job_id`, latency, outcome. Never log original image bytes, secrets, prompt text, private paths or unredacted EXIF GPS.

## Compatibility and versioning

Keep MCP tool names stable through `v1`. Expose `mfilm_status` with `mcp_adapter_version`, `backend_api_version`, `recipe_schema_version`, `renderer_build` and `catalog_bundle_version`. Add optional parameters compatibly; breaking changes use a new tool or versioned input. `render-recipe-v2` remains canonical; any future recipe v3 must include explicit migration and no destructive coercion. Avoid a blanket `execute_any_command` tool in v1; it weakens validation and makes accidental commands easier.

## Source references

- LightCraft: https://github.com/storytold/lightcraft/blob/main/docs/mcp.md
- LightCraft MCP crate: https://github.com/storytold/lightcraft/tree/main/crates/mcp
- LightCraft command channel: https://github.com/storytold/lightcraft/blob/main/docs/control-protocol.md
- MCP tools and image content: https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- MCP Streamable HTTP: https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
