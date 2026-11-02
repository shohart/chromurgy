# 06 — RAW/DNG Acquisition and Color Pipeline

## Source facts

SX510 HS records standard Canon JPEG at max 4000×3000. CHDK may create DNG/RAW with larger sensor-area dimensions than the final display area; never infer buffer width solely from JPEG resolution. Obtain actual camera DNG samples to determine active crop and metadata. Confirm that each DNG is complete before upload or development.

## Reader contract

Read and validate TIFF/DNG directory layout, byte ordering, strips/tiles and compression, bit depth, CFA pattern, `BlackLevel`, `WhiteLevel`, `ActiveArea`, `DefaultCropOrigin`, `DefaultCropSize`, orientation, white balance/as-shot neutral and camera-to-XYZ matrices. Support only verified modes with a clear `UNSUPPORTED_DNG_FEATURE` failure; do not blindly assume every `.dng` is uncompressed Bayer.

Linux can use LibRaw or another audited DNG parser as an **input adapter**, but the film look must remain M-Film shared C. For offline CHDK use a memory-constrained reader tailored to confirmed camera-produced files and document supported metadata and compression. Any DNG parsing on the camera must bounds-check lengths/offsets to avoid out-of-bounds reads.

## Reference output sequence

```text
DNG original
  -> integrity validation
  -> black-level subtraction + linearization
  -> defect/hot pixel and edge/optical corrections (if supported)
  -> demosaic into linear RGB
  -> white balance
  -> camera matrix / reference linear color space
  -> shared M-Film film core
  -> tone encoding and output crop/resample (only if requested)
  -> JPEG with color profile and EXIF
```

Film pipeline must explicitly document **where gamma and film LUTs apply**. Follow actual upstream M-Film algorithms where portable. Use canonical reference transforms; do not add a generic sRGB LUT in an unsuitable linear stage by accident.

## Resolution tiers

| Output | Target | Requirement |
|---|---|---|
| Host canonical | 4000×3000 4:3 | Derived from native active image, no upscaling of 720×480 preview |
| Host alternative | Crop/orientation-adjusted | Preserve intended aspect and exif orientation |
| Camera diagnostic | <= 720×480 | First validated fallback proof |
| Camera Standard candidate | 2592×1944 | Gate on measured memory and processing time |
| Camera High candidate | 3264×2448 | Stretch goal with on-device validation |

Changing dimensions does not change film recipe identity, but **does** change rendition identity.

## Streaming implementation

- Fixed-size input blocks and output tiles; keep rows overlapped by max effect radius.
- For algorithms with whole-image dependencies, use a prepass for histograms/statistics, or external temporary file on SD with explicit bounds/cleanup.
- Use sample-aware grains: deterministic noise indexed by global coordinates; proper scaling for final resolution.
- Use fixed-point or LUT-based math when justified for DIGIC 4; avoid silently different color transforms between reference and optimized paths.
- JPEG encoder may be reused from M-Film if portable; validate metadata and progressive/baseline compatibility with PhotoPrism and camera viewer.

## Canon JPEG and native gallery

Do not claim Canon Playback recognizes externally created JPEGs by mere filename copying. Verify DCF directory rules, EXIF, thumbnails, indexing and caching on hardware. If unsupported, the CHDK app must provide its own developed-only gallery or a reduced preview browser.

## Required tests

Real SX510 HS daylight/gray card/skin/tungsten DNGs; orientation shots; overexposure; large/small DNG; corrupt IFD; malformed dimensions; unsupported compression; sensor crop; 4:3/3:2/16:9; different ISO/noise profiles; missing white balance; tile-edge continuity. Document color calibration accuracy, not only decodability.
