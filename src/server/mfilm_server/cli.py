# SPDX-License-Identifier: GPL-2.0-only
"""mfilmctl: admin CLI (docs/08). Exit codes: 0 ok, 1 problems found, 2 usage, 3 not implemented."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import db
from .ids import sha256_file
from .importer import as_dict, import_card
from .store import Store

DEFAULT_ROOT = os.environ.get("MFILM_DATA_DIR", "/var/lib/mfilm")
NOT_IMPLEMENTED = ("publish", "device-pair", "reprocess")


def _open(root: str) -> tuple[Store, "db.sqlite3.Connection"]:
    store = Store(Path(root))
    store.init()
    conn = db.connect(store.db_path)
    db.migrate(conn)
    return store, conn


def _out(args, payload, text: str) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json else text)


def cmd_init(args) -> int:
    store, conn = _open(args.data_dir)
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    _out(args, {"data_dir": str(store.root), "schema_version": v}, f"initialised {store.root} (schema v{v})")
    return 0


def cmd_import_card(args) -> int:
    store, conn = _open(args.data_dir)
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


def cmd_develop(args) -> int:
    from . import worker
    store, conn = _open(args.data_dir)
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


def cmd_worker(args) -> int:
    from . import worker
    store, conn = _open(args.data_dir)
    results = worker.run(conn, store, max_jobs=args.max_jobs)
    _out(args, [r.__dict__ for r in results], "\n".join(
        f"job {r.job_id} {r.state} {r.render_id[:16]}" + (f" {r.error_code}: {r.detail}" if r.error_code else "")
        for r in results) or "queue empty")
    return 0 if all(r.state == "COMMITTED" for r in results) else 1


def cmd_list_rolls(args) -> int:
    _, conn = _open(args.data_dir)
    q = ("SELECT r.device_id, r.id, r.film_profile_id, r.state, r.expected_frames, "
         "SUM(f.original_state='VERIFIED') AS verified, "
         "(SELECT COUNT(*) FROM renders x JOIN frames y ON y.device_id=x.device_id AND y.id=x.frame_id "
         " WHERE y.device_id=r.device_id AND y.roll_id=r.id AND x.origin='linux' AND x.state='COMMITTED') AS developed "
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
    store, conn = _open(args.data_dir)
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
    common.add_argument("--data-dir", default=DEFAULT_ROOT, help="server data root (env MFILM_DATA_DIR)")
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
    s = sub.add_parser("worker", parents=[common], help="develop queued frames until the queue is empty")
    s.add_argument("--max-jobs", type=int)
    s.set_defaults(fn=cmd_worker)
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
    if args.fn is None:
        print(f"mfilmctl {args.name}: NOT IMPLEMENTED (see docs/14 roadmap)", file=sys.stderr)
        return 3
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
