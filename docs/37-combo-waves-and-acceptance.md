# 37 — Combo Presets: Integration Waves, API, Web UI and Acceptance

**Assignment:** Linux server only. Extend established M-Film Web Darkroom and current Optical Effects stack. No CHDK tasks, no second renderer, no new external hosted dependency.

## Mandatory waves (in lock-step with v0.6)

- **Wave 1**: 13 initial combo(s), activated only if linked effects and film stocks are implemented and tests pass.
- **Wave 2**: 3 initial combo(s), activated only if linked effects and film stocks are implemented and tests pass.
- **Wave 3**: 2 initial combo(s), activated only if linked effects and film stocks are implemented and tests pass.
- **Wave 5**: 2 initial combo(s), activated only if linked effects and film stocks are implemented and tests pass.
- **Wave 10**: 1 initial combo(s), activated only if linked effects and film stocks are implemented and tests pass.

### Wave 1 — Catalog + established effects + vignette

- Implement catalog loader, JSON-schema/type validation, source metadata, stable preset IDs/revisions and legacy ID-preserving import.
- Implement `GET /api/v1/creative/presets` filterable by `scene`, `category`, `available`, `wave`; `GET /api/v1/creative/presets/{id}` for details and resolved recipe. Names are proposed route contracts: **reuse existing endpoints** if they already provide this function; no duplicate endpoint families.
- Implement `POST /api/v1/creative/presets/{id}/resolve` accepting selected RAW ID, user overrides and seed, returning immutable canonical `render-recipe-v2` (or explicit unavailable dependencies). Validate against the existing v2 schema.
- Add Suggested Combos cards to the **existing** editing view and preserve all individual selectors. No new stage. User can save personal versions and return to manual selection.
- Release basic portrait, Gold/Classic Negative, Tri-X, Ricoh HDF and existing-effects combos only after visual review.

### Wave 2 — Detected highlight effects

- Make source-driven Ghosts, Starburst and mixed HDF/Starburst presets available when operators are shipped and tested.
- Preview overlays may mark detected point sources and expose normalized manual overrides; arbitrary random flare placement is a failure.
- Verify no-op for images with no relevant source and scaling invariance between preview and final.

### Wave 3 — Cinema and nostalgic artifacts

- Activate Anamorphic Streak and Analog Light Leaks combos.
- Deterministic RNG seed stable across retries; preserve luminance and dominant composition; light leaks remain deliberately optional.
- Night looks must preserve distinct red film halation vs blue streak; do not double-render CineStill halation.

### Wave 5 — Compound optics and selective focus

- Activate Superia Vintage Glass only after barrel warp, CA and edge softness are all real, tested operators.
- Activate Sweet Spot Floral after focus-point dragging, background transition and edge artifacts have been verified.
- Missing film alias => explicitly 'Unavailable', not 'Ready'.

### Wave 10 — Miniature look + full catalog release

- Activate Miniature Rooftops and audit all other combinations against actual production server, PhotoPrism and RAW/NEF/DNG workflows.
- Produce 21 before/after contact sheets, 21 side-by-side preview-vs-final samples, per-preset time and peak memory metrics, user-facing scene suggestions, and final migration report.

## Web acceptance criteria

1. Browse all 21 cards **in the existing Web Darkroom** with wave/availability/evidence indicators and search by scene. Default ordering promotes general-purpose presets over experiments.
2. Selecting a card populates Camera Look, Film Stock and all optical.stack parameters. The user may modify any stage without losing source selection or PhotoPrism album/destination.
3. With the same input + pinned recipe version + seed, multiple preview calls produce the same artistic decisions (normalized flare positions and leak layout). Preview and final may differ in sampling detail but not in random style choices.
4. `none` film is valid and explicit. Unsupported film IDs, unimplemented effects, invalid numeric ranges or missing RAW are visible validation errors. No generic film substitution.
5. Source RGB and final full-resolution output both use verified RAW decode and the production render graph; the preview is a reduced actual render, not a separate CSS filter.
6. All 21 presets resolve through the same backend used for an individual custom recipe; no separate effect engine or preset-specific renderer branches.
7. Saved personal preset has a private owner, immutable version, provenance link to base preset and editable overrides; historical jobs remain reproducible after default values change.
8. PhotoPrism publication takes the generated rendition and maps to the independently selected folder/album; verify no silent original replacement and no duplicate albums on retry.
9. All existing v0.6 manual recipes, 12 legacy camera composites and six original optical effects keep exact render behaviour for archived recipes.
10. An implementation report shows actual tested RAW fixture names, commands, sample output files and PASS/FAIL/BLOCKED. Catalog metadata alone **does not count as implemented**.

## Service integration tests

- Catalog schema + unique ID + source link integrity + operator availability + valid wave dependency.
- Preset resolve → schema-valid recipe → preview → final → PhotoPrism publication → job/preset provenance round trip.
- Source-candidate with no highlight → no flare/star/streak; subject behind normalized masks remains unchanged where expected.
- Preview vs final source coordinate consistency, fixed random leakage map and no tile seams.
- Golden Haze legacy preset reproducibility; nonexistent film alias returns a clear blocking error.
- Black-and-white Tri-X recipe keeps achromatic output and does not apply colorful CCD emulation after B&W conversion.
- Multi-effect blend, bloom/halation de-duplication, highlight clipping, dark shadow chroma and skin gamut checks.
- Performance: 12MP/24MP/45MP RAW fixture set; per-preset p50/p95 and peak RSS; cache keys include source checksum, expanded recipe, model/operator versions and seed.

## Rollout/gating detail

Expose `available`, `blocked_reason`, `operator_versions`, `source_evidence`, `render_validation_state` from the real service registry. Presets are **disabled with explicit reasons** until dependencies and visual validation pass; not silently substituted. A server build can include the entire curated YAML from Day 1, while progressively activating its cards in the specified waves. Last mandatory wave is Wave 10, never silently deferred.
