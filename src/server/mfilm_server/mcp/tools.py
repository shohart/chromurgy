# SPDX-License-Identifier: GPL-2.0-only
"""MCP Tool Registry and Schemas (contracts/mcp-tool-registry-v08.yaml)."""
from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "mfilm_status",
        "description": "Inspect deployed engine status, bundle hash, feature flags and asset/job counts.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_list_sources",
        "description": "Find authorized source containers (upload, photoprism, camera rolls).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["mfilm_library", "roll", "upload", "photoprism"]
                },
                "cursor": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50}
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_search_assets",
        "description": "Search actual asset catalog with metadata, camera model and format filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["mfilm_library", "roll", "upload", "photoprism", "all"]
                },
                "query": {"type": "string", "maxLength": 200},
                "album_uid": {"type": "string", "minLength": 1},
                "folder_id": {"type": "string", "minLength": 1},
                "camera_model": {"type": "string", "minLength": 1},
                "format": {
                    "type": "string",
                    "enum": ["nef", "dng", "cr2", "cr3", "arw", "raf", "jpeg", "tiff"]
                },
                "cursor": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50}
            },
            "required": ["source"],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_inspect_asset",
        "description": "Inspect one authorized RAW asset, returning metadata, baseline EV, auto WB and editing features.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "asset_id": {"type": "string", "minLength": 1}
            },
            "required": ["asset_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_list_creative_options",
        "description": "List installed Camera Looks, Film Stocks, Optical Effects, Curated Combos and Color Grades.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["camera_look", "film", "optical", "combo", "grade"]
                },
                "query": {"type": "string", "maxLength": 150},
                "cursor": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100}
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_get_recipe_schema",
        "description": "Expose authoritative Render Recipe v2 schema and valid parameters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schema_version": {"type": "integer", "enum": [2], "default": 2}
            },
            "required": [],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_list_photoprism_destinations",
        "description": "Find writable PhotoPrism manual albums and managed export folders.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string", "minLength": 1},
                "kind": {"type": "string", "enum": ["album", "folder"], "default": "album"},
                "query": {"type": "string", "maxLength": 150},
                "cursor": {"type": "string", "minLength": 1}
            },
            "required": ["kind"],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_create_draft",
        "description": "Create an editable versioned recipe draft for an existing RAW source.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "asset_id": {"type": "string", "minLength": 1},
                "preset_id": {"type": "string", "minLength": 1},
                "recipe": {"type": "object"}
            },
            "required": ["asset_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_get_draft",
        "description": "Inspect versioned recipe draft by draft ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "minLength": 1}
            },
            "required": ["draft_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_update_draft",
        "description": "Apply validated RFC 7396 merge patch to draft with optimistic concurrency check.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "minLength": 1},
                "expected_revision": {"type": "integer", "minimum": 1},
                "patch": {"type": "object", "minProperties": 1}
            },
            "required": ["draft_id", "expected_revision", "patch"],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_render_preview",
        "description": "Return actual rendered preview image as MCP image content (base64) and metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "minLength": 1},
                "revision": {"type": "integer", "minimum": 1},
                "max_side": {"type": "integer", "minimum": 128, "maximum": 1536, "default": 1024},
                "format": {"type": "string", "enum": ["png", "jpeg"], "default": "jpeg"}
            },
            "required": ["draft_id", "revision"],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_compare_drafts",
        "description": "Compare 2-4 versioned recipe drafts with rendered image previews.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_ids": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 4,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1}
                },
                "max_side": {"type": "integer", "minimum": 128, "maximum": 1536, "default": 720},
                "layout": {"type": "string", "enum": ["separate", "grid"], "default": "separate"}
            },
            "required": ["draft_ids"],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_start_development",
        "description": "Queue durable full-quality develop job in existing background worker queue.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "minLength": 1},
                "revision": {"type": "integer", "minimum": 1},
                "idempotency_key": {"type": "string", "minLength": 8, "maxLength": 128},
                "output": {
                    "type": "object",
                    "properties": {
                        "format": {"type": "string", "enum": ["jpeg", "tiff", "png"], "default": "jpeg"},
                        "quality": {"type": "integer", "minimum": 1, "maximum": 100, "default": 95}
                    },
                    "required": [],
                    "additionalProperties": False
                }
            },
            "required": ["draft_id", "revision", "idempotency_key"],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_get_job",
        "description": "Read state, progress and rendered output of a durable render job.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "minLength": 1}
            },
            "required": ["job_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_cancel_job",
        "description": "Cancel active or queued render job.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "minLength": 1}
            },
            "required": ["job_id"],
            "additionalProperties": False
        }
    },
    {
        "name": "mfilm_publish_render",
        "description": "Publish completed immutable render into authorized PhotoPrism album or folder.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "render_id": {"type": "string", "minLength": 1},
                "destination": {
                    "type": "object",
                    "properties": {
                        "instance_id": {"type": "string"},
                        "folder_id": {"type": "string", "minLength": 1},
                        "album_uid": {"type": "string"},
                        "create_missing_album": {"type": "boolean", "default": False}
                    },
                    "required": ["folder_id"],
                    "additionalProperties": False
                },
                "idempotency_key": {"type": "string", "minLength": 8, "maxLength": 128},
                "approval_token": {"type": "string"}
            },
            "required": ["render_id", "destination", "idempotency_key"],
            "additionalProperties": False
        }
    }
]


def get_tools_list() -> list[dict[str, Any]]:
    return TOOLS


def find_tool(name: str) -> dict[str, Any] | None:
    return next((t for t in TOOLS if t["name"] == name), None)
