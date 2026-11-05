# SPDX-License-Identifier: GPL-2.0-only
"""Decoder probe, run as `python -I -m mfilm_server.darkroom._inspect FILE` in a
child process with an address-space limit and a timeout (docs/web/30): a
malformed RAW can crash or exhaust LibRaw, which must never take the API down.
Prints one JSON object; exit 0 only for a file the decoder fully unpacked."""
from __future__ import annotations

import json
import resource
import sys

TAG_DNGVERSION = 50706
EXIF = 0x8769


def probe(path: str, thumb_out: str | None = None) -> dict:
    import rawpy
    from PIL import Image, UnidentifiedImageError
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic not in (b"II*\x00", b"MM\x00*"):
        return {"ok": False, "code": "NOT_RAW", "detail": "not a TIFF-based RAW container"}
    meta: dict = {}
    try:
        with Image.open(path) as im:
            tags = im.getexif()
            sub = tags.get_ifd(EXIF)
            meta = {"make": str(tags.get(271) or "").strip("\0 ") or None,
                    "model": str(tags.get(50708) or tags.get(272) or "").strip("\0 ") or None,
                    "software": str(tags.get(305) or "").strip("\0 ") or None,
                    "captured_at": str(sub.get(36867) or tags.get(306) or "") or None,
                    "iso": sub.get(34855), "exposure_s": _f(sub.get(33434)), "aperture": _f(sub.get(33437)),
                    "focal_mm": _f(sub.get(37386)), "is_dng": TAG_DNGVERSION in tags}
            if isinstance(meta["iso"], (tuple, list)):
                meta["iso"] = meta["iso"][0] if meta["iso"] else None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        pass                                           # EXIF is best effort; the decoder decides eligibility
    try:
        with rawpy.imread(path) as raw:
            s = raw.sizes
            meta.update(width=int(s.width), height=int(s.height), raw_width=int(s.raw_width),
                        raw_height=int(s.raw_height), flip=int(s.flip), raw_type=str(raw.raw_type).split(".")[-1])
    except rawpy.LibRawFileUnsupportedError as e:
        return {"ok": False, "code": "UNSUPPORTED_RAW", "detail": str(e)}
    except rawpy.LibRawError as e:
        return {"ok": False, "code": "BAD_RAW", "detail": f"{type(e).__name__}: {e}"}
    if thumb_out:
        meta["has_thumb"] = _thumb(path, thumb_out, meta.get("flip", 0))
    meta["format"] = "dng" if meta.get("is_dng") else ("nef" if (meta.get("make") or "").upper().startswith("NIKON") else "raw")
    return {"ok": True, "meta": meta}


def _thumb(path: str, out: str, flip: int) -> bool:
    """Grid thumbnail from the RAW's own embedded preview (spec 28 allows it for the grid; real
    previews and the before/after compare are always renders). Best effort."""
    import io

    import numpy as np
    import rawpy
    from PIL import Image, ImageOps
    try:
        with rawpy.imread(path) as raw:
            t = raw.extract_thumb()
        if t.format == rawpy.ThumbFormat.JPEG:
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(t.data))).convert("RGB")
        elif t.format == rawpy.ThumbFormat.BITMAP:
            k = {0: 0, 3: 2, 5: 1, 6: 3}.get(flip, 0)
            im = Image.fromarray(np.ascontiguousarray(np.rot90(np.asarray(t.data), k)))
        else:
            return False
        im.thumbnail((320, 320))
        im.save(out, "JPEG", quality=80)
        return True
    except (rawpy.LibRawError, OSError, ValueError, SyntaxError):
        return False


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def main() -> int:
    resource.setrlimit(resource.RLIMIT_AS, (6 << 30, 6 << 30))
    try:
        out = probe(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    except MemoryError:
        out = {"ok": False, "code": "RESOURCE_LIMIT", "detail": "decoder exceeded memory limit"}
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
