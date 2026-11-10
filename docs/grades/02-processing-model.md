# 02. Processing Model

## Placement in render pipeline

The Creative Color Grades module must be implemented as a structured stage inside the existing server render pipeline.

Recommended logical order:

1. Source ingest (`RAW`, `DNG`, `NEF`, `JPEG`, `TIFF`)
2. Decode and normalize
3. White balance / exposure normalization
4. Camera calibration / Camera Look
5. Film Stock rendering
6. **Creative Color Grade**
7. Optical Effects
8. Output transform / sharpening / export

This is the preferred conceptual order. Minor internal rearrangements are allowed if technically justified.

## Why this order

Creative Color Grades should act on an already interpretable image, not on raw mosaic data.

They should:

- refine mood,
- shape tonal atmosphere,
- bias color relationships,
- lift or deepen blacks,
- alter highlight warmth or shadow tint,
- reduce or reshape saturation,
- create “matte”, “faded”, “muted”, or “editorial” character.

Optical Effects should remain separate because they simulate light behavior or lens artifacts rather than color intent.

## Preview parity

The preview renderer and the full-resolution renderer must use the same grade logic and the same parameter model.

The preview may operate on a smaller image, but must not use a different artistic transform.

## Determinism

The Creative Color Grade stage must be deterministic.

If the same input and recipe are rendered twice with the same engine version, the result must be visually stable and numerically close.
