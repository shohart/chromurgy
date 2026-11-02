# 17 — Glossary and Stable Terms

- **Original** — unchanged DNG/RAW from the camera; never a Canon JPEG proxy or a resized preview.
- **Stock Canon JPEG** — native JPEG the Canon firmware may create alongside CHDK RAW. It must not be shown as a developed film image.
- **Roll** — immutable group of intended exposures sharing one profile and roll ID, sealed before batch processing.
- **Development** — RAW decode + shared M-Film film rendering + encoded rendition output, not merely uploading existing Canon JPEG.
- **Film core** — platform-neutral C implementation of film look and models, compiled unchanged into Linux and camera targets except justified platform adapters.
- **Profile bundle** — versioned, hashed parameters/LUTs, with provenance and redistribution rights.
- **Recipe** — exact named profile, core version, settings, seed, output quality/size and source normalization contract.
- **Rendition** — immutable output image version derived from one original and one render recipe/output specification.
- **Canonical server rendition** — Linux-produced full-size, verified rendition chosen for automatic PhotoPrism publication.
- **Offline rendition** — CHDK camera-produced fallback, usually with different resolution/encoder and separate rendition ID.
- **Camera gallery** — developed-only index viewed on device, not necessarily OEM Canon Playback.
- **PhotoPrism publication** — verified file exists in PhotoPrism input folder; `INDEXED` means visible in its catalog and is a separate state.
- **Online** — Linux receiver reachable, potentially only via a local Wi-Fi LAN. Public Internet is optional and not required.
- **Sync** — transfer of original bytes and metadata to server, server receipts, optionally retrieval of developed results; never means deletion of camera originals.
- **Hardware gate** — task must be tested with the actual SX510 HS and matching Canon/CHDK firmware before it may be marked passed.
