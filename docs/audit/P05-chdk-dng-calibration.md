# First CHDK DNGs from the SX510 HS: format, colour, lens geometry (2026-11-04)

Camera: Canon PowerShot SX510 HS, firmware GM1.01A, CHDK `sx510hs-101a-1.6.1-6355-full_ALPHA`,
loaded from an SD card. 26 DNG + JPEG pairs shot by the owner (daylight, tungsten, dark
frame, white sheets, straight lines, a zoom series 4.3-129 mm). The files stay out of Git.

## DNG format (VERIFIED on 26 files)

- DNG 1.4 written by `CHDK ver. 1.6.1`, `UniqueCameraModel = Canon PowerShot SX510 HS`.
- LibRaw visible area 4072x3044 (raw 4168x3062, margins left 96 / top 18), RGGB,
  12-bit, black level 127 on all four channels, white level 4095.
- `DefaultCrop` = origin (36, 22) in the visible area, size 4000x3000: the camera JPEG frame.
- `ColorMatrix1` (illuminant 21 = D65) and `AsShotNeutral` are present; no opcode lists
  (so no lens correction in the file).
- EXIF in the DNG has `FocalLength` and the precise exposure time (e.g. 0.1155 s where the
  JPEG says 1/8). It does **not** carry digital zoom: the DNG always holds the optical field.
- Dark frame (ISO 100, 0.6 s): mean = black level 127, 99.9th percentile 136; slight
  amplifier glow at the left edge.

## Raw/JPEG pairing (VERIFIED)

- The CRW number can lag the JPEG counter: `CRW_4209.DNG` was written at 19:05:00 together
  with `IMG_4210.JPG` (lens-cap frame); shot 4209 has no DNG.
- DNG and JPEG capture times differ by up to 1 s (`4226`). Pair by capture time, never by number.
  The camera-side manifest must record the actual DNG path (P06).

## Colour (VERIFIED, partial)

- Daylight white sheet (`4218`): measured neutral multipliers R 1.74 / B 1.53 vs the
  camera's AWB 1.72 / 1.51: the DNG metadata is consistent with the sensor data.
- Tungsten white sheet (`4211`): neutral needs B x3.97, the camera AWB applies x2.63 and
  deliberately keeps tungsten warm.
- No colour chart yet: the pipeline uses CHDK's `ColorMatrix1` via LibRaw. A ColorChecker
  shot would allow a fitted matrix (PROPOSED).

## Lens geometry (VERIFIED)

At the wide end the raw image is strongly barrel-distorted and its corners fall outside the
image circle; the camera corrects this in its JPEG. `tools/fit_lens.py` fits, per focal
length, the mapping JPEG pixel -> raw position from SIFT matches between each DNG and its
camera JPEG (radial polynomial, robust fit, same-focal pairs pooled), and writes
`profiles/lenses/canon-sx510hs.json`.

| focal | frames | rms | JPEG top-left corner comes from raw |
|---|---|---|---|
| 4.30 mm | 9 | 0.80 px | (334, 246) |
| 5.75 mm | 1 | 0.75 px | (220, 160) |
| 7.51 / 7.71 mm | 1 + 1 | 0.70 / 0.72 px | (134, 96) / (126, 89) |
| 8.81 mm | 1 | 0.77 px | (93, 65) |
| 11.50 mm | 1 | 0.77 px | (55, 37) |
| 15.4-129 mm | 7 | 0.59-0.86 px | (37, 23) = DefaultCrop, no distortion |

The fitted centre is (2036, 1522) at every focal length, the centre of `DefaultCrop`.
Skipped: 3 flat subjects (no features), 1 frame with digital zoom x1.54.

`mfilm_server/lens.py` applies it in `mfilm-develop` to CHDK DNGs of a camera with a lens
table: the decoded linear image is resampled (bilinear) into the 4000x3000 JPEG frame,
interpolating linearly in focal length between calibrated entries. Other sources (e.g.
the EOS M CR2 fixture) are unchanged. Provenance records `lens_correction` (table file,
sha256, focal length). `RAW_ADAPTER_VERSION = rawpy-libraw-v2`,
`INPUT_NORMALIZATION = mfilm-linear-rgb-v2`; `tests/test_lens.py` pins the table hash to
that version, so a new table forces a new normalization version (render ids change).

Check against the camera's own JPEGs (Portra 400 render from DNG vs camera JPEG, SIFT):
median misalignment 0.78 / 0.62 / 0.61 / 0.71 px for 4220 (4.3 mm), 4234 (5.75 mm),
4226 (11.5 mm), 4212 (4.3 mm); outer ring 0.54-0.80 px.

## Limitations

- Vignetting is not corrected (the camera JPEG likely does); the film look adds its own.
  Measuring it needs evenly lit flat frames per focal length (PROPOSED).
- Intermediate wide-end steps rely on interpolation between 5 calibrated points.
- Digital zoom is ignored: advise keeping it off so the render matches the screen framing.
- The camera-side offline development (P05) will need the same geometry, as a
  fixed-point remap; not started.

## Reproduce

    uv pip install -e 'src/server[calib]'
    python tools/fit_lens.py --out profiles/lenses/canon-sx510hs.json <dirs with DNG+JPG>
    mfilm-develop --input CRW_xxxx.DNG --profile portra400 --output out.jpg
