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
NOT_IMPLEMENTED = ("develop", "publish", "device-pair", "reprocess")


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
    lines = [f"{r.status:10} {r.device_id or '-'}/{r.roll_id or '-'}  {r.manifest}"
             + (f"  ({r.detail})" if r.detail else "")
             + "".join(f"\n    #{f.ordinal:02} {f.status}" + (f" {f.error_code}" if f.error_code else "")
                       for f in r.frames if f.status in ("ERROR",) or args.verbose)
             for r in results] or ["no roll manifests found under CHDK/MFILM/ROLLS"]
    _out(args, {"card": str(card), "dry_run": args.dry_run, "rolls": as_dict(results)}, "\n".join(lines))
    bad = any(r.status in ("INVALID", "CONFLICT", "INCOMPLETE") for r in results)
    return 1 if bad else 0


def cmd_list_rolls(args) -> int:
    _, conn = _open(args.data_dir)
    q = ("SELECT r.device_id, r.id, r.film_profile_id, r.state, r.expected_frames, "
         "SUM(f.original_state='VERIFIED') AS verified FROM rolls r "
         "LEFT JOIN frames f ON f.device_id=r.device_id AND f.roll_id=r.id ")
    params: tuple = ()
    if args.state:
        q += "WHERE r.state=? "
        params = (args.state,)
    rows = [dict(r) for r in conn.execute(q + "GROUP BY r.device_id, r.id ORDER BY r.received_at", params)]
    _out(args, rows, "\n".join(f"{r['state']:16} {r['device_id']}/{r['id']}  {r['film_profile_id']}  "
                               f"{r['verified'] or 0}/{r['expected_frames']} verified" for r in rows) or "no rolls")
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
    s.set_defaults(fn=cmd_import_card)
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
