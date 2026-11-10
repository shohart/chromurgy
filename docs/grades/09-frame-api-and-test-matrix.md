# 09. Per-Frame API, Rendering Contract and Acceptance Tests

## 1. Reuse existing service architecture

Extend existing recipe APIs if possible. The routes below are reference contracts, not a demand for a second parallel API. Respect current auth, job/roll identifiers, renderer queue and PhotoPrism adapter.

Suggested endpoints:

- `GET /api/v1/jobs/{job_id}/creative-color-grades` — global selection, frame override summary, revision.
- `PATCH /api/v1/jobs/{job_id}/creative-color-grade` — modify global selection, with default policy `preserve_frame_overrides`.
- `PUT /api/v1/jobs/{job_id}/frames/{frame_id}/creative-color-grade` — set `{mode:"preset",...}` or `{mode:"none"}` for this frame only.
- `DELETE /api/v1/jobs/{job_id}/frames/{frame_id}/creative-color-grade` — reset to global (delete override).
- `GET /api/v1/jobs/{job_id}/frames/{frame_id}/creative-color-grade/effective` — resolved grade for UI/diagnostics, with scope `inherited | individual`.
- `POST /api/v1/jobs/{job_id}/frames/{frame_id}/preview` — existing preview route; MUST resolve the effective grade.
- Existing `POST .../render` / batch processing — MUST snapshot grade selection independently for each frame.

Example patch body to set an individual override:

```json
{
  "mode": "preset",
  "preset_id": "pastel-air",
  "preset_version": "1.0.0",
  "overrides": { "global": { "black_lift": 0.12 } },
  "expected_revision": 8
}
```

Example effective selection response:

```json
{
  "frame_id": "frame-00042",
  "scope": "individual",
  "mode": "preset",
  "preset_id": "pastel-air",
  "preset_version": "1.0.0",
  "display_label": "Pastel Air",
  "style_tags": ["VSCO", "Pastel", "Editorial"],
  "effective_grade_hash": "sha256:example-placeholder",
  "revision": 9
}
```

For an inheriting frame, respond with `scope: "inherited"` and include the effective global name, ID, and tags, rather than just `null`.

## 2. Persistence and transactions

- Persist global and frame selections in the existing job/batch/roll recipe store.
- Validate frame IDs belong to the selected job and caller has access to both.
- Validate preset existence, version and overrides with the module schema; reject unknown parameters.
- Apply a single-frame change atomically (transaction and revision increment).
- Never mutate other frames' effective overrides.
- Rendering workers must consume an immutable job snapshot, not read a mutable browser/session state.
- Ensure changes and batch rendering are idempotent where applicable.
- UI success must follow server confirmation; show retry/error state if save fails.

## 3. MCP / agent compatibility

If the existing M-Film MCP adapter is installed, it must call the same APIs for:

- reading an effective frame grade;
- selecting an individual grade;
- resetting inheritance;
- previewing and rendering that frame.

Do **not** implement a separate MCP color-grading engine. Tool names and argument shapes should follow the existing MCP registry; this document introduces no requirement to change transport.

## 4. PhotoPrism integration

- Per-frame color grades must be included in individual output render metadata and history when publishing through the existing PhotoPrism workflow.
- User may send a whole roll where some frames use global grade, some individual presets, and some `None`; published JPEGs must reflect the effective per-frame choices.
- The `Individual` badge is a UI scope indicator. Do not automatically alter PhotoPrism album membership or create an unwanted tag for it.
- Preserve source references, destination album/folder choice and output naming rules already defined by the application.

## 5. Required end-to-end acceptance tests

**AC-01 Inheritance:** Set global `Warm Muted Matte`; open three frames. All dropdowns display `Warm Muted Matte — Inherited` and show matching effective grade in API.

**AC-02 Single override:** On frame B select `Pastel Air`. B displays `Individual`; frames A and C continue to inherit global; B preview changes without modifying A or C.

**AC-03 Global switch:** Change global to `Moody Earth Portrait`. A/C follow new global; B stays `Pastel Air`.

**AC-04 Explicit None:** Set C to `None (this frame)`. C is grade-disabled but retains Camera Look, Film Stock and Optical Effects; A/B unaffected.

**AC-05 Reset:** Choose `Reset to Global` for B; B becomes inherited `Moody Earth Portrait` and is no longer `Individual`.

**AC-06 Overrides from Adjust:** Editing grade parameters in B without explicitly selecting another preset creates a private frame override, without altering global preset definition.

**AC-07 Navigation:** Repeatedly switch A↔B↔C; each dropdown, tag and preview always match the active frame.

**AC-08 Reload:** Reload web page and restart server; override states and revisions are preserved.

**AC-09 Preview parity:** Per-frame preview and final export agree in grade identity and look within documented tolerances on representative NEF, DNG and JPEG inputs.

**AC-10 Batch output:** Render all three frames. Final outputs reflect three distinct effective grade choices; no frame uses a stale cached/global grade.

**AC-11 PhotoPrism:** Publish entire batch to selected album. Files reflect overrides, are indexed, and source originals remain unmodified.

**AC-12 Backward compatibility:** Load an older recipe with no override map. All frames inherit; existing optical effects and film looks behave identically to their prior versions.

**AC-13 Preset tags:** User can filter dropdown by `VSCO` or `Instagram Classics`; these style tags remain independent of `Individual` scope marker.

**AC-14 Rapid input:** Switch preset rapidly on one frame. Out-of-order responses cannot display an obsolete preview or save obsolete state.

**AC-15 Concurrency:** Two editor tabs modify global/frame state; conflict is detected and no override is silently lost.

**AC-16 Frozen render:** Queue batch render; then change global preset. Queued job still uses the immutable per-frame recipe snapshot taken when submitted.

**AC-17 Identical ID collisions:** Two images with the same filename in different PhotoPrism albums never share the same override by accident.

**AC-18 Explicit bulk reset:** Applying global with `preserve_frame_overrides` keeps exceptions. `Reset all individual overrides` requires confirmation and is reversible via history.

**AC-19 Accessibility:** Dropdown, state marker and reset control can be operated with keyboard and read by screen readers.

**AC-20 Image-independent validation:** Select a malformed or missing user preset; server reports targeted validation error and does not rewrite other frames' recipes.

## 6. Definition of done

Implementation is not complete unless:

1. Preview / Adjust visibly shows inherited global grade per frame and allows individual selection.
2. The `Individual` tag appears **only** for explicit per-frame overrides and is persisted.
3. Global edits affect only inheriting frames.
4. Frame edits affect only explicitly targeted frame(s).
5. Full-resolution rendering and PhotoPrism publishing use the exact effective frame selection.
6. The prior 16-color-grade catalog, `VSCO` / `Instagram Classics` tag filtering, and all previously available M-Film processing stages continue to function.
