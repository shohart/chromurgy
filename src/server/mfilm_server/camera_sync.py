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
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .importer import (
    IMPORTABLE_CAMERA_STATES,
    MFILM_DIR,
    RollResult,
    card_source,
    find_manifests,
    import_card,
)
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
    failed: list[tuple[str, str]] = field(default_factory=list)   # (camera path, chdkptp's answer)
    log_path: str | None = None
    viewer_rolls: list[str] = field(default_factory=list)     # rolls whose developed frames went to the camera
    deleted: list[str] = field(default_factory=list)          # rolls the owner deleted on the camera
    app_kept: bool = False                                     # synced without stopping the camera app
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


def fetch_listed(ses: _Session, card: Path) -> bool:
    """Download ROLLS/INDEX.TXT and the files it lists into the mirror; False if
    the camera has no index (an app before 0.7)."""
    base = card / MFILM_DIR
    base.mkdir(parents=True, exist_ok=True)
    part = base / "INDEX.TXT.part"
    out = ses.cmd(f"d {_q('A/' + str(MFILM_DIR) + '/INDEX.TXT')} {_q(str(part))}")
    if "ERROR" in out or not part.is_file():
        part.unlink(missing_ok=True)              # no index, or a broken transfer: the old way
        return False
    listed = [ln.strip() for ln in part.read_text(errors="replace").splitlines() if ln.strip()]
    part.replace(base / "INDEX.TXT")
    for rel in listed:
        if ".." in rel or rel.startswith("/") or not all(c.isalnum() or c in "._/-" for c in rel):
            continue                                  # only the app's own 8.3 paths
        dst = base / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".part")
        out = ses.cmd(f"d {_q('A/' + str(MFILM_DIR) + '/' + rel)} {_q(str(tmp))}")
        if "ERROR" not in out and tmp.is_file():
            tmp.replace(dst)
        else:
            tmp.unlink(missing_ok=True)
    return True


def deleted_rolls(card: Path) -> set[str]:
    """Roll ids the owner deleted on the camera (A/CHDK/MFILM/ROLLS/DELETED.CFG, app 0.6.1+)."""
    p = card / MFILM_DIR / "DELETED.CFG"
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return set()
    return {ln[5:].split("|")[0] for ln in text.splitlines() if ln.startswith("roll=")}


def forget_deleted(card: Path) -> list[str]:
    """Drop deleted rolls from the camera mirror (mdl only adds files): their
    manifests would otherwise ask for DNGs that are gone. The server's archive,
    database and published photos are untouched."""
    gone = deleted_rolls(card)
    out = []
    for m in find_manifests(card):
        try:
            rid = json.loads(m.read_text()).get("roll_id")
        except (OSError, ValueError):
            continue
        if rid in gone:
            shutil.rmtree(m.parent, ignore_errors=True)
            out.append(rid)
    return out


