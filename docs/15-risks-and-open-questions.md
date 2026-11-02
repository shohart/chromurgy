# 15 — Risks, Unverified Assumptions and Decision Gates

| ID | Risk / unknown | Consequence | Investigation / fallback |
|---|---|---|---|
| R01 | CHDK SX510 HS port historically ALPHA; exact sub-version not known | Cannot safely boot test build | Firmware detect; known-good SD build; no permanent flashing |
| R02 | Canon creates JPEG even with CHDK RAW; stock Playback may expose it | Strict undeveloped-film UX not guaranteed | Disable review, intercept PLAY, test safe quarantine; report limitations |
| R03 | Native Wi-Fi API in DryOS unverified | Camera cannot auto-upload over LAN | SD import, CHDKPTP USB; timebox network research after usable server |
| R04 | Small free RAM / CPU on DIGIC device | Offline 5–8 MP may be too slow | Bounded streaming with explicit lower-res option; Linux remains primary |
| R05 | Upstream M-Film desktop Darkrooms closed source | Cannot reuse its full-res implementation | Build independent Linux RAW pipeline around open camera M-Film core |
| R06 | Some M-Film film profiles rely on third-party LUTs/assets | Cannot lawfully bundle every film | Audit rights, vendor user-supplied assets or subset with clear errors |
| R07 | Identical film math but distinct RAW decode/demosaic | End-to-end pixels differ | Canonical linear input/film-stage parity corpus and measured visual deltas |
| R08 | Canon gallery may reject externally created JPEGs | On-camera developed browsing fails | CHDK app-specific gallery, thumbnails and cached previews |
| R09 | PhotoPrism import/index settings vary | Images stored but unseen or duplicated | Explicit adapter modes, verified indexing, stable paths and receipts |
| R10 | Power-off interrupts Wi-Fi / camera upload | User thinks sync continues when off | Durable queue and clear UI; no background promise |
| R11 | Camera SD is writable FAT without database-grade transaction guarantees | Torn manifests or incomplete image state | Append/checksum journal, recovery scan and atomic-ish state replacement |
| R12 | HTTP without TLS on an old camera | Exposure of photos / tokens | Trusted LAN or USB/SD; pairing and scoped credentials; no public endpoint |
| R13 | Full-size processing involves costly effects / licensing | Delay, RAM pressure | Optimize streaming; preserve look and provenance; audit LUTs |
| R14 | No real DNG or physical camera for agent | Cannot prove camera compatibility | Host sample fixtures; mark `NOT TESTED`; request exact files at gate |

## Decisions already approved

- Server is **primary film developer**, in-camera only when server absent or user explicitly chooses offline.
- Virtual film roll is fundamental: no per-shutter processing, no immediate post-shot photo review.
- Linux and camera use **one shared C film engine** and profile data; a second approximate implementation is disallowed.
- Server must receive **original DNG** and publish finished JPEGs to PhotoPrism; option to send JPEGs back to device gallery.
- Wi-Fi upload is a desired capability, not a proven fact of CHDK. LAN without Internet is enough.
- Keep originals and all distinct renditions; do not delete or overwrite automatically.

## Explicit non-decisions (agent should resolve empirically)

- Whether SX510 HS can really send HTTP over CHDK-accessible Wi-Fi; whether TLS is viable.
- Which CHDK module/UI hook path safely intercepts stock playback.
- Which offline resolutions fit the RAM/performance envelope and how fast.
- Whether Canon OEM Playback accepts generated JPEGs or a custom gallery is needed.
- Whether complete film LUT catalog can be legally bundled. If not, subset and supply instructions.
- Whether an always-on host import through USB/PTP requires an attached owner device or an SD-first approach.

The agent should investigate these, select the least risky workable implementation, and record decision evidence, rather than asking the user to choose hypothetical APIs.
