# 06. Rollout Plan

## Phase 1 — Core model

Implement:

- grade preset schema
- recipe integration
- preset catalog loader
- validation
- server persistence for user presets

## Phase 2 — Core rendering

Implement:

- tone curve engine
- split toning / color wheel engine
- HSL adjustment engine
- matte / fade controls
- saturation/vibrance shaping

## Phase 3 — Preset catalog

Ship starter catalog of at least 16 presets from the specification.

Each preset must:

- validate against schema
- have tag metadata
- produce visually distinct output
- include provenance notes

## Phase 4 — Preview and UI

Implement:

- preset browser
- tag filters
- search
- preview endpoint
- before/after comparison
- duplicate and edit workflow

## Phase 5 — Full render + PhotoPrism

Implement:

- full-resolution render using grade recipes
- batch rendering
- PhotoPrism publication support
- metadata persistence in render history

## Phase 6 — Stabilization

Implement:

- regression tests
- numerical consistency checks
- user preset import/export
- recipe compatibility tests
- performance tuning

## Version 1.1 — Follow-on phase: per-frame overrides

Once the global preset catalog and grade renderer are functional: implement stable frame identities and sparse overrides; wire Preview / Adjust dropdown and scope tag; provide server resolution and persistence; integrate preview and full render snapshots; confirm PhotoPrism publication; run AC-01 through AC-20. Do not mark the new color grading module complete until these are tested.
