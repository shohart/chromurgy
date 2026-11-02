# 10 — Transports: Wi-Fi, USB/PTP, SD

## Rule: connectivity != Internet

Canon's built-in Wi-Fi supports infrastructure connections in the 2.4 GHz band. A local server on the same LAN requires **no Internet access**. However, SX510 HS CHDK does not have a confirmed general-purpose Wi-Fi/socket API. Native Canon pairing/copy features are not proof that arbitrary C apps can upload to an HTTP endpoint. This is the project's highest technical uncertainty.

## Adapter interface (proposal)

```c
struct mf_transport_ops {
  int (*probe)(void *ctx);
  int (*connect)(void *ctx);
  int (*exchange_manifest)(void *ctx, const void *req, unsigned len);
  int (*send_chunk)(void *ctx, const void *chunk, unsigned len, unsigned long offset);
  int (*recv_chunk)(void *ctx, void *dst, unsigned cap, unsigned long offset);
  int (*disconnect)(void *ctx);
};
```

Logical sync and state machines cannot depend on a specific network API. Use a host-side adapter when USB/PTP pulls rather than camera HTTP pushes are the reliable path.

## Phase A: SD ingest, must ship early

- Mount card on Linux, run `mfilmctl import-card /media/camera`, read manifests + source DNG, verify SHA-256, insert server DB records and run developer.
- Safe when camera is off and SD removed. Never rewrite the card unless explicit mode enabled. Export a machine-readable receipt file that can later be imported by camera to reconcile states if network is unavailable.
- Use this transport to validate complete server-first workflow before debugging Wi-Fi.

## Phase B: USB/PTP (preferred initial automation)

- Explore `chdkptp` live control, remote file list/download, USB session lifetime and model-specific limitations.
- Linux initiates transfers; camera can be passive. Map each received source file to its manifest and support resume/idempotent relaunch.
- Do not assume USB presents camera as USB mass storage. If PTP cannot access needed files on the specific build, fallback to SD reader.
- Return camera-compatible JPEG via PTP upload if available and tested, or provide SD import fallback.

## Phase C: Wi-Fi R&D (hardware gate)

1. Extract **owner-authorized** Canon firmware dump or use existing legally obtained reverse-engineering information.
2. Map Wi-Fi/network init tasks, existing Canon transfer protocol, sockets/TCP/UDP and PTP/IP calls in DryOS; document exact function offsets per firmware revision.
3. Prototype read-only network status and capability detection; do not destabilize recording or sleep transitions.
4. Attempt a minimal controlled connection to a known test LAN endpoint and exchange a short fixed message.
5. Add safe DNS/static IP configuration, connection timeout, orderly teardown and RF power/battery impact metrics.
6. Implement bounded chunk upload and download with checksums; trigger **only after roll is sealed and capture is idle**.
7. Test reconnect, wrong password, AP absent, AP reboot, high latency, multi-minute transfer, battery and camera reboot.

**Gate to claim Wi-Fi working:** on the actual SX510 HS and exact CHDK/Canon firmware, upload a complete DNG and download a JPEG with verified SHA-256 through the native Wi-Fi interface; repeat after restart and disconnect. Compiled transport code alone is not sufficient.

## Power, scheduling and environment

- Camera has no always-on service while powered off. A sync service runs only while the CHDK environment is active and camera is powered.
- Default to camera-initiated sync after sealed roll when idle; manual sync and optional `sync on power-on` supported.
- Pause on low battery, active recording/capture, disk errors or UI mode constraints. Never let Wi-Fi activity introduce shutter lag.
- For transfer over remote WAN, require secure TLS or trusted VPN endpoint. Do not mistake a camera's Wi-Fi connection for Internet requirement.

## Transport status

| Method | Delivery role | Confidence |
|---|---|---|
| SD card + Linux reader | Baseline functional route | Host implementation feasible; hardware card required |
| USB/PTP via CHDK | Early automation route | Port-specific testing required |
| Native Wi-Fi via CHDK/DryOS | Target autonomous route | Research-only until proven |
| Camera as Wi-Fi HTTP server | **Not required** | Avoid: device sleeps and memory is limited |
