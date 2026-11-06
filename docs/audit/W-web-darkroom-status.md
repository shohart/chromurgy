# Web Darkroom: status (spec v0.5, docs/web/27-34)

Branch `web-darkroom`. Camera code is untouched. Shared files changed additively:
`db.py` (migrations 5, 6: new tables only), `develop.py` (optional `exif_extra`),
`worker.py` (web items drained in the same pass), `store.py` (4 new subdirs).

## Run it
    mfilmctl web-passwd                        # operator password, once
    mfilm-web --port 8766                      # UI at /darkroom
    mfilmctl worker --watch --interval 5       # develops queued web items and camera rolls

## Tests
`ci/check.sh` runs everything (fresh venv, so it also proves packaging: the `mfilm-web` script and `static/`).
Real RAW fixtures are not in git. Without them the RAW tests skip (silently, `-rs` shows why):

    scp octopusreborn:/mnt/theVault/RAW_LIB/photos/10.11.2015/DSC_0174.NEF ~/fixtures/   # Nikon D5100 NEF
    export MFILM_TEST_NEF=~/fixtures/DSC_0174.NEF                                       # CHDK DNGs default to theVault/Archives/roshal_old_photos/mfilm_calibration
    # from a worktree whose build/ is missing: MFILM_CORE_LIB=<main checkout>/build/src/shared/film_core/libmf_core.so PYTHONPATH=src/server:src/server/tests

## Deploy (octopusreborn, not done)
Migrations 5, 6 and 7 are taken by this branch (user_version 7): the camera branch must use 7+.
After merging: update the service checkout (`deploy/update-user.sh`, empty queue only), **reinstall the venv's
package** so the `mfilm-web` entry point and `static/` exist (`uv pip install -e src/server`), `mfilmctl web-passwd`,
install `deploy/systemd/user/mfilm-web.service`. The worker polls every 30 s, so a web job starts up to 30 s late;
lower `--interval` if that matters. Never point a dev run at /mnt/theVault/mfilm.

## Work packages
| WP | State | Evidence |
|---|---|---|
| W02 upload + source catalog | DONE for DNG/NEF | tests/test_darkroom_api.py: chunked + resumable upload, hash check, dedup by content, truncated / JPEG-as-DNG / wrong extension / unsupported RAW rejected without stopping the batch; real SX510 DNG and Nikon D5100 NEF. Decoder runs in an isolated child (rlimit + timeout). |
| W03 look / film / effect selection | DONE | 72 films, all 9 Camera Looks (8 + Neutral), 6 optical effects, Golden Haze and 5 composite quick-combinations, recipe v2 validated (unknown parameters/ranges, duplicate stack items, halation owner rules: `film`/`optical`/`stacked`/`disabled`, a doubled halation is refused with HALATION_CONFLICT). Implemented in `darkroom/creative.py` (numpy, scene-linear, optics -> look -> film, radii as fractions of the image diagonal, deterministic) with the provisional starter values of contracts/v0.5. **Deviation from the spec:** not in the shared C core, so Linux-only (the camera never renders them; spec 22 allows that). **Honest limits:** original artistic approximations, not measured recreations; ~14 s extra per 12 MP frame; no visual regression corpus yet. Neutral look + no effect keeps the old render ids (no `creative` block in the v1 recipe). tests/test_darkroom_creative.py (32 numeric checks: strength 0 = identity, spill into neighbours, far field unchanged, monotonic strength, scale independence, fixed engine order, look character). |
| W04 preview | DONE | tests/test_darkroom_preview.py: real core on a cached <=2048 px normalization; ~0.6-1.1 s per preview after the first (~11 s); cache key source+recipe+engine+size; latest request wins; before/after wipe. |
| W05 full-size render, history | DONE (+ History UI, publish later) | tests/test_darkroom_jobs.py: durable jobs, per-item states, cancel/retry, ZIP, history, restart recovery (recover_stale), identical render reused (no new file), new recipe = new rendition, never upscaled, source EXIF (make/model/ISO/exposure) kept. |
| W01 PhotoPrism doctor | DONE, live | `mfilmctl photoprism-doctor [--write-test]` on the real instance (260728 Plus): API auth, albums, folders, RAW detection, read an original from disk with SHA-1 == PhotoPrism's record, folder write, index command, album create+delete. Config: `[photoprism] url, token_file (0600), originals_dir, index_template, web_folder`. The API token is an app password for `admin`, in `~/.config/mfilm/photoprism.token` on octopus. |
| W06 source picker + publishing | DONE, live end-to-end | Tests with a fake PhotoPrism (response shapes observed live) plus a live run on octopus 2026-11-06: NEF from folder 10.11.2015 -> Leica M9 0.8 + Soft Sun Glow 0.45 + Portra 400 at 2400x1590 -> published to `M-Film/Developed/selftest/`, indexed, UID reconciled, added to the new album "mfilm-selftest (safe to delete)"; COMPLETE in ~50 s; the source NEF's SHA-1 still equals PhotoPrism's record. **Test leftovers in the library:** that one JPEG and that album: delete them from PhotoPrism when you like. |
| W07 security | PARTIAL | operator login (scrypt, 0600 file, HttpOnly SameSite=Strict cookie, CSRF header), device tokens are not accepted, strict CSP, upload limits. No HTTPS (deployment decision), no per-user roles, no upload quota/cleanup job for abandoned `.part` files yet. |

