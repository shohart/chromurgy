"""In-process PhotoPrism for tests: the response shapes observed on 260728 Plus (docs/audit W01).
Serves a tiny library whose originals are real files in a temp directory."""
import hashlib
from pathlib import Path


def sha1(p: Path) -> str:
    return hashlib.sha1(p.read_bytes()).hexdigest()


class FakePhotoPrism:
    def __init__(self, originals: Path):
        self.root = originals
        self.photos: dict[str, dict] = {}
        self.albums: dict[str, dict] = {}
        self.calls: list[tuple] = []
        self.deny_albums = False
        self.offline = False
        self.thumb_rev: dict[str, int] = {}

    def add_photo(self, uid: str, folder: str, name: str, *, kind="raw", ext=".DNG", src: Path | None = None,
                  raw_missing=False):
        d = self.root / folder
        d.mkdir(parents=True, exist_ok=True)
        files = []
        jhash = hashlib.sha1(f"jpg:{uid}:v1".encode()).hexdigest()
        if kind == "raw":
            raw = d / f"{name}{ext}"
            if src:
                raw.write_bytes(src.read_bytes())
            if not raw_missing:
                files.append({"UID": f"f{uid}r", "Name": f"{folder}/{name}{ext}", "Root": "/", "Hash": sha1(raw),
                              "Primary": False, "FileType": "raw", "MediaType": "raw", "Size": raw.stat().st_size,
                              "Sidecar": None, "Missing": None, "UpdatedAt": "2026-11-08T18:00:00Z"})
            files.append({"UID": f"f{uid}j", "Name": f"{folder}/{name}{ext}.jpg", "Root": "sidecar", "Hash": jhash,
                          "Primary": True, "FileType": "jpg", "MediaType": "image", "Size": 1, "Sidecar": None,
                          "UpdatedAt": "2026-11-08T18:00:00Z"})
        else:                                           # JPEG-only photo
            jpg = d / f"{name}.jpg"
            jpg.write_bytes(b"\xff\xd8\xff" + b"0" * 100)
            jhash = sha1(jpg)
            files.append({"UID": f"f{uid}j", "Name": f"{folder}/{name}.jpg", "Root": "/", "Hash": jhash,
                          "Primary": True, "FileType": "jpg", "MediaType": "image", "Size": jpg.stat().st_size,
                          "UpdatedAt": "2026-11-08T18:00:00Z"})
        self.photos[uid] = {"UID": uid, "Type": "raw" if kind == "raw" else "image", "Path": folder, "Name": name,
                            "Hash": jhash, "UpdatedAt": "2026-11-08T18:00:00Z",
                            "TakenAt": "2015-11-10T23:42:23Z", "Files": files, "Albums": []}

    def update_preview(self, uid: str, *, updated_at: str = "2026-11-08T19:30:00Z", new_hash: str | None = None):
        ph = self.photos[uid]
        prim = next(f for f in ph["Files"] if f.get("Primary"))
        th = new_hash or prim["Hash"]
        prim["Hash"] = th
        prim["UpdatedAt"] = updated_at
        ph["Hash"] = th
        ph["UpdatedAt"] = updated_at
        self.thumb_rev[th] = self.thumb_rev.get(th, 1) + 1

    def add_album(self, uid: str, title: str, members: list[str]):
        th = self.photos[members[0]]["Hash"] if members and members[0] in self.photos else ""
        self.albums[uid] = {"UID": uid, "Title": title, "Type": "album", "Filter": "", "PhotoCount": len(members),
                            "Thumb": th, "members": list(members)}

    def __call__(self, method, path, params, body):
        self.calls.append((method, path, params, body))
        if self.offline:
            from mfilm_server.darkroom.photoprism import PPError
            raise PPError("PHOTOPRISM_OFFLINE", "connection refused")
        params = params or {}
        if method == "GET" and path == "config":
            return 200, {"version": "fake", "edition": "plus", "readonly": True}
        if method == "GET" and path == "albums":
            if self.deny_albums:
                return 400, {"error": "Permission denied"}
            q = params.get("q", "").lower()
            return 200, [a for a in self.albums.values() if q in a["Title"].lower()]
        if method == "GET" and path.startswith("folders/originals"):
            parent = path[len("folders/originals"):].strip("/")
            subs = sorted({str(p.relative_to(self.root)) for p in (self.root / parent).iterdir() if p.is_dir()
                           and not p.name.startswith(".")}) if (self.root / parent).is_dir() else []
            return 200, {"root": "/", "folders": [{"Path": s, "Title": s.rsplit("/", 1)[-1], "UID": "d" + s, "FileCount": 0}
                                                   for s in subs]}
        if method == "GET" and path == "photos":
            if "s" in params:
                members = self.albums.get(params["s"], {"members": []})["members"]
                sel = [self.photos[u] for u in members]
            else:
                sel = [p for p in self.photos.values() if p["Path"] == params.get("path", "")]
            off, cnt = int(params.get("offset", 0)), int(params.get("count", 100))
            if params.get("merged") == "true":
                rows = [(p, f) for p in sel for f in (p.get("Files") or [None])]
                sliced = rows[off:off + cnt]
                merged: dict[str, dict] = {}
                for p, f in sliced:
                    if p["UID"] not in merged:
                        merged[p["UID"]] = {**p, "Files": [f] if f else []}
                    elif f:
                        merged[p["UID"]]["Files"].append(f)
                return 200, list(merged.values())
            return 200, [{k: v for k, v in p.items() if k != "Files"} for p in sel[off:off + cnt]]
        if method == "GET" and path.startswith("photos/"):
            uid = path.split("/", 1)[1]
            return (200, self.photos[uid]) if uid in self.photos else (404, {"error": "not found"})
        if method == "GET" and path.startswith("t/"):
            parts = path.split("/")
            th = parts[1] if len(parts) > 1 else ""
            sz = parts[3] if len(parts) > 3 else "tile_500"
            rev = self.thumb_rev.get(th, 1)
            return 200, b"\xff\xd8\xff\xe0PPTHUMB:" + f"{th}:{sz}:v{rev}".encode() + b"\xff\xd9"
        if method == "POST" and path == "albums":
            uid = f"a{len(self.albums) + 1}"
            self.add_album(uid, body["Title"], [])
            return 200, {"UID": uid, "Title": body["Title"]}
        if method == "POST" and path.startswith("albums/") and path.endswith("/photos"):
            a = self.albums[path.split("/")[1]]
            a["members"] += [u for u in body["photos"] if u not in a["members"]]
            return 200, {"code": 200}
        if method == "DELETE" and path.startswith("albums/") and path.endswith("/photos"):
            a = self.albums.get(path.split("/")[1])
            if a:
                to_remove = set(body["photos"])
                a["members"] = [u for u in a["members"] if u not in to_remove]
            return 200, {"code": 200}
        if method == "POST" and path == "batch/albums/delete":
            for u in body["albums"]:
                self.albums.pop(u, None)
            return 200, {"code": 200}
        return 404, {"error": f"unexpected {method} {path}"}
