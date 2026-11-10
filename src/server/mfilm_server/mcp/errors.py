# SPDX-License-Identifier: GPL-2.0-only
"""MCP error taxonomy and formatting (docs/39, docs/42)."""
from __future__ import annotations

from typing import Any


class McpDomainError(Exception):
    def __init__(self, code: str, detail: str = "", extra: dict[str, Any] | None = None):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.extra = extra or {}

    def to_mcp_response(self) -> dict[str, Any]:
        data = {
            "error_code": self.code,
            "detail": self.detail,
            **self.extra
        }
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Error [{self.code}]: {self.detail}" if self.detail else f"Error [{self.code}]"
                }
            ],
            "structuredContent": data,
            "isError": True
        }


class AssetNotFoundError(McpDomainError):
    def __init__(self, asset_id: str, detail: str = "Asset not found"):
        super().__init__("ASSET_NOT_FOUND", detail, {"asset_id": asset_id})


class UnsupportedRawError(McpDomainError):
    def __init__(self, detail: str = "Unsupported RAW format or unreadable file"):
        super().__init__("UNSUPPORTED_RAW", detail)


class UnknownProfileError(McpDomainError):
    def __init__(self, profile_id: str, kind: str = "profile"):
        super().__init__("UNKNOWN_PROFILE", f"Unknown {kind} '{profile_id}'", {"profile_id": profile_id, "kind": kind})


class RecipeInvalidError(McpDomainError):
    def __init__(self, detail: str, path: str = ""):
        super().__init__("RECIPE_INVALID", detail, {"path": path} if path else {})


class ConflictRevisionError(McpDomainError):
    def __init__(self, draft_id: str, expected: int, actual: int):
        super().__init__(
            "CONFLICT_REVISION",
            f"Draft revision mismatch: expected {expected}, actual revision is {actual}",
            {"draft_id": draft_id, "expected_revision": expected, "actual_revision": actual}
        )


class QuotaExceededError(McpDomainError):
    def __init__(self, detail: str = "Request quota or dimension limit exceeded"):
        super().__init__("QUOTA_EXCEEDED", detail)


class RenderFailedError(McpDomainError):
    def __init__(self, detail: str = "Rendering failed"):
        super().__init__("RENDER_FAILED", detail)


class JobUnknownError(McpDomainError):
    def __init__(self, job_id: str):
        super().__init__("JOB_UNKNOWN", f"Job '{job_id}' not found", {"job_id": job_id})


class PublishNotApprovedError(McpDomainError):
    def __init__(self, detail: str = "Publication requires explicit approval token or confirmation"):
        super().__init__("PUBLISH_NOT_APPROVED", detail)


class PhotoPrismUnavailableError(McpDomainError):
    def __init__(self, detail: str = "PhotoPrism service unreachable or unconfigured"):
        super().__init__("PHOTOPRISM_UNAVAILABLE", detail)
