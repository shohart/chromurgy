# SPDX-License-Identifier: GPL-2.0-only
"""mfilmctl: admin CLI (docs/08). Exit codes: 0 ok, 1 problems found, 2 usage, 3 not implemented."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import config as config_mod
from . import db
from .ids import sha256_file
from .importer import as_dict, import_card
from .store import Store

DEFAULT_ROOT = os.environ.get("MFILM_DATA_DIR", "/var/lib/mfilm")
NOT_IMPLEMENTED: tuple[str, ...] = ()


def _open(root: str | None, cfg=None) -> tuple[Store, "db.sqlite3.Connection"]:
    store = Store(Path(root or (cfg.data_dir if cfg else DEFAULT_ROOT)))
    store.init()
    conn = db.connect(store.db_path)
    db.migrate(conn)
    return store, conn


def _out(args, payload, text: str) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else text)


def cmd_init(args) -> int:
    store, conn = _open(args.data_dir, args.cfg)
    from . import core
    from .bundles import Bundles
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    try:
        sha = Bundles(store).ensure_default()
    except core.CoreError as e:
        sha = f"not archived ({e.code})"
    _out(args, {"data_dir": str(store.root), "schema_version": v, "profile_bundle": sha},
         f"initialised {store.root} (schema v{v}, profile bundle {sha})")
    return 0


def cmd_import_card(args) -> int:
    store, conn = _open(args.data_dir, args.cfg)
    card = Path(args.card)
    if not card.is_dir():
        print(f"not a directory: {card}", file=sys.stderr)
        return 2
    results = import_card(card, store, conn, dry_run=args.dry_run)
    queued = []
    if not args.dry_run and not args.no_develop:
        from . import worker
        for r in results:
            if r.status in ("IMPORTED", "UNCHANGED"):
                try:
                    queued.append(worker.enqueue_roll(conn, r.roll_id, r.device_id))
                except Exception as e:          # the import itself stands; report and continue
                    queued.append({"roll_id": r.roll_id, "error": str(e)})
    lines = [f"{r.status:10} {r.device_id or '-'}/{r.roll_id or '-'}  {r.manifest}"
             + (f"  ({r.detail})" if r.detail else "")
             + "".join(f"\n    #{f.ordinal:02} {f.status}" + (f" {f.error_code}" if f.error_code else "")
                       for f in r.frames if f.status in ("ERROR",) or args.verbose)
             for r in results] or ["no roll manifests found under CHDK/MFILM/ROLLS"]
    lines += [f"queued {q['queued']}/{q['frames']} frames of {q['roll_id']}" if "queued" in q
              else f"not queued {q['roll_id']}: {q['error']}" for q in queued]
    _out(args, {"card": str(card), "dry_run": args.dry_run, "rolls": as_dict(results), "queued": queued},
         "\n".join(lines))
    bad = any(r.status in ("INVALID", "CONFLICT", "INCOMPLETE") for r in results)
    return 1 if bad else 0


def cmd_camera_sync(args) -> int:
    from .camera_sync import SyncError, sync
    store, conn = _open(args.data_dir, args.cfg)
    host = args.host or (None if args.usb else args.cfg.camera_host)
    try:
        r = sync(store, conn, host=host, mirror=Path(args.mirror) if args.mirror else None, chdkptp=args.cfg.chdkptp)
    except SyncError as e:
        _out(args, {"ok": False, "error_code": e.code, "detail": e.detail}, f"camera-sync: {e.code}: {e.detail}")
        return 1
    queued = []
    from . import worker
    for x in r.rolls:
        if x.status in ("IMPORTED", "UNCHANGED"):
            try:
                queued.append(worker.enqueue_roll(conn, x.roll_id, x.device_id))
            except Exception as e:
                queued.append({"roll_id": x.roll_id, "error": str(e)})
    lines = [f"camera via {r.connection}: downloaded {len(r.downloaded)} file(s)"]
    lines += [f"{x.status:10} {x.device_id or '-'}/{x.roll_id or '-'}" + (f"  ({x.detail})" if x.detail else "")
              for x in r.rolls]
    _out(args, {"ok": True, "connection": r.connection, "downloaded": r.downloaded, "rolls": as_dict(r.rolls),
                "queued": queued}, "\n".join(lines))
    if args.run:                      # develop + publish, as one mfilmctl worker pass
        args.max_jobs, args.jobs, args.no_publish = None, None, False
        return _worker_pass(args)
    return 1 if any(x.status in ("INVALID", "CONFLICT", "INCOMPLETE") for x in r.rolls) else 0


def cmd_develop(args) -> int:
    from . import worker
    store, conn = _open(args.data_dir, args.cfg)
    try:
        q = worker.enqueue_roll(conn, args.roll_id, args.device)
    except worker.QueueError as e:
        print(str(e), file=sys.stderr)
        return 1
    results = worker.run(conn, store) if args.run else []
    _out(args, {**q, "jobs": [r.__dict__ for r in results]},
         f"queued {q['queued']}/{q['frames']} frames" + "".join(
             f"\n  job {r.job_id} {r.state}" + (f" {r.error_code}: {r.detail}" if r.error_code else "")
             for r in results))
    return 0 if all(r.state == "COMMITTED" for r in results) else 1


def _publish_ready(args, store, conn) -> list[dict]:
    """Publish every roll whose linux renders are all committed (when PhotoPrism is configured)."""
    from . import publisher
    pp = args.cfg.photoprism
    if not pp.export_dir:
        return []
    rolls = conn.execute(
        "SELECT r.device_id, r.id FROM rolls r WHERE r.state='INPUTS_COMPLETE' AND EXISTS ("
        " SELECT 1 FROM renders x JOIN frames f ON f.device_id=x.device_id AND f.id=x.frame_id"
        " WHERE f.roll_id=r.id AND f.device_id=r.device_id AND x.origin='linux' AND x.state='COMMITTED')"
        " AND NOT EXISTS (SELECT 1 FROM renders x JOIN frames f ON f.device_id=x.device_id AND f.id=x.frame_id"
        " WHERE f.roll_id=r.id AND f.device_id=r.device_id AND x.origin='linux'"
        " AND x.state IN ('QUEUED','RUNNING','FAILED_RETRYABLE','WAITING_FOR_INPUTS'))").fetchall()
    out = []
    for r in rolls:
        try:
            res = publisher.publish_roll(conn, store, pp, r["id"], r["device_id"])
            out.append({"roll_id": r["id"], "published": [x.__dict__ for x in res]})
        except publisher.PublishError as e:
            out.append({"roll_id": r["id"], "error": str(e)})
    return out


def cmd_worker(args) -> int:
    if args.watch:
        import time
        while True:                   # systemd restarts us on crash; SIGTERM ends the loop
            _worker_pass(args)
            time.sleep(args.interval)
    return _worker_pass(args)


def _worker_pass(args) -> int:
    from . import publisher, worker
    store, conn = _open(args.data_dir, args.cfg)
    results = worker.run(conn, store, max_jobs=args.max_jobs, jobs=args.jobs or args.cfg.jobs)
    published = [] if args.no_publish else _publish_ready(args, store, conn)
    exported = [x["render_id"] for p in published for x in p.get("published", []) if x["status"] == "EXPORTED"]
    indexed = publisher.run_index(conn, args.cfg.photoprism, exported) if exported else (False, "nothing new")
    _out(args, {"jobs": [r.__dict__ for r in results], "published": published,
                "index": {"ok": indexed[0], "log": indexed[1]}},
         "\n".join([f"job {r.job_id} {r.state} {r.render_id[:16]}" + (f" {r.error_code}: {r.detail}" if r.error_code else "")
                    for r in results] or ["queue empty"])
         + "".join(f"\npublished {sum(x['status'] == 'EXPORTED' for x in p.get('published', []))} of roll {p['roll_id']}"
                   + (f" ERROR {p['error']}" if "error" in p else "") for p in published))
    conn.close()
    return 0 if all(r.state == "COMMITTED" for r in results) else 1


def cmd_publish(args) -> int:
    from . import publisher
    store, conn = _open(args.data_dir, args.cfg)
    try:
        res = publisher.publish_roll(conn, store, args.cfg.photoprism, args.roll_id, args.device)
    except publisher.PublishError as e:
        print(str(e), file=sys.stderr)
        return 1
    idx = (False, "skipped")
    new = [x.render_id for x in res if x.status == "EXPORTED"]
    if args.index and new:
        idx = publisher.run_index(conn, args.cfg.photoprism, new)
    _out(args, {"published": [x.__dict__ for x in res], "index": {"ok": idx[0], "log": idx[1]}},
         "\n".join(f"{x.status:8} {x.path}" + (f" ({x.detail})" if x.detail else "") for x in res)
         or "nothing committed to publish")
    return 0 if res and all(x.status != "FAILED" for x in res) else 1


def cmd_reprocess(args) -> int:
    """Queue new renditions of a roll with another film / look / bundle. Old ones stay."""
    from . import core, worker
    from .bundles import Bundles
    store, conn = _open(args.data_dir, args.cfg)
    bundles = Bundles(store)
    try:
        roll = worker.find_roll(conn, args.roll_id, args.device)
        bundle_hash = args.bundle
        if bundle_hash == "current":
            bundle_hash = bundles.ensure_default()
            if not bundle_hash:
                raise worker.QueueError("this checkout has no profiles/mfilm-films.bin")
        recipe = worker.build_recipe(
            roll, profile=args.profile, bundle_hash=bundle_hash, exposure_ev=args.exposure_ev, user_seed=args.seed,
            look={"grain_scale": args.grain_scale, "halation_scale": args.halation_scale,
                  "softness_scale": args.softness_scale})
        keys = bundles.get(recipe["profile_bundle_hash"]).keys
        if recipe["film_profile_id"] not in keys:
            raise worker.QueueError(f"film {recipe['film_profile_id']} is not in bundle "
                                    f"{recipe['profile_bundle_hash'][:12]} (mfilmctl bundle-list)")
        q = worker.enqueue_roll(conn, roll["id"], roll["device_id"], recipe)
    except (worker.QueueError, core.CoreError) as e:
        print(str(e), file=sys.stderr)
        return 1
    results = worker.run(conn, store) if args.run else []
    msg = (f"queued {q['queued']}/{q['frames']} new renditions ({q['recipe_id']})" if q["queued"]
           else f"nothing new: renditions for {q['recipe_id']} already exist")
    _out(args, {**q, "jobs": [r.__dict__ for r in results]}, msg + "".join(
        f"\n  job {r.job_id} {r.state}" + (f" {r.error_code}: {r.detail}" if r.error_code else "") for r in results))
    return 0 if all(r.state == "COMMITTED" for r in results) else 1


def cmd_bundle_add(args) -> int:
    from . import core, worker
    from .bundles import Bundles
    store, conn = _open(args.data_dir, args.cfg)
    try:
        sha, new = Bundles(store).add(Path(args.file), Path(args.films_json) if args.films_json else None)
    except (core.CoreError, OSError) as e:
        print(f"rejected: {e}", file=sys.stderr)
        return 1
    _, unparked = worker.park_and_unpark(conn, Bundles(store))
    _out(args, {"profile_bundle_hash": sha, "added": new, "requeued_jobs": unparked},
         f"{'added' if new else 'already archived'} {sha}" + (f"; {unparked} waiting job(s) re-queued" if unparked else ""))
    return 0


def cmd_bundle_list(args) -> int:
    from .bundles import Bundles
    store, conn = _open(args.data_dir, args.cfg)
    rows = Bundles(store).list()
    used = {r[0]: r[1] for r in conn.execute("SELECT profile_bundle_hash, COUNT(*) FROM rolls GROUP BY 1")}
    for r in rows:
        r["rolls"] = used.pop(r["profile_bundle_hash"], 0)
        r.pop("keys", None)
    missing = [{"profile_bundle_hash": h, "rolls": n, "error": "NOT_ARCHIVED"} for h, n in used.items()]
    _out(args, rows + missing, "\n".join(
        f"{r['profile_bundle_hash']}  " + (f"{r['films']} films" if "films" in r else r["error"])
        + f", {r['rolls']} roll(s)" + ("  (current)" if r.get("current") else "") for r in rows + missing)
        or "no bundles archived")
    return 1 if missing else 0


def cmd_device_pair(args) -> int:
    from . import devices
    _, conn = _open(args.data_dir, args.cfg)
    token = devices.pair(conn, args.name)
    _out(args, {"device_id": args.name, "token": token},
         f"device {args.name} paired. Token (shown once, put it on the camera card):\n{token}")
    return 0


def cmd_device_revoke(args) -> int:
    from . import devices
    _, conn = _open(args.data_dir, args.cfg)
    n = devices.revoke(conn, args.name)
    _out(args, {"device_id": args.name, "revoked_tokens": n}, f"revoked {n} token(s) of {args.name}")
    return 0


def cmd_camera_card(args) -> int:
    from .camera_card import write_card
    for p in write_card(Path(args.out), utc_offset=args.utc_offset, bench=args.bench):
        print(p)
    return 0


def cmd_list_rolls(args) -> int:
    _, conn = _open(args.data_dir, args.cfg)
    q = ("SELECT r.device_id, r.id, r.film_profile_id, r.state, r.expected_frames, "
         "SUM(f.original_state='VERIFIED') AS verified, "
         "(SELECT COUNT(*) FROM renders x JOIN frames y ON y.device_id=x.device_id AND y.id=x.frame_id "
         " WHERE y.device_id=r.device_id AND y.roll_id=r.id AND x.origin='linux' AND x.state IN ('COMMITTED','PUBLISHED')) AS developed "
         "FROM rolls r LEFT JOIN frames f ON f.device_id=r.device_id AND f.roll_id=r.id ")
    params: tuple = ()
    if args.state:
        q += "WHERE r.state=? "
        params = (args.state,)
    rows = [dict(r) for r in conn.execute(q + "GROUP BY r.device_id, r.id ORDER BY r.received_at", params)]
    _out(args, rows, "\n".join(f"{r['state']:16} {r['device_id']}/{r['id']}  {r['film_profile_id']}  "
                               f"{r['verified'] or 0}/{r['expected_frames']} verified, {r['developed']} developed" for r in rows) or "no rolls")
    return 0


def cmd_verify(args) -> int:
    """Re-hash every archived original of a roll against the catalog."""
    store, conn = _open(args.data_dir, args.cfg)
    rows = conn.execute(
        "SELECT f.id, f.ordinal, a.sha256, a.path FROM frames f JOIN assets a ON a.id=f.original_asset_id "
        "WHERE f.roll_id=? ORDER BY f.ordinal", (args.roll_id,)).fetchall()
    report = []
    for r in rows:
        p = store.root / r["path"]
        have = sha256_file(p)[0] if p.is_file() else None
        report.append({"frame_id": r["id"], "ordinal": r["ordinal"], "ok": have == r["sha256"],
                       "expected": r["sha256"], "actual": have})
    ok = bool(report) and all(x["ok"] for x in report)
    _out(args, {"roll_id": args.roll_id, "ok": ok, "frames": report},
         "\n".join(f"#{x['ordinal']:02} {'OK ' if x['ok'] else 'BAD'} {x['frame_id']}" for x in report)
         or f"no archived frames for roll {args.roll_id}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default=None, help="server data root (config data_dir, env MFILM_DATA_DIR)")
    common.add_argument("--config", default=None, help="config.toml (env MFILM_CONFIG)")
    common.add_argument("--json", action="store_true", help="machine-readable output")
    p = argparse.ArgumentParser(prog="mfilmctl")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", parents=[common]).set_defaults(fn=cmd_init)
    s = sub.add_parser("import-card", parents=[common], help="import sealed rolls from a mounted SD card")
    s.add_argument("card")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("-v", "--verbose", action="store_true")
    s.add_argument("--no-develop", action="store_true", help="do not queue complete rolls for development")
    s.set_defaults(fn=cmd_import_card)
    s = sub.add_parser("develop", parents=[common], help="queue a roll's frames (and --run the worker)")
    s.add_argument("roll_id")
    s.add_argument("--device")
    s.add_argument("--run", action="store_true")
    s.set_defaults(fn=cmd_develop)
    s = sub.add_parser("worker", parents=[common], help="develop queued frames, then publish finished rolls")
    s.add_argument("--max-jobs", type=int)
    s.add_argument("--jobs", type=int, help="frames developed at once (config [worker] jobs; ~0.9 GB each)")
    s.add_argument("--no-publish", action="store_true")
    s.add_argument("--watch", action="store_true", help="keep polling the queue (service mode)")
    s.add_argument("--interval", type=float, default=30.0, help="seconds between passes with --watch")
    s.set_defaults(fn=cmd_worker)
    s = sub.add_parser("device-pair", parents=[common], help="register a camera and issue its token")
    s.add_argument("--name", required=True, help="device_id, e.g. sx510hs")
    s.set_defaults(fn=cmd_device_pair)
    s = sub.add_parser("device-revoke", parents=[common], help="revoke all tokens of a camera")
    s.add_argument("--name", required=True)
    s.set_defaults(fn=cmd_device_revoke)
    s = sub.add_parser("publish", parents=[common], help="copy a roll's committed renders into PhotoPrism")
    s.add_argument("roll_id")
    s.add_argument("--device")
    s.add_argument("--index", action="store_true", help="run photoprism.index_command afterwards")
    s.set_defaults(fn=cmd_publish)
    s = sub.add_parser("reprocess", parents=[common],
                       help="new renditions of a roll with another film/look (old ones are kept)")
    s.add_argument("roll_id")
    s.add_argument("--device")
    s.add_argument("--profile", help="film key (default: the roll's film)")
    s.add_argument("--bundle", help="profile bundle hash, or 'current' (default: the roll's own bundle)")
    s.add_argument("--grain-scale", type=float)
    s.add_argument("--halation-scale", type=float)
    s.add_argument("--softness-scale", type=float)
    s.add_argument("--exposure-ev", type=float)
    s.add_argument("--seed", type=int, help="user seed: another grain pattern")
    s.add_argument("--run", action="store_true")
    s.set_defaults(fn=cmd_reprocess)
    s = sub.add_parser("bundle-add", parents=[common], help="archive a profile bundle (mfilm-films.bin)")
    s.add_argument("file")
    s.add_argument("--films-json", help="its films.json (default: next to the file)")
    s.set_defaults(fn=cmd_bundle_add)
    sub.add_parser("bundle-list", parents=[common], help="archived bundles and rolls that need one").set_defaults(
        fn=cmd_bundle_list)
    s = sub.add_parser("camera-sync", parents=[common],
                       help="pull sealed rolls from the camera with chdkptp (USB, or Wi-Fi with --host)")
    s.add_argument("--host", help="camera IP for Wi-Fi (PTP/IP); default [camera] host, else USB")
    s.add_argument("--usb", action="store_true", help="force USB even if [camera] host is set")
    s.add_argument("--mirror", help="local mirror of the card (default <data_dir>/camera-mirror/<host|usb>)")
    s.add_argument("--run", action="store_true", help="then develop and publish (like mfilmctl worker)")
    s.set_defaults(fn=cmd_camera_sync)
    s = sub.add_parser("camera-card", parents=[common], help="lay out the M-Film camera app files to copy onto a CHDK card")
    s.add_argument("out")
    s.add_argument("--utc-offset", help="camera clock offset, e.g. +02:00 (default: this host's)")
    s.add_argument("--bench", action="store_true", help="also the MFBENCH module and probe (tools/build_chdk.sh)")
    s.set_defaults(fn=cmd_camera_card)
    s = sub.add_parser("list-rolls", parents=[common])
    s.add_argument("--state", choices=db.ROLL_SERVER_STATES)
    s.set_defaults(fn=cmd_list_rolls)
    s = sub.add_parser("verify", parents=[common])
    s.add_argument("roll_id")
    s.set_defaults(fn=cmd_verify)
    for name in NOT_IMPLEMENTED:
        s = sub.add_parser(name, help="not implemented yet")
        s.add_argument("rest", nargs=argparse.REMAINDER)
        s.set_defaults(fn=None, name=name)
    args = p.parse_args(argv)
    if args.fn is not None:
        args.cfg = config_mod.load(args.config)
        if args.data_dir is None and "MFILM_DATA_DIR" in os.environ:
            args.data_dir = os.environ["MFILM_DATA_DIR"]
    if args.fn is None:
        print(f"mfilmctl {args.name}: NOT IMPLEMENTED (see docs/14 roadmap)", file=sys.stderr)
        return 3
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
