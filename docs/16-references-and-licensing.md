# 16 — Verified Research Sources, Licensing and Attribution

Reference date: **2026-11-02**. All URLs and source paths must be rechecked and Git revisions pinned at implementation time.

## M-Film upstream

- https://github.com/HNGSeries/M-Film
- https://github.com/HNGSeries/M-Film/blob/main/PORTING.md
- https://github.com/HNGSeries/M-Film/blob/main/README.md
- https://github.com/HNGSeries/M-Film/blob/main/THIRD_PARTY.md
- https://github.com/HNGSeries/M-Film/blob/main/LICENSE

Upstream publicly describes a 72-film catalog and roll mechanics (12/24/36 exposures). Its portable `ml-dev/filmos` UI/processing code connects to Magic Lantern via `fos_port_*` functions, and its original in-camera Darkroom processes small images with a slice-based CR2 decoder. **Its separate computer application Darkrooms is closed source** and must not be treated as available for reuse. The new Linux implementation must be built from available, properly licensed code.

GPL-2.0 applies to the stated upstream repo; check copyright and exact license of every reused module and third-party LUT/font/binary. Keep derivative redistribution terms and source availability compliant. Do not redistribute proprietary Canon firmware dumps or assets without permission.

## CHDK

- https://github.com/eoschdk/trunk — automatic SVN trunk mirror, described as `use with care`.
- https://chdk.fandom.com/wiki/SX510HS — model port information, historically ALPHA.
- https://chdk.fandom.com/wiki/CameraFeatureTable — port feature/RAW sensor size table.
- https://chdk.setepontos.com/index.php?topic=10984.0 — historical SX510 HS porting thread.
- https://github.com/CHDKUtil/CHIMP — camera/firmware identification and SD installation utility (verify support and current release).

The CHDK wiki's SX510 HS standalone page shows an apparent **incorrect `4608×3456` max-image entry**, whereas the official Canon specification and CHDK camera feature table show **4000×3000**. Use Canon for finished output image size and inspect the camera DNG for raw active geometry.

## Canon SX510 HS original technical specifications

- https://www.usa.canon.com/support/p/powershot-sx510-hs
- https://sg.canon/en/support/6200182800

Canon specifies 12.1 effective MP, still-image large size **4000×3000 (4:3)**, and built-in **2.4 GHz IEEE 802.11b/g/n**. Networking hardware is verified, but third-party application networking is not.

## PhotoPrism

- https://docs.photoprism.app/user-guide/library/webdav/
- https://docs.photoprism.app/user-guide/library/originals/
- https://docs.photoprism.app/user-guide/first-steps/

PhotoPrism supports WebDAV upload and manual/automatic indexing when configured; automatic indexing behavior depends on upload mode/settings and server version. Validate the deployed instance. Do not invent specific PhotoPrism internal APIs.

## Source-of-truth policy

1. Canon official hardware specification outranks inaccurate volunteer model-page entries for model facts.
2. Exact CHDK hardware behavior must be verified on-device; old forums are hints, not compatibility guarantees.
3. M-Film file names and functions are leads until checked in a pinned upstream commit.
4. Reused code and LUT redistribution must be cleared separately; include SPDX headers and license notices in final deliverables.
5. The Ritual is only a UX inspiration; do not copy non-public or proprietary code/assets.
