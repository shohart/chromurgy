# Development

Implementation status lives in `docs/audit/` (phase reports). The spec in `docs/` and `README.md` is the source of truth; nothing is DONE without evidence (see `AGENTS.md`).

## Layout (as built so far)

```text
LOCKFILE                     pinned upstream commits (M-Film, CHDK, Film-Luts)
profiles/                    all 72 M-Film films: sources, LUTs, built bundle (tools/build_bundle.py)
deploy/                      systemd unit, install notes; config.example.toml at the root
scripts/fetch-upstream.sh    clone pins into vendor/ (git-ignored)
src/shared/film_core/        portable C film core (GPL-2.0, Linux + future CHDK build)
src/server/                  Python package mfilm_server + mfilmctl
tools/                       golden-vector generators (need vendor/)
ci/check.sh                  host CI: cmake/ctest + pytest
contracts/                   wire contracts (spec)
docs/audit/                  phase reports
```

## Quick start

```sh
scripts/fetch-upstream.sh          # only needed for tools/ and upstream simulator
ci/check.sh                        # build film core, run C + Python tests
src/server/.venv/bin/mfilmctl --data-dir /tmp/mfilm init
src/server/.venv/bin/mfilmctl --data-dir /tmp/mfilm import-card /media/$USER/CANON_DC --dry-run
src/server/.venv/bin/mfilm-develop --list-films
src/server/.venv/bin/mfilm-develop --input IMG_0001.DNG --profile portra400 --output out.jpg
src/server/.venv/bin/mfilmctl --data-dir /tmp/mfilm worker          # develop queued rolls (+ publish if configured)
```

Rebuild the film bundle after changing `profiles/source` or `profiles/luts`:
`src/server/.venv/bin/python -I tools/build_bundle.py` (then ctest; `tools/check_upstream_tables.sh` compares with upstream).

`mfilmctl` exit codes: 0 ok, 1 problems found (invalid/conflicting/incomplete roll), 2 usage, 3 not implemented.

## Rules worth repeating

- The film look comes only from `src/shared/film_core` (ported from M-Film, checked against upstream golden vectors). Python never reimplements it.
- Regenerate golden vectors only after a deliberate `LOCKFILE` bump: `tools/gen_golden_film_color.sh`.
- No camera RAWs, firmware, LUTs or personal photos in Git (`.gitignore` blocks the common ones).
