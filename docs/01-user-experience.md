# 01 — User Journeys and UX Rules

## A. Prepare a roll

- Power on camera and enter M-Film app via CHDK.
- Choose a film stock (existing M-Film catalog, up to 72 profiles subject to asset licensing), fixed roll length (12/24/36), and optional realistic rewind mode.
- Store stable `film_profile_id`, `profile_bundle_hash`, `roll_id`, `device_id`, start time, exposure count. Profile is frozen for this roll, even if global default later changes.
- Show a low-footprint exposure HUD and remaining frames; offer manual `Finish Roll` (exposed frames only).

## B. Capture without review

- Use Canon exposure/AF/zoom and normal shutter.
- Disable automatic image review where available. Intercept app-level playback navigation while an undeveloped roll is loaded.
- Store RAW/DNG; stock Canon JPEG may still be produced by the camera. Temporarily quarantine/hide it only if hardware-tested safe.
- Do not render film look on shutter event. Do not start Wi-Fi in a time-critical shot sequence.
- Allow multiple sealed rolls and a fresh loaded roll while prior rolls await sync; do not couple exposure count to uploading.
- If image review cannot be prevented at the Canon firmware level, the agent must report the limitation explicitly and should not call the strict film experience complete.

## C. Finish and use the default server route

- After last exposure or manual finish, mark roll `SEALED`; manifest describes all expected frame IDs and original hashes when available.
- When camera is awake and not shooting, detect receiver reachability. A server on the same Wi-Fi LAN counts as online; Internet is unnecessary.
- Show `Ready to sync`, `Uploading 7/24`, `Awaiting server development`, `Developed on server`, etc. Never block capture to wait for render.
- Upload **RAW originals and recipe**. Server archives, verifies, automatically develops, and publishes to PhotoPrism.
- On later camera connection, query completed roll, optionally download camera-friendly gallery JPEGs (possibly resized derivatives), verify and mark available in M-Film gallery.

## D. Offline fallback

- If connection is unavailable or user chooses not to upload, expose `Develop on Camera` for a sealed roll.
- Explicitly state approximate/selected output resolution and expected time after calibration; no implied 12 MP if impossible.
- Process sequentially with restartable queue; append locally developed JPEGs to gallery.
- On reconnection upload source DNG and local developed products with recipe metadata; server may generate a full-size canonical render. Do not overwrite the offline JPEG silently.

## E. Re-development and alternate film

- Original RAW never changes. A user may create an **additional** rendition with different profile/recipe, preferably on Linux.
- A repeated exact recipe creates or returns the same rendition identity (unless reprocessing is explicitly requested due to renderer bug or compatibility issue).
- Preserve which rendition was made locally, which remotely, their resolutions and core version.

## F. Errors, interruption and battery

- Low battery: finish atomic write, pause further development/transfer and continue after recharge. No silent deletion.
- Wi-Fi missing: show `Offline. Originals preserved.` and allow local development.
- Device off: no promises of continued transfer; server continues processing originals already received.
- Server down: leave rolls queued. User can take a new roll immediately.
- SD card full: block only operations that cannot safely proceed; tell user what space is needed. Never overwrite earlier shots.

## UI acceptance

Primary controls: `Load Film`, `Finish Roll`, `Sync`, `Develop Here`, `Developed Gallery`, `Roll Status`, `Settings`. The ordinary camera image review must not expose unprocessed roll images under the target verified mode. Buttons must be adapted to camera hardware and CHDK key map, with a recoverable escape to Canon/CHDK menus.
