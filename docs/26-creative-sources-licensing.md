# 26 — Creative Looks: Sources, Attribution and Legal Guardrails

## Confirmed reference points (research, not files to bundle)

- M-Film upstream, GPL-2.0 camera-side source and third-party film LUT restrictions: https://github.com/HNGSeries/M-Film
- Nikon / Leica / Fujifilm / Pentax CCD signature names are offered as a **commercial** pack by Cobalt: https://www.cobalt-image.com/product/ccd-fever-for-adobe/ . The pack is **not a dependency** and must not be copied, bundled or reverse-engineered from licensed binaries.
- Ricoh official GR III Positive Film Image Control: https://www.ricoh-imaging.co.jp/english/products/gr-3/spec/
- Ricoh HDF manufacturer explanation/comparison: https://www.ricoh-imaging.co.jp/english/products/gr-3/special/hdf/
- Fujifilm official X-Pro3 film simulation descriptions, including Classic Negative: https://fujifilm-dsc.com/en-int/manual/x-pro3/menu_shooting/image_quality_setting/index.html
- darktable's documented image diffusion and bloom concepts: https://docs.darktable.org/usermanual/development/en/module-reference/processing-modules/diffuse/ . Use as technical research; if copying code, independently audit the exact component's GPL license and dependency compatibility.
- Fuji profile community collection: https://github.com/eowynring/fujifilmcameraprofiles — CC BY-NC-SA 4.0. **Do not bundle as generic assets in distributed GPL software without legal review of license compatibility and non-commercial restriction.**
- Canon PowerShot SX510 HS official specifications (12.1MP, 4000×3000 JPEG, DIGIC 4 and 2.4 GHz Wi-Fi): https://sg.canon/en/support/6200182800
- CHDK SX510 HS port listing (alpha): https://chdk.fandom.com/wiki/SX510HS
- PhotoPrism index-on-WebDAV behavior and configurable auto-index: https://docs.photoprism.app/user-guide/library/originals/

## Rules for implementers

1. Copy **only** code/assets with a recorded source, commit/release, SPDX or license text and legal review for the intended distribution. Never bundle a commercial plugin/profile or a proprietary camera RAW converter.
2. Camera model and film names are references for identification. Put `Inspired by` / `Unofficial emulation` in GUI/docs; do not imply endorsement, authorized reproduction or physical sensor matching.
3. Reference photography must have redistribution rights or be stored locally (not checked into public repository); remove sensitive EXIF/GPS as needed. Use synthetic charts freely.
4. Results from proprietary reference software can be used only if lawfully obtained and permissible under applicable terms; avoid extracting protected embedded data or duplicating branded UI assets.
5. Before importing upstream M-Film assets, inspect `LICENSE` and `THIRD_PARTY.md`. GPL distribution and asset licenses are separate questions; document inclusion decisions and attribution notices.
6. Maintain a `PROFILE_PROVENANCE.md` generated at build time listing every shipped profile's source, author (ours or licensed), status, validation domain, and licensing.

## Quality / honesty

A hand-tuned preset inspired by a camera is *not* a calibrated model of its sensor or JPEG engine. No algorithm can restore missing clipped highlights, reproduce unavailable optical inputs or reconstruct the actual Foveon sampling of a different sensor. Use neutral and named inspired profiles with explicit confidence tiers.
