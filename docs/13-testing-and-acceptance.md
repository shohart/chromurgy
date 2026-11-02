# 13 — Validation Strategy, Evidence and Acceptance Matrix

## Level 1: host-only tests (CI)

- Original upstream M-Film simulator builds and launches in a reproducible environment; output observed.
- Shared film C core builds for Linux and camera toolchain (the latter is **build-only**, not device proof).
- Reference fixtures include gradient, white/gray chart, skin-like patches, pure RGB primaries, dark/highlight, hot pixels, edge/tile boundary, portrait orientation and several upstream film stocks.
- Full DNG pipeline on Linux produces valid full-resolution 4000×3000 or source-appropriate outputs, no resolution inflation, correct EXIF and expected output-space ICC profile.
- Film profile bundle tests verify IDs, resource hashes, profile count and licensing, and unsupported profile returns error.
- Deterministic grain test: same recipe/seed and source -> same stage output regardless of tile order.
- Input bounds/fuzz tests: truncated DNG, unsupported compression, invalid IFD offsets, absurd image size, malformed manifest and untrusted filename.
- API tests: repeat identical roll/asset uploads, conflicting hashes, partial resume, duplicate finalize, worker failure, repeated publication, camera downloads and reject unauthorized device.

## Level 2: parity tests

**Golden master**: normalized linear input tiles to shared C film stage. Compare host build vs cross-compiled device stage outputs under emulator/unit harness if available; otherwise compare real hardware logs/output tiles to host golden fixture. Any different math/backend must be explicitly declared.

Acceptance expectations:

- exact profile data and deterministic seed generation;
- no palette substitutions or missing film effects;
- fixed-point reference 16-bit stage tolerance goal >=99.9% within ±1 (subject to agreed numeric mode);
- end-to-end image metrics supported by human-approved comparison set: color/contrast, highlight response, noise statistics, no tile seams;
- lower-res output permitted for camera but **not falsely characterized** as equivalent pixel resolution.

Do not use identical JPEG byte hash as parity test across differing encoders/EXIF. Use normalized decoded pixels and stage outputs.

## Level 3: actual SX510 HS device tests

| Test | Evidence | Gate |
|---|---|---|
| Exact CHDK firmware compatibility | firmware version, CHDK build ID, startup log | G1 |
| Safe capture of original DNG | files, sizes, hash, verified decode | G2 |
| No auto-view and blocked original gallery | video or repeatable UI test incl. Canon PLAY | G2 |
| 20 exposures in one/multiple rolls | manifests, hashes, exposure count | G2 |
| No image processing during shutter critical path | capture timing/trace | G2 |
| Offline single-frame film render | image, time, peak RAM | G3 |
| Resume local roll render after power cycle | logs, manifests, images | G3 |
| Return server-developed JPEG to developed gallery | device screenshots, hash | G4 |
| USB/SD upload original DNG | server log+hash match | G4 |
| Native Wi-Fi uplink + result downlink | actual Wi-Fi logs & SHA verification | G5 |
| Battery/storage exhaustion | safe pause and resume | G5 |

## Level 4: system / PhotoPrism

- Import sealed card to Linux, verify all originals, queue automatic server render, publish canonical high-res JPEG; verify PhotoPrism catalog actually displays frames and respects capture dates.
- Duplicate card import / API replay produces no duplicate files or gallery entries.
- Camera offline develops, later synchronizes DNG and local rendition, server generates separate canonical full-size rendition without overwriting local.
- Linux service reboot between upload/init and completion; between rendering and publication; PhotoPrism down for 24 hours; tasks resume on next cycle.
- Camera requests server-rendered gallery preview on next connection; all hashes correct and original remains intact.

## Milestone gates

**G0:** pinned upstream revisions, simulator, inventory of reusable film code and license audit.

**G1:** host DNG->JPEG pipeline + shared film core, tests, server ingest, SD importer and local PhotoPrism publication.

**G2:** CHDK hardware probe, safe roll capture, manifest persistence and measured/verified no-preview implementation.

**G3:** local offline developer using shared core, limited memory, recoverable queue and usable gallery.

**G4:** USB/PTP or SD round-trip with Linux server and optional result return; end-to-end server-first experience even without Wi-Fi.

**G5:** Wi-Fi native transport **if proven**. Cannot mark G5 complete solely because hardware includes Wi-Fi or simulator talks HTTP.

## Reporting rubric

Every test is `PASS`, `FAIL`, `BLOCKED`, or `NOT TESTED`; never substitute `BUILD SUCCESS` for `PASS ON CAMERA`. Record artifact hashes, logs, Git commits, CHDK/Canon versions, build toolchain, dataset permissions and exact commands. See report template.