## Deployed (octopusreborn, 2026-11-06)
Service checkout `~/services/mfilm` fast-forwarded to the branch tip (not merged into the dev repo's main), DB migrated v4 -> v7
(backup: `/mnt/theVault/mfilm/db/mfilm.sqlite3.bak-before-web-darkroom`; config backup `~/.config/mfilm/config.toml.bak-before-web-darkroom`).
`mfilm-web` user service on **http://192.168.1.123:8766/darkroom** (plain HTTP, LAN only), operator password in
`~/.config/mfilm/web-password` (0600), change it with `mfilmctl web-passwd`. Worker interval lowered 30 s -> 10 s so web jobs start quickly.
PhotoPrism credentials: app password for `admin` in `~/.config/mfilm/photoprism.token` (0600): rotate it, it was pasted into a chat.

## Added 2026-11-06 (second pass, deployed)
- Fix: the preview now follows the frame last clicked (click = preview, tick = include in Develop); the previous frame's picture is cleared at once, never left standing.
- M-Film rolls tab: archived, hash-verified roll originals become sources (`origin camera_roll`, the DNG is not copied); jobs of kind `mfilm_roll`; the roll's own archive untouched (tested).
- `POST /renders/{id}/publish` + History panel: publish a finished render later; same source+recipe+size reuses the file byte for byte, repeating the request is a no-op (tested live on octopus).
- `tools/creative_sheet.py`: none/25/50/100 % comparison sheets for every effect and look (synthetic scene or `--image`).
- Job kind and source origin must agree (`SOURCE_KIND_MISMATCH`).

## Crop (third pass)
Per-frame crop: `crop {x,y,w,h}` in NORMALIZED coordinates of the upright, lens-corrected frame, so a 1280 px preview and the full-size
render show the same framing. Applied right after normalization and BEFORE optical effects, Camera Look and film (radii, scanner
exposure and grain scale refer to the kept picture); the RAW is never touched; the crop is part of the render id (another crop = another file
next to the old one; no crop keeps the old ids). Job assets carry their own `crop` (extension of web-darkroom-job.schema.json, flagged in the
contract copy); a job-level `recipe.extensions.crop` also works and is what "publish later" reuses. UI: **Crop** on the preview stage shows the whole frame with a
rule-of-thirds rectangle, 8 handles, proportions (free / original / 1:1 / 5:4 / 4:3 / 3:2 / 16:9 and portrait), rotate ratio, arrow keys (Shift = resize),
Reset, Cancel, Done, "Apply to all selected" (same fractions per frame); crops persist across a page reload (localStorage). `Output size` after a crop still means "not
larger than the kept pixels" (never upscaled). Tested: normalization rules, same fractions at every resolution, preview before/treated line up, native-pixel full-size
output (73.3 % x 65.1 % of 4000x3000 -> 2931x1954), dedup of equal crops, publish-later keeps the framing; driven with a real mouse in the browser.
Not included: straighten/rotate by an angle, lens-perspective correction.

## Known limits
- Preview demosaic is LibRaw's fast linear one (documented in preview.py); final renders use the recipe's demosaic.
- A job's `GET` is polled by the UI (2.5 s); SSE is not implemented.
- Web outputs use grain seed derived from the source hash + recipe, not from a roll.
- NEF/DNG from other makers go through generic LibRaw colour; only the SX510 has a lens table.
