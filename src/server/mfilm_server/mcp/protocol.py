# SPDX-License-Identifier: GPL-2.0-only
"""MCP Stdio Transport Runner (docs/41)."""
from __future__ import annotations

import io
import json
import logging
import sys
from typing import TextIO

from .server import McpServer

logger = logging.getLogger("mfilm.mcp.stdio")


def run_stdio_server(
    server: McpServer,
    in_stream: TextIO | None = None,
    out_stream: TextIO | None = None
) -> None:
    """Run JSON-RPC 2.0 stdio server loop."""
    inp = in_stream or sys.stdin
    out = out_stream or sys.stdout

    # Configure root logger to output to stderr only
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    )
    logger.info("M-Film MCP stdio server starting")

    while True:
        try:
            line = inp.readline()
            if not line:
                logger.info("EOF reached on stdin, shutting down")
                break

            line_str = line.strip()
            if not line_str:
                continue

            try:
                req = json.loads(line_str)
            except json.JSONDecodeError as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"}
                }
                out.write(json.dumps(err_resp) + "\n")
                out.flush()
                continue

            resp = server.handle_request(req)
            if resp is not None:
                out.write(json.dumps(resp) + "\n")
                out.flush()

        except (KeyboardInterrupt, BrokenPipeError):
            logger.info("Server interrupted or pipe closed")
            break
        except Exception:
            logger.exception("Unexpected exception in stdio loop")

    logger.info("M-Film MCP stdio server exited")
