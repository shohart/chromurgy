# 23 — Render Recipe v2, API and Migration Contract

**Deliverables:** versioned JSON Schema; canonical recipe serializer; CLI parsing; an endpoint for look and effect discovery; migration from existing v1 roll recipes; PhotoPrism sidecar provenance. See [`render-recipe-v2.schema.json`](../contracts/render-recipe-v2.schema.json) and [`render-recipe-v2.example.json`](../contracts/render-recipe-v2.example.json).

## Core recipe fields

```json
{
  "schema_version": 2,
  "preset_id": "leica-m9-portra-sun-v1",
  "camera_look": {"id":"leica_m9_ccd","version":"1.0.0","strength":0.8},
  "film": {"id":"kodak-portra-400","bundle_hash":"<actual SHA-256>"},
  "optical": {"preset_id":"soft_sun_glow","strength":0.45,
    "stack":[{"id":"soft_sun_glow","enabled":true,"parameters":{"radius_fraction":0.012,"threshold":1.0,"knee":0.25}}]},
  "render": {"output_format":"jpeg","output_color_space":"srgb","quality":92},
  "seed": 0
}
```

Example above shows intended structure, but source files under `contracts/` are the machine-readable normative examples. Optical threshold is defined on normalized scene-linear exposure where neutral gray convention and white point are fixed; document value meanings alongside code defaults.

`strength=0.0` is an exact bypass. A preset is a **recipe template**, not a mutable external dependency; expand it before accepting a roll. If a field is unknown and not namespaced to `extensions`, fail explicitly instead of dropping it.

## Legacy migration

v1 recipe has `film_profile_id` and `look_controls` but no target Camera Look. It must map to v2 `{camera_look: neutral/0.0, optical: none/0.0, film: original film_profile_id}`. Preserve old M-Film film halation/softness controls; do not map them silently to new `optical` presets. Keep v1 read support in API for stored rolls; all new writes use v2.

## API/CLI (host)

Implement:

- `GET /api/v1/creative/camera-looks` — id, label, evidence tier, version, status, supported controls.
- `GET /api/v1/creative/optical-effects` — id, name, parameter schema, default, allowable strength.
- `GET /api/v1/creative/presets` — fully versioned combinations.
- `POST /api/v1/renders` — source/roll/frame reference + canonical v2 recipe; idempotent content-addressed job.
- `GET /api/v1/renders/{render_id}` — status, progress, applied/omitted stages, artifacts, errors.
- `POST /api/v1/renders/{render_id}/publish` — select version to expose in PhotoPrism; do not re-export if already published.

Versioned OpenAPI: extend `contracts/openapi.yaml` or produce merged `contracts/openapi-v2.yaml`; **do not break the v0.3 ingest/sync routes**. Return structured 400 for invalid recipes, 404 for unknown assets, 409 for locked or incompatible versions, 422 for unsupported effect/profile combo, 503 for temporary work queue saturation.

CLI examples:

```bash
mfilm-develop --input RAW.DNG --film kodak-portra-400 --camera-look leica_m9_ccd \
  --camera-look-strength 0.8 --optical-preset soft_sun_glow \
  --optical-strength 0.45 --output IMG_0001.jpg
mfilm-develop --input RAW.DNG --recipe contracts/render-recipe-v2.example.json \
  --output IMG_0001.jpg --provenance IMG_0001.json
mfilmctl rerender --roll ROLL_001 --preset golden_haze --select-default
```

## Provenance and storage

Each output sidecar must include: original DNG SHA-256; canonical recipe hash; full resolved recipe; camera calibration ID; M-Film film bundle revision; camera-look params hash and evidence tier; optical engine version; processing order ID; module versions; actual rendered stages; output size/ICC; result SHA-256; elapsed stage times. PhotoPrism should get human-friendly EXIF/IPTC/XMP tags **when safely supported**; sidecar remains the authoritative record.

`render_id` must include source digest, exact expanded recipe, code/profile revisions and output spec. Re-rendering makes a new object, not an overwritten file. User-selected publish-default is a separate pointer, not part of image content identity.

## Synchronization

CHDK or SD manifest transfers complete v2 recipe even if local renderer cannot execute it. Server resolves and validates compatibility, receives RAW, renders full recipe, stores output and optionally returns preview/final JPEG. Local partially processed image is a separate rendition whose metadata shows omitted stages.

## v0.6 in-place recipe-v2 additive fields (Linux only)

Maintain `schema_version: 2` and existing `optical.stack[]` item shape; expand `maxItems` 8→16. Add optional `optical.vignette_policy`, per-effect `source_selection`, `mask` and `implementation_version`; permit typed enum settings in the existing `parameters` while preserving numeric parameters in old recipes. Enforce parameter names/types/ranges against [one unified optical registry](../contracts/optical-effects-catalog.yaml), not by accepting arbitrary keys. New optical IDs and component IDs are listed in [21](21-optical-effects.md); **none replaces the original six**. Old recipe samples must validate unchanged and yield pinned historical output. See [example](../contracts/render-recipe-v2.optics-example.json).
