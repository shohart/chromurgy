# 08. Individual Frame-Level Creative Color Grades

**Status:** Mandatory server-side and Web Darkroom requirement.  
**Scope:** Only the existing **Creative Color Grades** module. Do not build a separate grading engine or change Camera Look, Film Stock, or Optical Effects behavior.

## 1. User-facing behavior

The Web Darkroom already contains a batch/roll-wide Creative Color Grades selector. The **Preview / Adjust** panel for each image MUST gain a **Creative Color Grade** dropdown.

- **Default:** The frame uses the grade selected in the main Creative Color Grades section. The dropdown visibly shows the inherited grade's **name**, e.g. `Warm Muted Matte — Inherited`, not a blank value. If the global grade is disabled, show `None — Inherited`.
- **Explicit frame choice:** Changing that dropdown to another grade makes an **individual override** for the active frame only. Show a prominent, small **`Individual`** tag beside the dropdown and an option **`Reset to Global`**. The global selection and all other frames remain unchanged.
- **No grade:** A user can choose `None` for an individual frame, disabling the color grade on that image even when a global grade is active. This is an explicit override, distinct from inheritance.
- **Restoration:** `Reset to Global` removes the override object and immediately restores the current global grade. No duplicate copy of global data is written to the frame.
- **Global changes:** When the user changes the main section's grade, every inheriting frame updates; frames explicitly overridden stay as they are. Per-frame `None` stays off.
- **Selection independence:** Switching to another image updates the dropdown and preview to that image's effective grade. It MUST NOT silently copy the previously selected image's individual grade.
- **Adjustment independence:** If a user modifies grade parameters within Preview / Adjust for a frame, the application MUST first create a frame-level override (copy-on-write of the **effective** grade) and show `Individual`. Global preset definitions and batch defaults must never be mutated by individual adjustments.
- **Clear override and undo:** Support `Reset to Global`, Undo/Redo and revision tracking for both preset selection and per-frame parameter adjustments using existing application mechanisms.

The `Individual` indicator is a **scope marker** for this frame's recipe. Do not confuse it with the preset style tags `VSCO` and `Instagram Classics`, and do not automatically create PhotoPrism labels for it. Both tag systems appear independently in the interface.

## 2. Required preview/adjust UI

Wire this into the **existing** Preview / Adjust panel; do not add a second editing screen.

```
Preview / Adjust — IMG_0042.NEF
----------------------------------------------------
Creative Color Grade   [ Warm Muted Matte — Inherited v ]
Style tags: VSCO · Matte · Portrait
[ Adjust grade ]
----------------------------------------------------
```

After choosing `Pastel Air` on this one image:

```
Preview / Adjust — IMG_0042.NEF
----------------------------------------------------
Creative Color Grade   [ Pastel Air v ]    [Individual]
Style tags: VSCO · Pastel · Editorial
[ Adjust grade ]              [ Reset to Global ]
----------------------------------------------------
```

Dropdown choices:
1. `Use Global: <current global grade name>` — **always first**, bound dynamically to the global state.
2. `None (this frame)` — explicit override disabling grading, unless global is already disabled and no override is needed.
3. Separator or heading: `All Color Grades`.
4. Searchable grade choices, with existing tags/categories filtering (`VSCO`, `Instagram Classics`, etc.) and curated presets.
5. User-created grades.

Use an explicit inheritance selector rather than representing inheritance with the globally selected preset ID: choosing a preset with the same name as the global selection is still a distinct explicit override if the user intentionally sets it. The UI may offer `Reset to Global` for clarity.

Interaction and feedback:
- Apply selection to the active frame with an immediate preview invalidation and a debounced preview render.
- Show loading/progress without blocking edits on other images.
- Cancel/suppress stale preview responses when the user changes selection rapidly.
- Preserve the override when navigating forward/backward, reloading the browser, restarting a job, and switching from preview to final render.
- Provide a visible individual-override marker on the frame thumbnail or filmstrip for discoverability.
- The tag should remain readable without relying solely on color.
- Batch application of a new global grade must offer **`Preserve individual overrides` (default)** and **`Reset all individual overrides` (explicit confirmation)**.

## 3. State model: inherit vs preset vs none

