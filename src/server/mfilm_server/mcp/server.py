# SPDX-License-Identifier: GPL-2.0-only
"""MCP Server Protocol Dispatcher (docs/38, docs/41)."""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

import jsonschema

from .bus import MFilmCommandBus
from .errors import McpDomainError
from .tools import find_tool, get_tools_list

logger = logging.getLogger("mfilm.mcp")


class McpServer:
    def __init__(self, bus: MFilmCommandBus):
        self.bus = bus
        self.client_protocol_version: str = "2024-11-05"

    def handle_request(self, req: dict[str, Any]) -> dict[str, Any] | None:
        """Handle a single JSON-RPC 2.0 request or notification."""
        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        if not method:
            return self._rpc_error(msg_id, -32600, "Invalid Request: method missing")

        # Notifications (no id)
        if msg_id is None:
            if method == "notifications/initialized":
                logger.info("Client sent notifications/initialized")
            return None

        # Ping
        if method == "ping":
            return self._rpc_result(msg_id, {})

        # Initialize
        if method == "initialize":
            client_pv = params.get("protocolVersion", "2024-11-05")
            self.client_protocol_version = client_pv
            return self._rpc_result(msg_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False}
                },
                "serverInfo": {
                    "name": "mfilm-darkroom",
                    "version": "0.8.0"
                },
                "instructions": (
                    "M-Film Darkroom MCP service. Discover RAW photos with mfilm_search_assets, "
                    "explore creative looks with mfilm_list_creative_options, create and edit recipe "
                    "drafts with mfilm_create_draft / mfilm_update_draft, inspect real visual output "
                    "with mfilm_render_preview / mfilm_compare_drafts, and queue final renders "
                    "with mfilm_start_development."
                )
            })

        # Tools list
        if method == "tools/list":
            return self._rpc_result(msg_id, {"tools": get_tools_list()})

        # Tools call
        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            tool_def = find_tool(tool_name)
            if not tool_def:
                return self._rpc_error(msg_id, -32601, f"Unknown tool: '{tool_name}'")

            # Validate input schema
            try:
                jsonschema.validate(instance=arguments, schema=tool_def["inputSchema"])
            except jsonschema.ValidationError as e:
                err_path = "/".join(str(p) for p in e.absolute_path) or "(root)"
                return self._rpc_result(msg_id, {
                    "content": [{"type": "text", "text": f"Validation error at {err_path}: {e.message}"}],
                    "structuredContent": {"error_code": "INVALID_PARAMS", "path": err_path, "detail": e.message},
                    "isError": True
                })

            # Execute tool
            try:
                res = self._dispatch_tool(tool_name, arguments)
                if isinstance(res, dict) and "content" in res and "isError" in res:
                    return self._rpc_result(msg_id, res)
                return self._rpc_result(msg_id, {
                    "content": [{"type": "text", "text": json.dumps(res, indent=2)}],
                    "structuredContent": res,
                    "isError": False
                })
            except McpDomainError as e:
                return self._rpc_result(msg_id, e.to_mcp_response())
            except Exception as e:
                logger.exception("Unexpected error executing tool %s", tool_name)
                return self._rpc_result(msg_id, {
                    "content": [{"type": "text", "text": f"Internal execution error: {type(e).__name__}: {e}"}],
                    "structuredContent": {"error_code": "INTERNAL_ERROR", "detail": str(e)},
                    "isError": True
                })

        # Resources list
        if method == "resources/list":
            return self._rpc_result(msg_id, {
                "resources": [
                    {
                        "uri": "mfilm://status",
                        "name": "M-Film Status",
                        "description": "Engine and system readiness summary",
                        "mimeType": "application/json"
                    },
                    {
                        "uri": "mfilm://catalog",
                        "name": "Creative Catalog",
                        "description": "Available camera looks, film stocks and effects",
                        "mimeType": "application/json"
                    },
                    {
                        "uri": "mfilm://recipe-schema/v2",
                        "name": "Render Recipe v2 Schema",
                        "description": "Authoritative Render Recipe v2 JSON schema",
                        "mimeType": "application/json"
                    }
                ]
            })

        # Resources read
        if method == "resources/read":
            uri = params.get("uri")
            if uri == "mfilm://status":
                data = json.dumps(self.bus.status(), indent=2)
            elif uri == "mfilm://catalog":
                data = json.dumps(self.bus.list_creative_options(), indent=2)
            elif uri == "mfilm://recipe-schema/v2":
                data = json.dumps(self.bus.get_recipe_schema(2), indent=2)
            else:
                return self._rpc_error(msg_id, -32602, f"Resource not found: '{uri}'")

            return self._rpc_result(msg_id, {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": data
                    }
                ]
            })

        return self._rpc_error(msg_id, -32601, f"Method not found: '{method}'")

    def _dispatch_tool(self, name: str, args: dict[str, Any]) -> Any:
        b = self.bus
        if name == "mfilm_status":
            return b.status()
        elif name == "mfilm_list_sources":
            return b.list_sources(**args)
        elif name == "mfilm_search_assets":
            return b.search_assets(**args)
        elif name == "mfilm_inspect_asset":
            return b.inspect_asset(**args)
        elif name == "mfilm_list_creative_options":
            return b.list_creative_options(**args)
        elif name == "mfilm_get_recipe_schema":
            return b.get_recipe_schema(**args)
        elif name == "mfilm_list_photoprism_destinations":
            return b.list_photoprism_destinations(**args)
        elif name == "mfilm_create_draft":
            return b.create_draft(**args)
        elif name == "mfilm_get_draft":
            return b.get_draft(**args)
        elif name == "mfilm_update_draft":
            return b.update_draft(**args)
        elif name == "mfilm_render_preview":
            return b.render_preview(**args)
        elif name == "mfilm_compare_drafts":
            return b.compare_drafts(**args)
        elif name == "mfilm_start_development":
            return b.start_development(**args)
        elif name == "mfilm_get_job":
            return b.get_job(**args)
        elif name == "mfilm_cancel_job":
            return b.cancel_job(**args)
        elif name == "mfilm_publish_render":
            return b.publish_render(**args)
        raise McpDomainError("UNKNOWN_TOOL", f"Tool '{name}' dispatch not implemented")

    def _rpc_result(self, msg_id: Any, result: Any) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": result
        }

    def _rpc_error(self, msg_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": err
        }


def create_mcp_server(bus: MFilmCommandBus) -> McpServer:
    return McpServer(bus)
