# SPDX-License-Identifier: GPL-2.0-only
"""PhotoPrism connector (docs/web/29). Server-side only: the browser never sees the token or
a PhotoPrism URL, and no request carries a user-supplied host (SSRF). Verified against
PhotoPrism 260728 Plus: Bearer app password; photos have Type 'raw' with a Files list whose RAW
entry has Root '/', Name relative to originals, Hash = SHA-1 of the file."""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from ..config import PhotoPrism as Cfg
from ..store import UnsafePath, confine

RAW_EXT = {".nef", ".dng"}                    # what the decoder is verified for (docs/web/30)
THUMB_SIZES = {"tile_224", "tile_500", "fit_720"}


class PPError(Exception):
    def __init__(self, code: str, detail: str = "", status: int = 502):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.status = code, detail, status


Transport = Callable[[str, str, dict | None, dict | None], tuple[int, object]]


def urllib_transport(base: str, token: str, timeout: float = 30.0) -> Transport:
    base = base.rstrip("/")

    def call(method: str, path: str, params: dict | None = None, body: dict | None = None):
        clean = path.lstrip("/")
        is_bin = clean.startswith("t/")
        url = f"{base}/api/v1/{clean}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        req = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {token}",
                                              "Accept": "image/jpeg, */*" if is_bin else "application/json",
                                              **({"Content-Type": "application/json"} if body is not None else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 (fixed, configured base)
                raw = r.read()
                if is_bin:
                    return r.status, raw
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"null")
            except ValueError:
                return e.code, None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise PPError("PHOTOPRISM_OFFLINE", str(getattr(e, "reason", e))) from None
    return call


class Client:
    def __init__(self, cfg: Cfg, transport: Transport | None = None):
        self.cfg = cfg
        self._preview_token: str | None = None
        if transport is None:
            if not cfg.url or not cfg.token_file:
                raise PPError("PHOTOPRISM_NOT_CONFIGURED", "set [photoprism] url and token_file", 503)
            try:
                if cfg.token_file.stat().st_mode & 0o077:
                    raise PPError("TOKEN_FILE_TOO_OPEN", f"chmod 600 {cfg.token_file}", 503)
                token = cfg.token_file.read_text().strip()
            except OSError as e:
                raise PPError("TOKEN_FILE_UNREADABLE", str(e), 503) from None
            transport = urllib_transport(cfg.url, token)
        self.t = transport

    def _get(self, _path: str, **params):
        path = _path
        status, data = self.t("GET", path, {k: v for k, v in params.items() if v not in (None, "")}, None)
        if status == 401:
            raise PPError("PHOTOPRISM_AUTH", "token rejected", 502)
        if status == 400 and isinstance(data, dict) and data.get("error") == "Permission denied":
            raise PPError("PHOTOPRISM_PERMISSION", f"the token may not read {path.split('/')[0]}", 403)
        if status >= 400:
            raise PPError("PHOTOPRISM_ERROR", f"GET {path}: HTTP {status} {data}", 502)
        return data

    # ---- read ----------------------------------------------------------------------------------
    def config(self) -> dict:
        return self._get("config")

    def preview_token(self) -> str:
        if not self._preview_token:
            pt = (self.config() or {}).get("previewToken")
            self._preview_token = str(pt) if pt else "public"
        return self._preview_token

    def thumb(self, thumb_hash: str, size: str = "tile_500") -> bytes:
        if not isinstance(thumb_hash, str) or len(thumb_hash) != 40 or not thumb_hash.isalnum():
            raise PPError("BAD_THUMB_HASH", str(thumb_hash), 400)
        if size not in THUMB_SIZES:
            raise PPError("BAD_THUMB_SIZE", size, 400)
        data = self._get(f"t/{thumb_hash}/{self.preview_token()}/{size}")
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise PPError("THUMB_EMPTY", thumb_hash, 502)
        return bytes(data)

    def albums(self, q: str = "", count: int = 100, offset: int = 0) -> list[dict]:
        rows = self._get("albums", type="album", q=q, count=count, offset=offset, order="name")
        return [{"uid": a["UID"], "title": a["Title"], "photo_count": a.get("PhotoCount", 0), "type": a.get("Type"),
                 "manual": not a.get("Filter"), "thumb": a.get("Thumb")} for a in rows]

    def folders(self, parent: str = "") -> list[dict]:
        """Direct sub-folders of `parent` (a path below originals; '' = root)."""
        data = self._get("folders/originals" + (f"/{urllib.parse.quote(parent)}" if parent else ""), recursive="false")
        return [{"path": f["Path"], "title": f["Title"], "uid": f["UID"], "file_count": f.get("FileCount", 0)}
                for f in data.get("folders", []) if not f.get("Ignore")]

    def photos(self, *, album_uid: str | None = None, folder: str | None = None, count: int = 100,
               offset: int = 0) -> list[dict]:
        """One page of photos of an album or of one folder (not recursive: merged stacks per folder)."""
        if bool(album_uid) == bool(folder is not None):
            raise PPError("BAD_REQUEST", "exactly one of album_uid / folder", 400)
        return self._get("photos", merged="true", count=count, offset=offset, s=album_uid,
                         **({"path": folder} if folder is not None else {}))

    def photo(self, uid: str) -> dict:
        return self._get(f"photos/{urllib.parse.quote(uid)}")

    # ---- write ---------------------------------------------------------------------------------
    def create_album(self, title: str) -> str:
        status, data = self.t("POST", "albums", None, {"Title": title, "Type": "album"})
        if status >= 400 or not isinstance(data, dict) or "UID" not in data:
            raise PPError("ALBUM_CREATE_FAILED", f"HTTP {status} {data}", 502 if status != 403 else 403)
        return data["UID"]

    def add_to_album(self, album_uid: str, photo_uids: list[str]) -> None:
        status, data = self.t("POST", f"albums/{urllib.parse.quote(album_uid)}/photos", None, {"photos": photo_uids})
        if status >= 400:
            raise PPError("ALBUM_ADD_FAILED", f"HTTP {status} {data}", 502)

    def remove_from_album(self, album_uid: str, photo_uids: list[str]) -> None:
        status, data = self.t("DELETE", f"albums/{urllib.parse.quote(album_uid)}/photos", None, {"photos": photo_uids})
        if status >= 400:
            raise PPError("ALBUM_REMOVE_FAILED", f"HTTP {status} {data}", 502)

    def delete_album(self, album_uid: str) -> None:
        status, data = self.t("POST", "batch/albums/delete", None, {"albums": [album_uid]})
        if status >= 400:
            raise PPError("ALBUM_DELETE_FAILED", f"HTTP {status} {data}", 502)


