#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Runs isolated test web darkroom server with AI processing on port 8767.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
VENV_PY="${SCRIPT_DIR}/src/server/.venv/bin/python"

PORT="${1:-8767}"
HOST="${2:-0.0.0.0}"

echo "=========================================================="
echo " Starting M-Film / Chromurgy AI Darkroom Test Server"
echo " Host: ${HOST}:${PORT}"
echo " Branch: $(git branch --show-current)"
echo " GPU: $(nvidia-smi --query-gpu=name,memory.free --format=csv,noheader 2>/dev/null || echo 'No GPU detected')"
echo " URL: http://localhost:${PORT} or http://192.168.1.122:${PORT}"
echo "=========================================================="

exec "${VENV_PY}" -m mfilm_server.darkroom.app --host "${HOST}" --port "${PORT}"
