# 05. API and Workflows

## Required API capabilities

The server must expose Creative Color Grade functionality through its existing API.

### Required endpoints

1. `GET /api/v1/color-grades`
   - list presets
   - support filtering by tag, category, and search query

2. `GET /api/v1/color-grades/{id}`
   - return full preset definition

3. `POST /api/v1/color-grades/preview`
   - render a preview for a source image and grade recipe

4. `POST /api/v1/color-grades/render`
   - queue a full-resolution render job using a color grade

5. `POST /api/v1/color-grades`
   - create a user preset

6. `PUT /api/v1/color-grades/{id}`
   - update a user preset

7. `DELETE /api/v1/color-grades/{id}`
   - remove a user preset

8. `POST /api/v1/color-grades/duplicate/{id}`
   - clone an existing preset as a user-editable preset

## Required UI workflow

The Web Darkroom must expose a dedicated section:

### Creative Color Grades

The user flow should be:

1. open image or batch,
2. select Camera Look,
3. select Film Stock,
4. open Creative Color Grades,
5. browse or filter presets,
6. preview a preset,
7. adjust parameters,
8. optionally save custom preset,
9. run final full-resolution render,
10. optionally publish result to PhotoPrism.

## Preview behavior

Preview must support:

- quick preset switching,
- side-by-side comparison,
- before/after toggle,
- recipe persistence,
- deterministic results.

## Batch behavior

For batch workflows, the API must allow:

- applying one grade preset to a batch,
- applying one grade preset with per-image overrides,
- rendering all results into a chosen PhotoPrism destination.

## Version 1.1 — Per-frame Preview / Adjust dropdown

Add a Creative Color Grade selector to the existing Preview / Adjust block. Default shows the name of the current global grade marked `Inherited`. A user's change creates a frame-local override (`Individual` tag), applies it to preview **and full render**, and saves it in the batch recipe. `None (this frame)` disables grading only for that image. `Reset to Global` deletes the override. Global changes must preserve individual overrides by default. Extend existing job/frame API; detailed routes and end-to-end cases are in `docs/09-frame-api-and-test-matrix.md`.