# ---- RAW & thumbnail resolution -------------------------------------------------------------------
def thumb_info(photo: dict | None = None, detail: dict | None = None) -> tuple[str | None, str]:
    """Return (thumb_hash, updated_at) for a PhotoPrism photo, using the primary file's SHA-1 hash
    and latest modification timestamp so preview changes in PhotoPrism are detected automatically."""
    files = (detail or photo or {}).get("Files") or []
    prim = (next((f for f in files if f.get("Primary") and f.get("Hash") and not f.get("Missing")), None)
            or next((f for f in files if f.get("Hash") and not f.get("Missing")), None))
    th = ((prim and prim.get("Hash")) or (photo or {}).get("Hash") or (detail or {}).get("Hash")
          or (photo or {}).get("Thumb") or (detail or {}).get("Thumb"))
    th = th if isinstance(th, str) and len(th) == 40 and th.isalnum() else None
    ts = [t for t in (
        prim.get("UpdatedAt") if prim else None,
        (detail or {}).get("EditedAt"), (detail or {}).get("UpdatedAt"), (detail or {}).get("CheckedAt"),
        (photo or {}).get("EditedAt"), (photo or {}).get("UpdatedAt"), (photo or {}).get("CheckedAt"),
    ) if isinstance(t, str) and t and not t.startswith("0001-")]
    return th, max(ts, default="")


def raw_file_of(detail: dict) -> tuple[dict | None, str | None]:
    """The RAW file of a photo's Files list, or (None, reason). Never assumes the primary file is RAW,
    never substitutes a sidecar or camera JPEG (docs/web/29)."""
    files = [f for f in detail.get("Files") or [] if not f.get("Sidecar") and f.get("Root", "/") == "/"
             and not f.get("Missing")]
    raws = [f for f in files if f.get("MediaType") == "raw" or f.get("FileType") == "raw"
            or Path(f.get("Name", "")).suffix.lower() in RAW_EXT]
    if not raws:
        return None, "RAW unavailable (only " + (", ".join(sorted({f.get("FileType", "?") for f in files})) or "no") + " files)"
    raws.sort(key=lambda f: f.get("Name", ""))
    f = raws[0]
    if Path(f["Name"]).suffix.lower() not in RAW_EXT:
        return None, f"unsupported RAW type {Path(f['Name']).suffix or '?'} (verified: .NEF .DNG)"
    return f, None


def local_original(originals: Path, name: str) -> Path:
    """The file below the originals mount; refuses traversal and symlinks leaving the root."""
    try:
        return confine(originals, name)
    except UnsafePath as e:
        raise PPError("UNSAFE_PATH", str(e), 400) from None


def sha1_file(path: Path) -> str:
    h = hashlib.sha1(usedforsecurity=False)
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def originals_root(cfg: Cfg) -> Path | None:
    return cfg.originals_dir or cfg.export_dir


def check_writable(root: Path, rel: str) -> str | None:
    """None when a file can be created below root/rel (temp name, removed again), else the reason."""
    d = root / rel
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / f".mfilm-write-test-{os.getpid()}"
        probe.write_bytes(b"x")
        probe.unlink()
    except OSError as e:
        return str(e)
    return None
