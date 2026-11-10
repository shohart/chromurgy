# 01. Module Scope

## Goal

Create a dedicated **Creative Color Grades** layer for artistic color styling in the M-Film server-side darkroom.

This layer is intended for recognizable color aesthetics that are not fully described by either:

- the base camera response,
- the selected film stock,
- or optical effects.

Examples include:

- warm matte portrait looks,
- faded vintage looks,
- pastel editorial looks,
- moody earthy tones,
- cool cinematic desaturation,
- early VSCO-like looks,
- early Instagram-classic inspired looks.

## What this module is

This module is:

- a **creative grading layer**,
- applied after core image normalization and the main film look,
- parameterized and serializable,
- available to web UI, API, and automated agents,
- usable both through curated presets and direct parameter editing.

## What this module is not

This module is not:

- a replacement for Camera Looks,
- a replacement for Film Stocks,
- a replacement for Optical Effects,
- a generic “apply random LUT” system,
- a social-media template engine,
- a destructive editor.

## Required outcomes

The module must let the user or agent:

1. choose a creative color grade preset,
2. inspect its parameters,
3. preview the result,
4. tweak the grade,
5. save it as a custom preset,
6. include it in a final render recipe,
7. publish the rendered result to PhotoPrism.
