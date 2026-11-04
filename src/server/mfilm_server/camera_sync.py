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

from .importer import IMPORTABLE_CAMERA_STATES, MFILM_DIR, RollResult, card_source, import_card
from .store import Store, UnsafePath

DEFAULT_CHDKPTP = ("docker run --rm --network host --privileged -v /dev/bus/usb:/dev/bus/usb "
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


def _chdkptp(cmd_template: str, mirror: Path, commands: list[str], timeout: int) -> str:
    argv = shlex.split(cmd_template.format(mirror=str(mirror)))
    for c in commands:
        argv.append(f"-e{c}")
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as e:
        raise SyncError("CHDKPTP_NOT_FOUND", str(e)) from None
    except subprocess.TimeoutExpired:
        raise SyncError("CHDKPTP_TIMEOUT", f"after {timeout} s") from None
    out = p.stdout + p.stderr
    low = out.lower()
    if p.returncode != 0 or "no matching devices" in low or "connection failed" in low or "not connected" in low:
        raise SyncError("CAMERA_NOT_CONNECTED" if "connect" in low or "devices" in low else "CHDKPTP_FAILED",
                        out.strip()[-800:])
    return out


def _connect(host: str | None) -> str:
    return f"connect -h={host}" if host else "connect"


def _q(s: str) -> str:
    if '"' in s:
        raise SyncError("BAD_PATH", s)
    return f'"{s}"'


def wanted_files(card: Path, conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """(camera path, size) of the DNGs of sealed rolls not yet fully imported."""
    out = []
    base = card / MFILM_DIR
    for m in sorted(base.glob("*/manifest.json")) if base.is_dir() else []:
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
    # 1. roll metadata (small): mdownload puts the contents of A/CHDK/MFILM/ROLLS into the target
    res.log += _chdkptp(tmpl, mirror, [_connect(host),
                                       f"mdl -overwrite=y {_q('A/' + str(MFILM_DIR))} {_q(str(card / MFILM_DIR))}"],
                        timeout)
    # 2. originals the sealed rolls need
    want = wanted_files(card, conn)
    if want:
        cmds = [_connect(host)]
        for src, _ in want:
            dst = card_source(card, src)
            dst.parent.mkdir(parents=True, exist_ok=True)
            part = dst.with_name(dst.name + ".part")
            cmds.append(f"d {_q(src)} {_q(str(part))}")
        res.log += _chdkptp(tmpl, mirror, cmds, timeout)
        for src, size in want:
            dst = card_source(card, src)
            part = dst.with_name(dst.name + ".part")
            if part.is_file() and part.stat().st_size == size:
                part.replace(dst)
                res.downloaded.append(src)
            elif part.exists():
                part.unlink()
    # 3. the same import as an SD card
    res.rolls = import_card(card, store, conn)
    return res