The canonical recipe MUST contain a **global** default and a sparse map of frame-specific overrides keyed by an immutable frame identifier. File names must not be used as the primary keys.

Use these three states:

- **INHERIT:** no entry in the frame override map (or explicitly `mode: inherit` if needed for transport); resolves to the current global grade.
- **PRESET:** `{mode: "preset", preset_id, preset_version, overrides}`; resolves to that frame's selected base preset plus parameter edits.
- **NONE:** `{mode: "none"}`; grading is disabled for that frame, regardless of global selection.

Persist the *semantic* override state. Do not save a rendered image alone as the authoritative record of an override.

### Precedence and resolution

For frame `F`:

1. If its override state is `none`, disable Creative Color Grade for `F`.
2. If `preset`, resolve the pinned preset definition and apply **frame-local** parameter overrides.
3. If no override, resolve the current **global** grade and its global parameter overrides.
4. If global grade is off and there is no frame override, grading is disabled.

`EffectiveRecipe(F) = Merge(existing_render_recipe_without_grade, EffectiveCreativeGrade(F))`.

The rest of the M-Film recipe remains unchanged and continues using the established precedence rules for other components.

### Stable frame identity

A frame ID comes from the current system's persistent photo/frame ID (for PhotoPrism, prefer an internal mapping to the PhotoPrism photo UID rather than using a display filename). Keep it stable across renames and normal navigation. The same source shown in multiple rolls/jobs must be scoped appropriately to the relevant **batch/roll ID** and recipe version.

### Versioning and frozen renders

- Keep existing `render-recipe-v2` compatible: adding the optional `creative_color_grade` and `frame_color_grade_overrides` fields must not break old recipes.
- Pin `preset_id` **and** a resolved preset version (or content hash) at job submission.
- Persist the fully resolved effective grade per frame in each **render job snapshot**, alongside the originating global/frame selection, so queued jobs never change because the user edits the batch afterward.
- Preserve the source SHA-256, engine version, output settings and effective recipe hash in render history.
- A frame override MUST survive PhotoPrism publication and be recoverable from M-Film job history or its metadata sidecar.

## 4. Preview and final render parity

The preview MUST render the **effective frame grade** by the exact same grading algorithm as the full-resolution renderer. Only resolution and explicitly documented quality-related settings may differ. Do not silently use the global grade on final render.

Preview cache key (conceptual):
`source_sha256 + effective_grade_hash + full_recipe_hash + engine_version + preview_geometry + color_space + preview_quality`

- Changing global grade invalidates cache for inheriting frames only (other stages permitting).
- Changing one frame's grade invalidates its own affected preview only.
- Preview and final should report the same `effective_grade` in metadata/diagnostics.
- If color grading is disabled for a frame, the optical effects and film stock stages continue as usual.
- Respect existing color-management, stage ordering, and batch job scheduling.

## 5. Edge cases

- **Deleted system preset:** prevent deleting built-in presets; pin job snapshots. When a user preset is deleted, existing jobs continue from snapshots; editable recipes show `Missing preset` and offer recovery, never silently fall back to a different look.
- **Global preset updated:** inheriting frames follow the selected global definition on new previews; previously submitted render jobs remain pinned. Individual overrides follow the pinned version or explicit user migration rules.
- **Duplicate filename:** use stable frame identifiers.
- **Import older recipes:** absence of override map means all frames inherit the global grade (or off if no global grade).
- **Unsupported preset:** return a typed error identifying the frame and preset without affecting other frames; job failure policy should remain existing batch policy.
- **Keyboard/assistive tech:** label dropdown, inherited/individual state, and reset action; all operable without a mouse.
- **Concurrency:** use optimistic recipe revision or equivalent; do not lose a per-frame edit when another tab edits the global preset.
- **Multi-selection:** selecting a grade for multiple explicitly selected frames is allowed only through an intentional bulk action; the ordinary Preview / Adjust dropdown affects exactly one frame.
- **Per-frame previews of RAW/NEF/DNG:** selection uses current source asset; never overwrite original.

## 6. Constraints

This is not an additional layer that stacks multiple Creative Color Grades; each frame resolves to **one** grade selection, plus its parameters, within the existing stage. Existing Camera Look, Film Stock, Optical Effects and their combinations remain independent.
