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
Migrations 5 and 6 are taken by this branch (user_version 6): the camera branch must use 7+.
After merging: update the service checkout (`deploy/update-user.sh`, empty queue only), **reinstall the venv's
package** so the `mfilm-web` entry point and `static/` exist (`uv pip install -e src/server`), `mfilmctl web-passwd`,
install `deploy/systemd/user/mfilm-web.service`. The worker polls every 30 s, so a web job starts up to 30 s late;
lower `--interval` if that matters. Never point a dev run at /mnt/theVault/mfilm.

## Work packages
| WP | State | Evidence |
|---|---|---|
| W02 upload + source catalog | DONE for DNG/NEF | tests/test_darkroom_api.py: chunked + resumable upload, hash check, dedup by content, truncated / JPEG-as-DNG / wrong extension / unsupported RAW rejected without stopping the batch; real SX510 DNG and Nikon D5100 NEF. Decoder runs in an isolated child (rlimit + timeout). |
| W03 look / film / effect selection | PARTIAL | 72 films + recipe v2 validated against the contract. The 8 Camera Looks (only Neutral works) and all 6 optical effects are listed **disabled** and rejected with 422 UNSUPPORTED_*: the film core does not implement them yet (decided with the owner: web first, looks later). |
| W04 preview | DONE | tests/test_darkroom_preview.py: real core on a cached <=2048 px normalization; ~0.6-1.1 s per preview after the first (~11 s); cache key source+recipe+engine+size; latest request wins; before/after wipe. |
| W05 full-size render, history | DONE | tests/test_darkroom_jobs.py: durable jobs, per-item states, cancel/retry, ZIP, history, restart recovery (recover_stale), identical render reused (no new file), new recipe = new rendition, never upscaled, source EXIF (make/model/ISO/exposure) kept. |
| W01 PhotoPrism doctor, W06 source picker + publishing | NOT STARTED | needs the PhotoPrism API token at doctor time. Job requests for `photoprism_*` sources or `publish: true` return 422 SOURCE_KIND_UNAVAILABLE / PUBLISH_UNAVAILABLE. |
| W07 security | PARTIAL | operator login (scrypt, 0600 file, HttpOnly SameSite=Strict cookie, CSRF header), device tokens are not accepted, strict CSP, upload limits. No HTTPS (deployment decision), no per-user roles, no upload quota/cleanup job for abandoned `.part` files yet. |

## Known limits
- Preview demosaic is LibRaw's fast linear one (documented in preview.py); final renders use the recipe's demosaic.
- A job's `GET` is polled by the UI (2.5 s); SSE is not implemented.
- Web outputs use grain seed derived from the source hash + recipe, not from a roll.
- NEF/DNG from other makers go through generic LibRaw colour; only the SX510 has a lens table.
