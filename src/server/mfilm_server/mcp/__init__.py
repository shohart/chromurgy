# SPDX-License-Identifier: GPL-2.0-only
"""M-Film Model Context Protocol (MCP) server adapter (docs/38-44)."""
from __future__ import annotations

from .bus import MFilmCommandBus
from .server import create_mcp_server

__all__ = ["MFilmCommandBus", "create_mcp_server"]
