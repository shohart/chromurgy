# 12 — Security, File Integrity and Failure Recovery

## Threat model

Hostile LAN device spoofing camera, malicious upload filename/path traversal, repeated replay, corrupted files, unstable SD card, loss of Wi-Fi mid-file, crash after server storage but before receipt, compromised camera token, unsupported DNG parser, PhotoPrism inadvertent publication of private/unfinished images, physical access to camera SD, low battery during development.

## Required controls

- **Pairing:** explicit owner approval on Linux; give camera scoped credentials and logical device ID; support revocation and rotation.
- **Transport:** HTTPS when supported; if DryOS cannot do TLS, do not falsely describe plaintext bearer token as secure. An isolated/trusted WPA2 LAN/VLAN with no WAN exposure is a documented constrained workaround; prefer USB/SD where confidentiality matters. Evaluate a local bridge/tunnel on a trusted device rather than embedding heavyweight TLS into CHDK blindly.
- **Authorization:** credentials bound to `device_id`, upload size limits, content hashes, allowed media types and API version. Never trust arbitrary upload paths or EXIF strings.
- **Server filesystem:** stage outside PhotoPrism, strip supplied path components, refuse symlinks to outside approved roots, use strict permissions, separate service user, disk quota and free-space checks.
- **Parsing:** sanitize DNG/EXIF inputs, limit dimensions, fuzz input decoder on Linux, reject unsupported compression/metadata. Do not execute embedded metadata or remote scripts.
- **Secrets:** no tokens, Wi-Fi passwords or serial numbers in repo or log; use file permissions and rotation. Camera SD is not a secure secret store; document risks.

## Recovery matrix

| Interruption | Expected recovery |
|---|---|
| Camera powers off during capture | Keep prior verified frames; reconcile incomplete new frame from filesystem |
| Camera powers off during offline render | Discard incomplete `.part`; resume remaining frames from journal |
| Camera powers off while uploading | Server retains staging offset; next session queries and resumes |
| Server crashes after full file before HTTP ACK | Repeated `complete` returns identical durable receipt |
| Duplicate manifest / render request | Resolve existing matching object, do not enqueue twice |
| Server job crashes | Worker retries with bounded count; cannot create duplicate canonical JPEG |
| PhotoPrism unavailable | Originals+renders retained; publication queued for retry |
| Camera lacks storage for returned gallery JPEG | Keep server result; mark `AVAILABLE_REMOTE` and retry later |
| Bundle/core mismatch | Pause render or use archived exact bundle, never silent color drift |
| Canon DNG invalid | Keep file and report `SOURCE_INVALID`; never destructively replace with JPEG |

## Retention and backups

Default **retain originals** on both camera and Linux. Long-term automated cleanup on camera is explicitly **not in v1** and requires separate safety review, proven server redundancy, hashes, and opt-in user policy. Enforce server archive backups before relying on it for unique photographs. Keep checksum on every asset and perform periodic scrub.

## Sensitive information

Log only logical IDs and error codes, never GPS coordinates or private image data by default. A photo-processing system inevitably holds personal photographs: secure local access, no public uploads endpoint, no telemetry, and no automatic outbound sharing.

## Firmware reversibility

The experimental app must be removable by SD card, subject to verification of chosen CHDK install method. No write to internal ROM, NVRAM or boot flags without separate written approval. A separate recovery card and safe shutdown procedure are required before device tests.
