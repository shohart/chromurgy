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

    def add_photo(self, uid: str, folder: str, name: str, *, kind="raw", ext=".DNG", src: Path | None = None,
                  raw_missing=False):
        d = self.root / folder
        d.mkdir(parents=True, exist_ok=True)
        files = []
        if kind == "raw":
            raw = d / f"{name}{ext}"
            if src:
                raw.write_bytes(src.read_bytes())
            if not raw_missing:
                files.append({"UID": f"f{uid}r", "Name": f"{folder}/{name}{ext}", "Root": "/", "Hash": sha1(raw),
                              "Primary": False, "FileType": "raw", "MediaType": "raw", "Size": raw.stat().st_size,
                              "Sidecar": None, "Missing": None})
            files.append({"UID": f"f{uid}j", "Name": f"{folder}/{name}{ext}.jpg", "Root": "sidecar", "Hash": "j" * 40,
                          "Primary": True, "FileType": "jpg", "MediaType": "image", "Size": 1, "Sidecar": None})
        else:                                           # JPEG-only photo
            jpg = d / f"{name}.jpg"
            jpg.write_bytes(b"\xff\xd8\xff" + b"0" * 100)
            files.append({"UID": f"f{uid}j", "Name": f"{folder}/{name}.jpg", "Root": "/", "Hash": sha1(jpg),
                          "Primary": True, "FileType": "jpg", "MediaType": "image", "Size": jpg.stat().st_size})
        self.photos[uid] = {"UID": uid, "Type": "raw" if kind == "raw" else "image", "Path": folder, "Name": name,
                            "TakenAt": "2015-11-10T23:42:23Z", "Files": files, "Albums": []}

    def add_album(self, uid: str, title: str, members: list[str]):
        self.albums[uid] = {"UID": uid, "Title": title, "Type": "album", "Filter": "", "PhotoCount": len(members),
                            "members": list(members)}

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
            return 200, [{k: v for k, v in p.items() if k != "Files"} for p in sel[off:off + cnt]]
        if method == "GET" and path.startswith("photos/"):
            uid = path.split("/", 1)[1]
            return (200, self.photos[uid]) if uid in self.photos else (404, {"error": "not found"})
        if method == "POST" and path == "albums":
            uid = f"a{len(self.albums) + 1}"
            self.add_album(uid, body["Title"], [])
            return 200, {"UID": uid, "Title": body["Title"]}
        if method == "POST" and path.startswith("albums/") and path.endswith("/photos"):
            a = self.albums[path.split("/")[1]]
            a["members"] += [u for u in body["photos"] if u not in a["members"]]
            return 200, {"code": 200}
        if method == "POST" and path == "batch/albums/delete":
            for u in body["albums"]:
                self.albums.pop(u, None)
            return 200, {"code": 200}
        return 404, {"error": f"unexpected {method} {path}"}
