# SPDX-License-Identifier: GPL-2.0-only
"""Fake camera: the sync client of docs/09, run against a mounted card copy.

This is the reference for what the CHDK sync_client must do, and the test
driver for the receiver. It never modifies or deletes originals; returned
renders go to <card>/CHDK/MFILM/GALLERY/<roll_id>/ via .part + hash check.

Offline development ("Develop Here", docs/07) is faked with the same shared
core: ROLLS/<roll_id>/offline/NN.jpg plus NN.json, the render record that
goes up with the JPEG as media_role=camera_render after the originals.

    python -m mfilm_server.simulator --server http://127.0.0.1:8765 --token T --card /media/card
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import httpx

from .importer import MFILM_DIR, card_source, find_manifests


class SyncError(RuntimeError):
    pass


class Camera:
    def __init__(self, client: httpx.Client, token: str, card: Path, *, chunk_limit: int | None = None):
        self.c = client
        self.h = {"Authorization": f"Bearer {token}"}
        self.card = Path(card)
        self.chunk_limit = chunk_limit          # tests: stop after N chunks to simulate power loss
        self.chunks_sent = 0

    def _req(self, method: str, url: str, **kw) -> httpx.Response:
        r = self.c.request(method, url, headers={**self.h, **kw.pop("headers", {})}, **kw)
        return r

    def _ok(self, r: httpx.Response, *codes: int) -> dict:
        if r.status_code not in codes:
            raise SyncError(f"{r.request.method} {r.request.url.path}: {r.status_code} {r.text[:300]}")
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

    def _upload(self, init_body: dict, src: Path, caps: dict) -> dict:
        init = self._ok(self._req("POST", "/v1/uploads", json=init_body), 200, 201)
        uid, off, total = init["upload_id"], init["next_offset"], init_body["bytes"]
        if init.get("state") == "COMPLETE" and uid is None:
            return {"durable": True, "asset_sha256": init_body["sha256"], "bytes": total}
        size = min(init["chunk_size"], caps["max_chunk_size"])
        with open(src, "rb") as f:
            while off < total:
                if self.chunk_limit is not None and self.chunks_sent >= self.chunk_limit:
                    raise SyncError("simulated power loss")
                f.seek(off)
                data = f.read(size)
                r = self._req("PUT", f"/v1/uploads/{uid}/chunk", content=data,
                              headers={"X-Upload-Offset": str(off), "Content-Type": "application/octet-stream"})
                if r.status_code == 409 and "next_offset" in r.json():
                    off = r.json()["next_offset"]          # resync with the server
                    continue
                off = self._ok(r, 200)["next_offset"]
                self.chunks_sent += 1
        rec = self._ok(self._req("POST", f"/v1/uploads/{uid}/complete"), 200)
        if not rec.get("durable") or rec["asset_sha256"] != init_body["sha256"].lower():
            raise SyncError(f"bad receipt for {init_body['frame_id']}: {rec}")
        return rec

    def sync_roll(self, manifest_path: Path) -> dict:
        self._ok(self.c.get("/v1/health"), 200)
        caps = self._ok(self._req("GET", "/v1/capabilities"), 200)
        raw = manifest_path.read_bytes()
        doc = json.loads(raw)
        roll = doc["roll_id"]
        self._ok(self._req("PUT", f"/v1/rolls/{roll}", content=raw, headers={"Content-Type": "application/json"}),
                 200, 201)
        receipts = {}
        for fr in doc["frames"]:                  # originals first, always (docs/07)
            src = card_source(self.card, fr["source_path"])
            receipts[fr["frame_id"]] = self._upload({
                "device_id": doc["device_id"], "roll_id": roll, "frame_id": fr["frame_id"],
                "media_role": "original_dng", "filename": src.name, "bytes": fr["source_size_bytes"],
                "sha256": fr["source_sha256"], "media_type": "image/x-adobe-dng"}, src, caps)
        fin = self._req("POST", f"/v1/rolls/{roll}/finalize")
        self._ok(fin, 200, 202)
        offline = {}
        if "camera_render" in caps.get("media_roles", []):
            for rec_path in sorted((manifest_path.parent / "offline").glob("*.json")):
                rec = json.loads(rec_path.read_text())
                jpg = rec_path.with_suffix(".jpg")
                data = jpg.read_bytes()
                offline[rec["frame_id"]] = self._upload({
                    "device_id": doc["device_id"], "roll_id": roll, "frame_id": rec["frame_id"],
                    "media_role": "camera_render", "filename": jpg.name, "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(), "media_type": "image/jpeg",
                    "render": rec["render"]}, jpg, caps)
        return {"roll_id": roll, "receipts": receipts, "finalize": fin.status_code, "camera_renders": offline}

    def pull_results(self, roll_id: str) -> list[Path]:
        """Download committed renders into the camera gallery (docs/07 return sync)."""
        gallery = self.card / MFILM_DIR.parent / "GALLERY" / roll_id
        gallery.mkdir(parents=True, exist_ok=True)
        got = []
        for r in self._ok(self._req("GET", f"/v1/rolls/{roll_id}/renders", params={"origin": "linux"}), 200):
            dst = gallery / f"F{r['ordinal']:02d}_{r['render_id'][:8]}.JPG"
            if dst.is_file() and hashlib.sha256(dst.read_bytes()).hexdigest() == r["sha256"]:
                got.append(dst)
                continue
            part = dst.with_suffix(".part")
            with self.c.stream("GET", f"/v1/renders/{r['render_id']}/file", headers=self.h) as resp:
                if resp.status_code != 200:
                    raise SyncError(f"download {r['render_id']}: {resp.status_code}")
                h = hashlib.sha256()
                with open(part, "wb") as f:
                    for chunk in resp.iter_bytes(64 * 1024):
                        f.write(chunk)
                        h.update(chunk)
            if h.hexdigest() != r["sha256"]:
                part.unlink()
                raise SyncError(f"download {r['render_id']}: hash mismatch")
            os.replace(part, dst)
            got.append(dst)
        return got


def develop_offline(manifest_path: Path, card: Path, width: int = 1200, height: int = 800) -> list[Path]:
    """Fake 'Develop Here': reduced-size renders of a sealed roll with the shared core."""
    from .develop import default_recipe, develop
    doc = json.loads(manifest_path.read_text())
    out_dir = manifest_path.parent / "offline"
    out_dir.mkdir(exist_ok=True)
    recipe = default_recipe(doc["film_profile_id"], doc["profile_bundle_hash"])
    recipe["recipe_id"] = doc.get("render_recipe_id") or recipe["recipe_id"]
    recipe["output_spec"].update(width=width, height=height, jpeg_quality=85)
    made = []
    for fr in doc["frames"]:
        jpg = out_dir / f"{fr['ordinal']:02d}.jpg"
        part = out_dir / f"{fr['ordinal']:02d}.part.jpg"
        prov = develop(card_source(card, fr["source_path"]), part, profile=None, recipe=recipe,
                       device_id=doc["device_id"], roll_id=doc["roll_id"], frame_id=fr["frame_id"],
                       captured_at=fr.get("captured_at"))
        part.with_suffix(".jpg.json").unlink()
        os.replace(part, jpg)
        record = {"frame_id": fr["frame_id"], "render": {
            "render_id": prov["render_id"], "recipe": recipe, "film_core_version": prov["film_core_version"],
            "grain_seed": prov["grain_seed"], "output_width": prov["output_width"],
            "output_height": prov["output_height"], "developed_at": prov["development_timestamp"],
            "elapsed_s": prov["elapsed_s"]}}
        jpg.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n")
        made.append(jpg)
    return made


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mfilm-fakecam")
    ap.add_argument("--server", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--card", required=True, type=Path)
    ap.add_argument("--pull", action="store_true", help="also download finished renders")
    ap.add_argument("--develop-here", action="store_true", help="first make reduced offline renders on the card")
    a = ap.parse_args(argv)
    with httpx.Client(base_url=a.server, timeout=60) as client:
        cam = Camera(client, a.token, a.card)
        for m in find_manifests(a.card):
            try:
                if a.develop_here:
                    print(f"  {len(develop_offline(m, a.card))} offline renders made")
                res = cam.sync_roll(m)
                print(f"{res['roll_id']}: {len(res['receipts'])} originals acknowledged, finalize {res['finalize']}, "
                      f"{len(res['camera_renders'])} camera renders")
                if a.pull:
                    print(f"  {len(cam.pull_results(res['roll_id']))} renders in the gallery")
            except SyncError as e:
                print(f"{m}: {e}", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
