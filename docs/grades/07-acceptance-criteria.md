# 07. Acceptance Criteria

## Functional acceptance

The module is accepted when:

1. The server can list available color grade presets.
2. The preset catalog contains at least 16 curated presets.
3. Presets can be filtered by tags including `VSCO` and `Instagram Classics`.
4. A preset can be previewed on a source image.
5. A preset can be embedded into a render recipe.
6. A preset can be adjusted via overrides.
7. A full-resolution final render can be produced.
8. The result can be published to PhotoPrism through the existing workflow.
9. User-defined presets can be created and saved.
10. Existing recipes without `creative_color_grade` continue to work unchanged.

## Quality acceptance

The module is accepted only if:

1. Preview and final render are visually aligned.
2. Presets are visibly distinct from each other.
3. Matte presets actually lift blacks and soften contrast.
4. Warm presets shift highlights and mids perceptibly warmer.
5. Moody presets meaningfully suppress or reshape color response.
6. Skin tones remain visually plausible in portrait-oriented presets.
7. Batch rendering remains deterministic.

## Technical acceptance

1. Schema validation is enforced.
2. Invalid tags are rejected or normalized according to documented rules.
3. Preset IDs are unique and stable.
4. All preset definitions are versioned.
5. Server logs and render history record the selected grade preset and overrides.
6. Tests cover recipe serialization and backward compatibility.

## Version 1.1 — Mandatory frame-level acceptance

The module is not accepted until all AC-01 through AC-20 in `docs/09-frame-api-and-test-matrix.md` pass, including correct inherited labels, per-frame `Individual` tag, explicit `None`, global-vs-frame precedence, saved settings, preview/final parity, PhotoPrism export, older recipe compatibility and concurrent session protection.
