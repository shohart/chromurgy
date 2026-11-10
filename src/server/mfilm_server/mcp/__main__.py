# SPDX-License-Identifier: GPL-2.0-only
"""CLI entry point for running M-Film MCP stdio server (docs/41)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .. import config as config_mod
from ..store import Store
from .bus import MFilmCommandBus
from .protocol import run_stdio_server
from .server import create_mcp_server


def main() -> int:
    parser = argparse.ArgumentParser(description="M-Film MCP stdio server for Claude Code and AI agents")
    parser.add_argument("--data-dir", default=os.environ.get("MFILM_DATA_DIR"), help="Path to M-Film data directory")
    parser.add_argument("--config", default=os.environ.get("MFILM_CONFIG"), help="Path to M-Film config.toml")
    args = parser.parse_args()

    cfg = config_mod.load(args.config)
    data_dir = Path(args.data_dir or cfg.data_dir)
    store = Store(data_dir)
    store.init()

    bus = MFilmCommandBus(store, config=cfg)
    server = create_mcp_server(bus)
    run_stdio_server(server)
    return 0


if __name__ == "__main__":
    sys.exit(main())
