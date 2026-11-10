# MCP Gap and Inventory Report (Wave 0)

**Date:** 2026-11-10  
**Project:** Chromurgy / M-Film Web Darkroom v0.8  
**Scope:** Server-side Model Context Protocol (MCP) integration  

---

## 1. Executive Summary

This report completes Wave 0 of the MCP integration specification (`docs/43-mcp-phased-rollout-and-acceptance.md`). It inventories existing M-Film backend services, compares proposed OpenAPI specifications against actual implemented routes, details domain service facades, and defines the unified command bus (`MFilmCommandBus`) used by both Web Darkroom and MCP.

---

## 2. Existing Backend Inventory

| Component | Implementation File | Status | Notes |
|---|---|---|---|
| **Storage & Store** | `mfilm_server/store.py` | `VERIFIED` | Root paths: `sources/`, `web-previews/`, `bundles/`, `incoming/`, `exports/`. |
| **Database Schema** | `mfilm_server/db.py` | `VERIFIED` | SQLite schema with 9 migrations (`devices`, `assets`, `rolls`, `frames`, `sources`, `web_renders`, `darkroom_jobs`, `darkroom_items`, `darkroom_presets`, `color_grade_presets`). |
| **Native Film Core** | `mfilm_server/core.py` | `VERIFIED` | C ABI binding for film profiles, grain, and LUT emulation. |
| **Camera Looks & Optics** | `mfilm_server/darkroom/creative.py`, `optics.py` | `VERIFIED` | 8 camera looks, 7 standalone optical effects + vintage glass + 6 legacy effects. |
| **Curated Combos** | `mfilm_server/darkroom/combos.py` | `VERIFIED` | 21 curated combination presets with provenance labels. |
| **Color Grades v1.1** | `mfilm_server/darkroom/grades.py`, `grades_catalog.py` | `VERIFIED` | 16 curated color grade presets with intensity amplification. |
| **Recipe v2 Validator** | `mfilm_server/darkroom/recipe2.py` | `VERIFIED` | Canonical `schema_version: 2`, hash computation, v2 -> v1 normalization. |
| **Preview Renderer** | `mfilm_server/darkroom/preview.py` | `VERIFIED` | Real multi-stage pipeline, in-memory caching, JPEG disk cache. |
| **Job Queue & Worker** | `mfilm_server/darkroom/jobs.py`, `worker.py`, `develop.py` | `VERIFIED` | Multi-process worker, SQLite job item state machine, retry and cancellation. |
| **PhotoPrism Connector** | `mfilm_server/darkroom/photoprism.py`, `pp_sources.py` | `VERIFIED` | Album/folder discovery, sync, original file path resolution. |
| **Publisher** | `mfilm_server/darkroom/publish.py`, `publisher.py` | `VERIFIED` | Sidecar generation, staged export, album indexing and linking. |

---

## 3. Route & API Gap Analysis

| Proposed MCP Tool | Existing Backend Route / Service | Adapter Strategy |
|---|---|---|
| `mfilm_status` | `GET /api/v1/darkroom/catalog`, `engine_info()`, config checks | In-process command bus method reading engine, store, and PhotoPrism readiness. |
| `mfilm_list_sources` | `GET /api/v1/darkroom/sources`, `sources.py` | Query `sources` table and active rolls; sanitize file paths. |
| `mfilm_search_assets` | `GET /api/v1/darkroom/sources`, `photoprism.py` | Filter `sources` table by origin (`upload`, `photoprism`, `camera_roll`), format, query. |
| `mfilm_inspect_asset` | `GET /api/v1/darkroom/sources/{asset_id}`, `analysis.py` | Return full source metadata, camera baseline EV, auto WB, dimensions. |
| `mfilm_list_creative_options` | `catalog.build_catalog()`, `combos.COMBOS`, `grades_catalog.GRADES` | Return Camera Looks, Film Stocks, Optical Effects, Combos, and Grades. |
| `mfilm_get_recipe_schema` | `contracts/render-recipe-v2.schema.json`, `creative_params.py` | Return authoritative schema dictionary. |
| `mfilm_list_photoprism_destinations` | `photoprism.list_albums()`, `photoprism.list_folders()` | Return writable albums and folders with permissions. |
| `mfilm_create_draft` | **NEW** (SQLite table `mcp_drafts`) | Persist versioned recipe draft with immutable `asset_id` and initial revision 1. |
| `mfilm_get_draft` | **NEW** (SQLite table `mcp_drafts`) | Retrieve draft recipe, revision, recipe hash. |
| `mfilm_update_draft` | **NEW** (SQLite table `mcp_drafts` + `recipe2.py`) | Validate RFC 7396 merge patch; check `expected_revision == revision`; increment revision. |
| `mfilm_render_preview` | `preview.render()`, `POST /api/v1/darkroom/previews` | Render using existing preview pipeline; encode JPEG/PNG to base64 MCP ImageContent. |
| `mfilm_compare_drafts` | **NEW** (batch preview via `preview.render()`) | Render 2-4 drafts; return individual labeled image blocks or grid. |
| `mfilm_start_development` | `jobs.create_job()`, `POST /api/v1/darkroom/jobs` | Enqueue durable development job in existing worker queue with `idempotency_key`. |
| `mfilm_get_job` | `jobs.job_view()`, `GET /api/v1/darkroom/jobs/{job_id}` | Read state, progress, and render outcome. |
| `mfilm_cancel_job` | `jobs.cancel()`, `POST /api/v1/darkroom/jobs/{job_id}/cancel` | Best-effort cancellation via existing cancellation flag. |
| `mfilm_publish_render` | `publish.publish_render()`, `POST /api/v1/darkroom/jobs/{id}/publish` | Execute publisher export to selected PhotoPrism destination. |

---

## 4. Architecture & Co-Location Decision

* **Architecture:** In-process domain service facade (`MFilmCommandBus`).
* **Tradeoff Evaluation:**
  * Direct co-located invocation avoids loopback HTTP latency, connection pooling overhead, and credential roundtrips.
  * Preserves single source of truth: validator (`recipe2.py`), renderer (`develop.py` / `preview.py`), and queue (`jobs.py`).
  * Enables stdio transport without requiring an active external browser session.
  * SQLite concurrency safely coordinates multiple accessors.

---

## 5. Wave 0 Exit Gate Verification

1. [x] Mapping from each proposed MCP tool to a real handler/service defined.
2. [x] Zero duplicate renderers or secondary catalogs created.
3. [x] Schema migration for `mcp_drafts` designed with optimistic locking.
