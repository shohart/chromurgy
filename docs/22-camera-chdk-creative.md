# 22 — CHDK Integration for Creative Looks: Required Metadata, Experimental Rendering

## Target and scope

Target Canon PowerShot SX510 HS, DIGIC 4, CHDK ALPHA port. **Do not presume the camera has resources to reproduce Linux optical effects.** Existing CHDK firmware, RAW capture, filesystem, button interception, graphics/UI, memory management and Wi-Fi transport must all be validated on the real device and exact firmware revision. Full creative processing is **not a launch-blocking device requirement**.

## Device feature matrix

| Feature | Target | Required evidence |
|---|---|---|
| Selection of Camera Look ID | MUST once CHDK UI is functional | on-camera UI screenshot, restart persistence |
| Selection of film + optics + strengths | MUST | serialized canonical v2 recipe, id and valid ranges |
| Lock roll recipe at start | MUST | each frame/roll manifest has snapshot or linked immutable recipe hash |
| Store/send recipes with RAW | MUST | round trip Linux import and replay results |
| Show unavailable local effects correctly | MUST | explicit “Server rendering required” and display applied stages |
| Render simplified Camera Look (tone/3D LUT) | EXPERIMENT | benchmark RAM/CPU, quality comparison, crash recovery |
| Render small bloom/HDF on camera | EXPERIMENT | memory and heat/battery benchmarks; tests on real camera |
| Render all 12MP layers locally | NOT ASSUMED | can only be accepted after actual demonstrated device tests |
| Native Wi-Fi arbitrary file transport | UNVERIFIED | network call validation; no firmware flash or guessed addresses |

## User workflow

- Set profile for roll on small screen; show concise `Look / Film / Optical` summary and strength percent; allow preset templates to avoid complex menu navigation.
- Keep shot-preview lock and roll workflow of v0.3. Never run image processing on the capture critical path.
- Upon `Develop Offline`, determine supported local stages. If only film stage is available, warn before starting and label rendition `film_only_offline`; retain original full recipe in roll manifest for later Linux development.
- A partial offline rendition must not advance full `server_developed` status; after sync host still generates full creative rendition from original.
- On reconnect, camera receives server outputs and can display selected final rendition in developed-only gallery if gallery integration is feasible.

## Storage contract

Store at minimum `recipe_schema_version`, `camera_look_id`, `camera_look_strength`, `film_profile_id`, `optical_preset_id`, `optical_strength`, exact `optical_stack` if used, `recipe_hash`, `bundle_versions`, `captured_at`, `roll_id`, `frame_id`. Store selection with roll even if local render engine ignores some effects; never delete unsupported fields on import/export.

Use frozen preset resolution: **resolve preset references to full parameters at time of roll creation**. Do not allow remote profile updates to silently change an already exposed roll. Retain an optional `preset_id` for UI labels.

On-device logging: capability report, selected recipe, local stage coverage (`skipped_stages`), free RAM, per-frame timing, error code, power-cycle recovery. Provide a diagnostic export in SD card for agent inspection.

## Experimental implementation protocol

1. Query existing CHDK C module and scripting API; build tiny prototype that stores a v2 recipe and reads it back safely.
2. Verify CHDK DNG capture and exact image dimensions, active crop and RAW bit depth.
3. Benchmark CPU-only 33³/17³ LUT lookup on small tile, then 720×480 preview and 5 MP processing; do not assume data or buffer fits.
4. Test low-cost optical approximation using downsampled bright mask + separable blur; measure peak RAM/CPU and SD I/O. Only then decide if optional development feature should ship.
5. Compare local render with Linux at matched input/output settings; use documented tolerances and mark stages omitted.
6. If system is unstable, stop camera creative rendering work and keep complete server-first workflow with metadata support.

## Safety

No Canon persistent firmware writes; no guessed ROM function calls or memory addresses; no untested module on user's primary SD card; avoid Linux POSIX assumptions on DryOS. Do not let experimental effects alter native RAW originals. Do not expose unsafe controls as enabled defaults.
