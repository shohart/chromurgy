# SPDX-License-Identifier: GPL-2.0-only
"""Comprehensive test suite for M-Film MCP adapter (docs/38-44)."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest

from darkroom_fixtures import DNG
from mfilm_server import core, db
from mfilm_server.darkroom import app as dapp
from mfilm_server.darkroom import auth, combos, grades_catalog, recipe2
from mfilm_server.mcp.bus import MFilmCommandBus
from mfilm_server.mcp.protocol import run_stdio_server
from mfilm_server.mcp.server import create_mcp_server
from mfilm_server.mcp.tools import get_tools_list

needs_core = pytest.mark.skipif(not core.lib_path().is_file(), reason="needs built film core")
needs_dng = pytest.mark.skipif(not DNG.is_file(), reason="needs a real CHDK DNG")


@pytest.fixture
def bus(store):
    from mfilm_server.darkroom import engine
    import shutil
    if core.lib_path().is_file():
        (store.root / "bundles").mkdir(exist_ok=True)
        shutil.copy(core.bundle_path(), store.root / "bundles" / f"{engine.current_bundle().sha256}.bin")
    return MFilmCommandBus(store)


@pytest.fixture
def mcp_server(bus):
    return create_mcp_server(bus)


def test_a01_tools_list_schema(mcp_server):
    """A01: MCP lists tools with valid JSON input schemas."""
    tools = get_tools_list()
    assert len(tools) == 16, f"Expected 16 tools, got {len(tools)}"

    tool_names = [t["name"] for t in tools]
    expected = [
        "mfilm_status",
        "mfilm_list_sources",
        "mfilm_search_assets",
        "mfilm_inspect_asset",
        "mfilm_list_creative_options",
        "mfilm_get_recipe_schema",
        "mfilm_list_photoprism_destinations",
        "mfilm_create_draft",
        "mfilm_get_draft",
        "mfilm_update_draft",
        "mfilm_render_preview",
        "mfilm_compare_drafts",
        "mfilm_start_development",
        "mfilm_get_job",
        "mfilm_cancel_job",
        "mfilm_publish_render",
    ]
    for exp in expected:
        assert exp in tool_names, f"Missing tool: {exp}"

    # Verify JSON-RPC initialize and tools/list request
    init_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"}
    })
    assert init_res["result"]["serverInfo"]["name"] == "mfilm-darkroom"

    list_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list"
    })
    assert len(list_res["result"]["tools"]) == 16


def test_mfilm_status_tool(mcp_server):
    res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {"name": "mfilm_status", "arguments": {}}
    })
    assert not res["result"].get("isError")
    st = res["result"]["structuredContent"]
    assert st["service_health"] == "OK"
    assert st["recipe_schema_version"] == 2
    assert st["counts"]["camera_looks"] >= 8
    assert st["counts"]["film_stocks"] >= 20
    assert st["counts"]["curated_combos"] == 21
    assert st["counts"]["color_grades"] == 16


def test_mfilm_list_creative_options_tool(mcp_server):
    res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {"name": "mfilm_list_creative_options", "arguments": {"type": "combo"}}
    })
    assert not res["result"].get("isError")
    items = res["result"]["structuredContent"]["items"]
    assert len(items) == 21
    ids = [it["id"] for it in items]
    assert "portrait-portra-gentle-v07" in ids
    assert "cinestill-neon-halo-v07" in ids


def test_mfilm_get_recipe_schema(mcp_server):
    res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 30,
        "method": "tools/call",
        "params": {"name": "mfilm_get_recipe_schema", "arguments": {"schema_version": 2}}
    })
    assert not res["result"].get("isError")
    schema = res["result"]["structuredContent"]
    assert schema.get("schema_version") == 2 or "properties" in schema


@needs_dng
def test_a02_a04_a05_drafts_and_preview(mcp_server, bus, store):
    """A02, A04, A05: Create draft from real DNG, preview with ImageContent, optimistic locking."""
    import hashlib
    dng_data = DNG.read_bytes()
    sha = hashlib.sha256(dng_data).hexdigest()
    # Promote into sources
    sources_dir = store.root / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    dng_dest = sources_dir / "test.dng"
    dng_dest.write_bytes(dng_data)

    conn = bus.get_connection()
    conn.execute(
        "INSERT INTO sources (id, sha256, origin, filename, format, bytes, path, eligible, meta) VALUES (?, ?, 'upload', 'test.dng', 'dng', ?, 'test.dng', 1, '{}')",
        ("up_test123", sha, len(dng_data))
    )
    conn.close()

    # Search assets (A02)
    s_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 40,
        "method": "tools/call",
        "params": {"name": "mfilm_search_assets", "arguments": {"source": "upload"}}
    })
    assert not s_res["result"].get("isError")
    items = s_res["result"]["structuredContent"]["items"]
    assert len(items) >= 1
    assert any(it["asset_id"] == "up_test123" for it in items)

    # Inspect asset
    ins_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 41,
        "method": "tools/call",
        "params": {"name": "mfilm_inspect_asset", "arguments": {"asset_id": "up_test123"}}
    })
    assert not ins_res["result"].get("isError")
    assert ins_res["result"]["structuredContent"]["asset_id"] == "up_test123"

    # Create draft 1 with Portra Soft Portrait (A04)
    d1_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 42,
        "method": "tools/call",
        "params": {"name": "mfilm_create_draft", "arguments": {"asset_id": "up_test123", "preset_id": "portrait-portra-gentle-v07"}}
    })
    assert not d1_res["result"].get("isError")
    d1_id = d1_res["result"]["structuredContent"]["draft_id"]
    assert d1_res["result"]["structuredContent"]["revision"] == 1

    # Create draft 2 with Neon Halo (A04)
    d2_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 43,
        "method": "tools/call",
        "params": {"name": "mfilm_create_draft", "arguments": {"asset_id": "up_test123", "preset_id": "cinestill-neon-halo-v07"}}
    })
    assert not d2_res["result"].get("isError")
    d2_id = d2_res["result"]["structuredContent"]["draft_id"]

    # Preview draft 1 (A04: actual ImageContent returned)
    pv_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 44,
        "method": "tools/call",
        "params": {"name": "mfilm_render_preview", "arguments": {"draft_id": d1_id, "revision": 1, "max_side": 512}}
    })
    assert not pv_res["result"].get("isError")
    content = pv_res["result"]["content"]
    img_block = next((c for c in content if c["type"] == "image"), None)
    assert img_block is not None, "ImageContent block missing in preview response"
    assert img_block["mimeType"] == "image/jpeg"
    # Ensure base64 can be decoded into valid JPEG bytes
    raw_img = base64.b64decode(img_block["data"])
    assert raw_img[:2] == b"\xff\xd8"  # JPEG SOI marker

    # Update draft with valid patch
    up_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 45,
        "method": "tools/call",
        "params": {
            "name": "mfilm_update_draft",
            "arguments": {
                "draft_id": d1_id,
                "expected_revision": 1,
                "patch": {"tone": {"brightness": 0.5}}
            }
        }
    })
    assert not up_res["result"].get("isError")
    assert up_res["result"]["structuredContent"]["revision"] == 2

    # A05: Update with stale revision -> CONFLICT_REVISION
    stale_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 46,
        "method": "tools/call",
        "params": {
            "name": "mfilm_update_draft",
            "arguments": {
                "draft_id": d1_id,
                "expected_revision": 1,  # Stale! Current revision is 2
                "patch": {"tone": {"brightness": 1.0}}
            }
        }
    })
    assert stale_res["result"].get("isError") is True
    assert stale_res["result"]["structuredContent"]["error_code"] == "CONFLICT_REVISION"

    # A16: Compare 2 drafts
    comp_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 47,
        "method": "tools/call",
        "params": {"name": "mfilm_compare_drafts", "arguments": {"draft_ids": [d1_id, d2_id], "max_side": 512}}
    })
    assert not comp_res["result"].get("isError")
    comp_images = [c for c in comp_res["result"]["content"] if c["type"] == "image"]
    assert len(comp_images) == 2, f"Expected 2 image blocks, got {len(comp_images)}"


def test_a03_unknown_profile_validation_error(mcp_server, bus):
    """A03: Unknown profile or invalid parameter returns clean validation error."""
    conn = bus.get_connection()
    conn.execute(
        "INSERT INTO sources (id, sha256, origin, filename, format, bytes, path) VALUES (?, ?, 'upload', 'a.dng', 'dng', 100, 'a.dng')",
        ("up_s1", "0" * 64)
    )
    conn.close()

    res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 50,
        "method": "tools/call",
        "params": {
            "name": "mfilm_create_draft",
            "arguments": {
                "asset_id": "up_s1",
                "recipe": {
                    "schema_version": 2,
                    "camera_look": {"id": "nonexistent_look", "version": "1", "strength": 1.0},
                    "film": {"stock": "portra400", "version": "1", "strength": 1.0}
                }
            }
        }
    })
    assert res["result"].get("isError") is True
    assert res["result"]["structuredContent"]["error_code"] in ("RECIPE_INVALID", "UNKNOWN_PROFILE")


@needs_dng
def test_a07_idempotent_development_job(mcp_server, bus, store):
    """A07: Queue develop job with idempotency key."""
    import hashlib
    dng_data = DNG.read_bytes()
    sha = hashlib.sha256(dng_data).hexdigest()
    sources_dir = store.root / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    dng_dest = sources_dir / "job_test.dng"
    dng_dest.write_bytes(dng_data)

    conn = bus.get_connection()
    conn.execute(
        "INSERT INTO sources (id, sha256, origin, filename, format, bytes, path, eligible, meta) VALUES (?, ?, 'upload', 'job_test.dng', 'dng', ?, 'job_test.dng', 1, '{}')",
        ("up_job1", sha, len(dng_data))
    )
    conn.close()

    d_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 60,
        "method": "tools/call",
        "params": {"name": "mfilm_create_draft", "arguments": {"asset_id": "up_job1"}}
    })
    draft_id = d_res["result"]["structuredContent"]["draft_id"]

    # Start develop 1st time
    j1 = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 61,
        "method": "tools/call",
        "params": {
            "name": "mfilm_start_development",
            "arguments": {
                "draft_id": draft_id,
                "revision": 1,
                "idempotency_key": "idempotent-key-12345"
            }
        }
    })
    assert not j1["result"].get("isError")
    job_id1 = j1["result"]["structuredContent"]["job_id"]

    # Start develop 2nd time with SAME idempotency key (A07)
    j2 = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 62,
        "method": "tools/call",
        "params": {
            "name": "mfilm_start_development",
            "arguments": {
                "draft_id": draft_id,
                "revision": 1,
                "idempotency_key": "idempotent-key-12345"
            }
        }
    })
    assert not j2["result"].get("isError")
    job_id2 = j2["result"]["structuredContent"]["job_id"]
    assert job_id1 == job_id2, "Same idempotency key must return the same job ID"

    # Get job status
    st_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 63,
        "method": "tools/call",
        "params": {"name": "mfilm_get_job", "arguments": {"job_id": job_id1}}
    })
    assert not st_res["result"].get("isError")
    assert st_res["result"]["structuredContent"]["job_id"] == job_id1

    # Cancel job
    can_res = mcp_server.handle_request({
        "jsonrpc": "2.0",
        "id": 64,
        "method": "tools/call",
        "params": {"name": "mfilm_cancel_job", "arguments": {"job_id": job_id1}}
    })
    assert not can_res["result"].get("isError")


def test_stdio_protocol_runner(mcp_server):
    """Test stdio JSON-RPC stream loop with string streams."""
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "mfilm_status", "arguments": {}}}),
    ]
    inp = io.StringIO("\n".join(lines) + "\n")
    out = io.StringIO()

    run_stdio_server(mcp_server, in_stream=inp, out_stream=out)

    out_lines = [json.loads(l) for l in out.getvalue().strip().splitlines() if l.strip()]
    assert len(out_lines) == 3
    assert out_lines[0]["id"] == 1
    assert out_lines[1]["id"] == 2
    assert out_lines[2]["id"] == 3
    assert out_lines[2]["result"]["structuredContent"]["service_health"] == "OK"
