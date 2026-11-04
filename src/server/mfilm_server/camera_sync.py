# SPDX-License-Identifier: GPL-2.0-only
"""Pull sealed rolls straight from the camera with chdkptp (docs/10 phase B/C):
over USB, or over Wi-Fi (PTP/IP) after the camera has been paired with this
server ("Connect to computer" in the Canon Wi-Fi menu, answered by the
ptpip-canon-upnp-helper running on the server).

    mfilmctl camera-sync [--host CAMERA_IP] [--run]

1. download A/CHDK/MFILM/ROLLS (manifests, state, journals: a few KB) into a
   local mirror of the card,
2. download the DNGs that sealed rolls reference and the mirror lacks (or
   has with a different size),
3. import the mirror exactly like an SD card (importer.import_card), so all
   hashing, verification and idempotence rules are the same.

Nothing on the camera is changed or deleted. chdkptp runs from the
mfilm-chdkptp image (deploy/chdkptp) unless [camera] chdkptp says otherwise.
"""
from __future__ import annotations

import json
import shlex
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .importer import IMPORTABLE_CAMERA_STATES, MFILM_DIR, RollResult, card_source, find_manifests, import_card
from .store import Store, UnsafePath

DEFAULT_CHDKPTP = ("docker run --rm -i --network host --privileged -v /dev/bus/usb:/dev/bus/usb "
                   "-v {mirror}:{mirror} mfilm-chdkptp")


class SyncError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass
class SyncResult:
    connection: str
    downloaded: list[str] = field(default_factory=list)
    rolls: list[RollResult] = field(default_factory=list)
    log: str = ""


class _Session:
    """One interactive chdkptp process for the whole sync. Over Wi-Fi the
    SX510 HS accepts one PTP/IP connection per Canon "connect" (a second
    connection after a disconnect times out, 2026-11-04), so everything runs
    in one session: each command is followed by a local marker print and the
    output is read up to it."""

    def __init__(self, cmd_template: str, mirror: Path, timeout: int):
        import queue
        import threading
        argv = shlex.split(cmd_template.format(mirror=str(mirror))) + ["-i"]
        try:
            self.p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, bufsize=1)
        except FileNotFoundError as e:
            raise SyncError("CHDKPTP_NOT_FOUND", str(e)) from None
        self.q: queue.Queue = queue.Queue()
        self.timeout, self.n, self.log = timeout, 0, ""

        def pump():
            for line in self.p.stdout:
                self.q.put(line)
            self.q.put(None)
        threading.Thread(target=pump, daemon=True).start()

    def cmd(self, c: str, timeout: int | None = None) -> str:
        import queue
        import time
        self.n += 1
        mark = f"@@MFILM{self.n}@@"
        try:
            self.p.stdin.write(f"{c}\n!print('{mark}')\n")
            self.p.stdin.flush()
        except (BrokenPipeError, OSError):
            raise SyncError("CHDKPTP_FAILED", self.log[-800:]) from None
        out, end = [], time.monotonic() + (timeout or self.timeout)
        while True:
            try:
                line = self.q.get(timeout=max(0.1, end - time.monotonic()))
            except queue.Empty:
                raise SyncError("CHDKPTP_TIMEOUT", f"{c}: no answer") from None
            if line is None:
                raise SyncError("CHDKPTP_FAILED", ("".join(out) + self.log)[-800:])
            if mark in line and not line.lstrip().startswith(("___>", "con")) or line.strip() == mark:
                break
            out.append(line)
        text = "".join(out)
        self.log += f"> {c}\n{text}"
        return text

    def close(self):
        try:
            self.p.stdin.write("dis\nquit\n")
            self.p.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        try:
            self.p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.p.kill()


def _connect(host: str | None) -> str:
    return f"connect -h={host}" if host else "connect"


def _q(s: str) -> str:
    if '"' in s:
        raise SyncError("BAD_PATH", s)
    return f'"{s}"'


def wanted_files(card: Path, conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """(camera path, size) of the DNGs of sealed rolls not yet fully imported."""
    out = []
    for m in find_manifests(card):
        try:
            doc = json.loads(m.read_text())
        except (OSError, ValueError):
            continue
        if doc.get("roll_state") not in IMPORTABLE_CAMERA_STATES:
            continue
        row = conn.execute("SELECT state FROM rolls WHERE device_id=? AND id=?",
                           (doc.get("device_id"), doc.get("roll_id"))).fetchone()
        if row and row["state"] != "RECEIVING":
            continue
        for fr in doc.get("frames", []):
            try:
                local = card_source(card, fr["source_path"])
            except (UnsafePath, KeyError):
                continue
            size = int(fr.get("source_size_bytes", 0))
            if not local.is_file() or local.stat().st_size != size:
                out.append((fr["source_path"], size))
    return out


def sync(store: Store, conn: sqlite3.Connection, *, host: str | None = None, mirror: Path | None = None,
         chdkptp: str | None = None, timeout: int = 3600) -> SyncResult:
    name = host or "usb"
    mirror = Path(mirror or store.root / "camera-mirror" / name.replace(":", "_")).resolve()
    card = mirror / "A"
    (card / MFILM_DIR).mkdir(parents=True, exist_ok=True)
    tmpl = chdkptp or DEFAULT_CHDKPTP
    res = SyncResult(connection=name)
    ses = _Session(tmpl, mirror, timeout)
    try:
        out = ses.cmd(_connect(host), timeout=60)
        if "connected:" not in out:
            raise SyncError("CAMERA_NOT_CONNECTED", out.strip()[-800:])
        # a running camera script (the M-Film app) blocks chdkptp's remote calls
        ses.cmd("killscript", timeout=30)
        # 1. roll metadata (small): mdownload puts the contents of A/CHDK/MFILM/ROLLS into the target
        out = ses.cmd(f"mdl -overwrite=y {_q('A/' + str(MFILM_DIR))} {_q(str(card / MFILM_DIR))}")
        if "ERROR" in out and "no matching files" not in out:
            raise SyncError("CHDKPTP_FAILED", out.strip()[-800:])
        # 2. originals the sealed rolls need
        for src, size in wanted_files(card, conn):
            dst = card_source(card, src)
            dst.parent.mkdir(parents=True, exist_ok=True)
            part = dst.with_name(dst.name + ".part")
            ses.cmd(f"d {_q(src)} {_q(str(part))}")
            if part.is_file() and part.stat().st_size == size:
                part.replace(dst)
                res.downloaded.append(src)
            elif part.exists():
                part.unlink()
    finally:
        ses.close()
        res.log = ses.log
    # 3. the same import as an SD card
    res.rolls = import_card(card, store, conn)
    return res
