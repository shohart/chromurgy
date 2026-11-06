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
| W03 look / film / effect selection | PARTIAL | 72 films + recipe v2 validated against the contract. The 8 Camera Looks (only Neutral works) and all 6 optical effects are listed **disabled** and rejected with 422 UNSUPPORTED_*: the film core does not implement them yet (decided with the owner: web first, looks later). |
| W04 preview | DONE | tests/test_darkroom_preview.py: real core on a cached <=2048 px normalization; ~0.6-1.1 s per preview after the first (~11 s); cache key source+recipe+engine+size; latest request wins; before/after wipe. |
| W05 full-size render, history | DONE | tests/test_darkroom_jobs.py: durable jobs, per-item states, cancel/retry, ZIP, history, restart recovery (recover_stale), identical render reused (no new file), new recipe = new rendition, never upscaled, source EXIF (make/model/ISO/exposure) kept. |
| W01 PhotoPrism doctor | DONE, live | `mfilmctl photoprism-doctor [--write-test]` on the real instance (260728 Plus): API auth, albums, folders, RAW detection, read an original from disk with SHA-1 == PhotoPrism's record, folder write, index command, album create+delete. Config: `[photoprism] url, token_file (0600), originals_dir, index_template, web_folder`. The API token is an app password for `admin`, in `~/.config/mfilm/photoprism.token` on octopus. |
| W06 source picker + publishing | DONE in code and tests, live READ verified; live WRITE not run | Tests (fake PhotoPrism with the observed response shapes): albums vs folders, pagination, RAW eligibility (JPEG-only, RAW record missing, unverified RAW family all refused with a reason, never the sidecar JPEG), traversal / hash mismatch refused, original untouched, original replaced after selection -> SOURCE_CHANGED, publish to folder + new/existing album in idempotent stages (copy -> index -> UID by exact folder+name -> album), PhotoPrism outage keeps the render and recovers. Live through the browser UI: albums listed, folder `10.11.2015` opened, 2 real D5100 NEFs snapshotted. NOT yet run live: publishing into the real library. |
| W07 security | PARTIAL | operator login (scrypt, 0600 file, HttpOnly SameSite=Strict cookie, CSRF header), device tokens are not accepted, strict CSP, upload limits. No HTTPS (deployment decision), no per-user roles, no upload quota/cleanup job for abandoned `.part` files yet. |

## Known limits
- Preview demosaic is LibRaw's fast linear one (documented in preview.py); final renders use the recipe's demosaic.
- A job's `GET` is polled by the UI (2.5 s); SSE is not implemented.
- Web outputs use grain seed derived from the source hash + recipe, not from a roll.
- NEF/DNG from other makers go through generic LibRaw colour; only the SX510 has a lens table.