def wanted_files(card: Path, conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """(camera path, size) of the DNGs of sealed rolls not yet fully imported."""
    out = []
    gone = deleted_rolls(card)
    for m in find_manifests(card):
        try:
            doc = json.loads(m.read_text())
        except (OSError, ValueError):
            continue
        if doc.get("roll_id") in gone:
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


def _device_ids(card: Path) -> set[str]:
    out = set()
    for m in find_manifests(card):
        try:
            d = json.loads(m.read_text()).get("device_id")
        except (OSError, ValueError):
            continue
        if d:
            out.add(d)
    return out


def push_viewer(ses: _Session, store: Store, conn: sqlite3.Connection, card: Path, res: SyncResult) -> None:
    """Developed frames for the camera's viewer (camera_view.py): only rolls whose set changed."""
    from . import camera_view as cv
    vroot = card / cv.VIEW_DIR
    vroot.mkdir(parents=True, exist_ok=True)
    idx_local = vroot / "INDEX.CFG"
    part = vroot / "INDEX.CFG.part"
    ses.cmd(f"d {_q('A/' + cv.VIEW_DIR + '/INDEX.CFG')} {_q(str(part))}")
    on_camera = cv.parse_index(part.read_text(errors="replace")) if part.is_file() else {}
    if part.exists():
        part.unlink()
    gone = deleted_rolls(card)
    rolls = [v for dev in sorted(_device_ids(card)) for v in cv.developed_rolls(conn, store, dev)
             if v.roll_id not in gone]
    if not rolls:
        return
    lua = not res.app_kept                        # with the app running Lua is refused: the app made the folders
    if lua:
        ses.cmd(f"mkdir {_q('A/' + cv.VIEW_DIR)}")
    for v in rolls:
        if on_camera.get(v.roll_id) == v.set_hash():
            continue
        rdir = vroot / v.dir8
        rdir.mkdir(parents=True, exist_ok=True)
        if lua:
            ses.cmd(f"mkdir {_q(f'A/{cv.VIEW_DIR}/{v.dir8}')}")
        ok = True
        for i, src in enumerate(v.frames, 1):
            f = rdir / f"F{i:02d}.MFV"
            f.write_bytes(cv.mfv_from_jpeg(src))
            out = ses.cmd(f"u {_q(str(f))} {_q(f'A/{cv.VIEW_DIR}/{v.dir8}/{f.name}')}")
            if "ERROR" in out or "failed" in out:
                ok = False
                res.failed.append((f"viewer {v.dir8}/{f.name}", out.strip()[-200:]))
                break
        if ok:
            on_camera[v.roll_id] = v.set_hash()
            res.viewer_rolls.append(v.roll_id)
    # the index lists only rolls whose frames are all on the camera
    lines = [v.index_line() for v in rolls if on_camera.get(v.roll_id) == v.set_hash()]
    idx_local.write_text("\n".join(lines) + "\n")
    ses.cmd(f"u {_q(str(idx_local))} {_q('A/' + cv.VIEW_DIR + '/INDEX.CFG')}")


def sync(store: Store, conn: sqlite3.Connection, *, host: str | None = None, mirror: Path | None = None,
         chdkptp: str | None = None, timeout: int = 3600, develop=None) -> SyncResult:
    """develop(rolls): optional callable run after the import while the camera is still
    connected (camera-sync --run develops the new frames), so the developed
    frames can go back to the camera's viewer in the same session."""
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
        # 1. roll metadata (small). App 0.7+ lists it in ROLLS/INDEX.TXT, so plain
        #    file downloads do -- they work while the app runs (Lua commands do
        #    not). Older apps: stop the script, mdownload the folder.
        res.app_kept = fetch_listed(ses, card)
        if not res.app_kept:
            ses.cmd("killscript", timeout=30)
            out = ses.cmd(f"mdl -overwrite=y {_q('A/' + str(MFILM_DIR))} {_q(str(card / MFILM_DIR))}")
            if "ERROR" in out and "no matching files" not in out:
                raise SyncError("CHDKPTP_FAILED", out.strip()[-800:])
        res.deleted = forget_deleted(card)
        # 2. originals the sealed rolls need
        # a failed file is tried once more at the end; what chdkptp said is
        # kept (camera session 2026-11-04: a first session got 3 of 18 files
        # and left no trace why)
        todo = wanted_files(card, conn)
        for attempt in (1, 2):
            failed = []
            for src, size in todo:
                dst = card_source(card, src)
                dst.parent.mkdir(parents=True, exist_ok=True)
                part = dst.with_name(dst.name + ".part")
                out = ses.cmd(f"d {_q(src)} {_q(str(part))}")
                if part.is_file() and part.stat().st_size == size:
                    part.replace(dst)
                    res.downloaded.append(src)
                    continue
                got = part.stat().st_size if part.exists() else 0
                if part.exists():
                    part.unlink()
                failed.append(((src, size), f"attempt {attempt}: got {got} of {size} bytes: "
                               + (out.strip().splitlines() or ["no output"])[-1][:200]))
            todo = [f for f, _ in failed]
            res.failed = [(f[0], why) for f, why in failed]
            if not todo:
                break
        # 3. the same import as an SD card; 4. develop (optional); 5. viewer frames back to the camera
        res.rolls = import_card(card, store, conn)
        if develop is not None:
            develop(res.rolls)
        try:
            push_viewer(ses, store, conn, card, res)
        except SyncError as e:                   # the import stands; the viewer gets them next time
            res.failed.append(("viewer", f"{e.code}: {e.detail}"[:300]))
        # what the app shows after the session (A/CHDK/MFILM/SYNC.TXT)
        imported = sum(1 for x in res.rolls if x.status == "IMPORTED")
        note = card / "CHDK" / "MFILM" / "SYNC.TXT"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(f"done {time.strftime('%Y-%m-%d %H:%M')} {imported} new roll(s), "
                        f"{len(res.downloaded)} file(s), {len(res.viewer_rolls)} to view"
                        + (f", {len(res.failed)} failed" if res.failed else "") + "\n")
        ses.cmd(f"u {_q(str(note))} {_q('A/CHDK/MFILM/SYNC.TXT')}")
    finally:
        ses.close()
        res.log = ses.log
        try:
            logs = store.root / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            lp = logs / f"camera-sync-{time.strftime('%Y%m%d-%H%M%S')}.log"
            lp.write_text(ses.log)
            res.log_path = str(lp)
        except OSError:
            pass
    return res
