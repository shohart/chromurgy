# 04. Preset Data Model

## Overview

A Creative Color Grade preset must be a structured, machine-readable preset object.

It must not be stored as a single opaque binary blob.

## Required fields

- `id`
- `name`
- `version`
- `description`
- `category`
- `tags`
- `provenance`
- `parameters`
- `enabled`

## Parameter groups

### 1. Global tone controls

- exposure offset (optional)
- contrast
- black point lift
- white point compression
- micro contrast (optional)
- clarity bias (optional)

### 2. Tone curve

Support:

- RGB master curve
- optional per-channel curves
- S-curve presets
- lifted black floor
- softened highlight shoulder

### 3. Split toning / color wheels

At minimum:

- shadow hue
- shadow saturation
- midtone hue
- midtone saturation
- highlight hue
- highlight saturation
- balance parameter

### 4. HSL adjustments

At minimum support per-color family adjustments for:

- hue
- saturation
- luminance

Recommended families:

- red
- orange
- yellow
- green
- aqua
- blue
- purple
- magenta

### 5. Selective skin-preservation bias

Optional but strongly recommended.

This can be implemented as:

- softer saturation reduction in orange/red channels,
- protective skin luminance handling,
- or a bounded skin-tone adjustment strategy.

### 6. Matte / fade controls

Explicit support for:

- black lift amount
- shadow flattening
- shadow desaturation
- highlight softening

### 7. Vibrance / saturation shaping

Support both:

- global saturation
- vibrance-like protected saturation control

## Tags

`tags` must be a string array.

Examples:

- `["VSCO", "Matte", "Warm", "Portrait"]`
- `["Instagram Classics", "Faded", "Pastel", "Vintage"]`

## Provenance field

The `provenance` object should capture whether the preset is:

- `original`
- `community-inspired`
- `editorial-inspired`
- `instagram-classics-inspired`
- `vsco-inspired`
- `internal-experimental`

This is useful for future curation and UI filtering.

## Recipe embedding

The existing render recipe must be extended with a new optional block:

```json
{
  "creative_color_grade": {
    "enabled": true,
    "preset_id": "warm-muted-matte",
    "overrides": {
      "global_saturation": -0.12,
      "black_lift": 0.08
    }
  }
}
```

The `overrides` object allows a preset to be chosen first and then locally modified without mutating the original preset definition.

## Version 1.1 — Frame-specific selection

The previous `creative_color_grade` recipe block remains the global selection. Persist sparse `frame_color_grade_overrides`, keyed by immutable frame IDs, with exactly two explicit override forms: `mode: preset` (with optional grade parameter overrides) or `mode: none`. A missing frame entry means **inherit current global selection**. See `docs/08-frame-level-overrides.md` and the machine-readable schema in `contracts/frame-color-grade-overrides.schema.json`. The `Individual` tag signifies override scope, not a style tag such as VSCO or Instagram Classics.
