# SPDX-License-Identifier: GPL-2.0-only
"""mfilm-develop: one RAW/DNG -> film JPEG + provenance sidecar (docs/05, docs/06).

    mfilm-develop --input IMG.DNG --profile portra400 --output out.jpg [--recipe r.json] [--json]

Pipeline: LibRaw (rawpy) decode -> linear sRGB -> lens geometry for CHDK
DNGs of calibrated cameras (lens.py) -> shared C film core -> optional
crop/downscale (never upscale) -> 8-bit sRGB JPEG with ICC.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from . import core, lens
from .ids import frame_seed, render_id, sha256_file

RAW_ADAPTER_VERSION = "rawpy-libraw-v3"
# v2: CHDK DNGs of a camera with a lens table are resampled into the camera JPEG frame
INPUT_NORMALIZATION = "mfilm-linear-rgb-v3"
DEMOSAIC = {"reference": "AHD", "fast": "LINEAR"}


class DevelopError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def film_core_version() -> str:
    return f"{core.core_version()}/abi{core.abi_version()}"


def recipe_seed(recipe: dict, device_id: str, roll_id: str, frame_id: str) -> int:
    return frame_seed(device_id, roll_id, frame_id, recipe["film_profile_id"], recipe["recipe_id"],
                      int(recipe.get("user_seed", 0)))


def recipe_render_id(original_sha256: str, recipe: dict, bundle_hash: str, seed: int) -> str:
    """Identity of the requested rendition (output_spec as requested, 0 = native)."""
    return render_id(original_sha256=original_sha256, recipe=recipe, film_core_version=film_core_version(),
                     profile_bundle_hash=bundle_hash, output_spec=recipe.get("output_spec", {}),
                     input_normalization_version=INPUT_NORMALIZATION, grain_seed=seed)


def core_commit() -> str:
    try:
        rev = subprocess.run(["git", "-C", str(core.REPO), "rev-parse", "HEAD"], capture_output=True, text=True,
                             check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(core.REPO), "status", "--porcelain", "src/shared/film_core"],
                               capture_output=True, text=True).stdout.strip()
        return rev + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def default_recipe(profile: str, bundle_hash: str) -> dict:
    return {"schema_version": 1, "recipe_id": f"default-{profile}-v1", "film_profile_id": profile,
            "profile_bundle_hash": bundle_hash, "film_core_abi_version": core.abi_version(),
            "input_normalization_version": INPUT_NORMALIZATION, "white_balance_mode": "daylight",
            "demosaic_mode": "reference", "exposure_compensation_ev": 0.0, "grain_seed_mode": "derived-per-frame",
            "user_seed": 0, "look_controls": {"grain_scale": 1.0, "halation_scale": 1.0, "softness_scale": 1.0},
            "output_spec": {"format": "image/jpeg", "colorspace": "sRGB", "width": 0, "height": 0,
                            "jpeg_quality": 92, "orientation_policy": "normalize-pixels"}}


# LibRaw's flip code -> np.rot90 k that turns the sensor-oriented image upright
# (flip 5 checked against LibRaw's own rotation on a CHDK DNG: identical)
_FLIP_ROT90 = {0: 0, 3: 2, 5: 1, 6: 3}


def decode_raw(path: Path, wb_mode: str, demosaic: str) -> tuple[np.ndarray, int]:
    """Linear sRGB in SENSOR orientation (LibRaw does not rotate) and the DNG's
    flip code. The lens model is in sensor coordinates, so rotation comes after
    it: rotating first sent portrait frames through a landscape lens map and
    smeared their right quarter (camera roll 2026-11-04, flip 5)."""
    import rawpy
    try:
        raw = rawpy.imread(str(path))
    except (rawpy.LibRawError, OSError) as e:
        raise DevelopError("BAD_DNG", str(e)) from None
    with raw:
        if wb_mode not in ("as-shot", "daylight"):
            raise DevelopError("UNSUPPORTED_RECIPE", f"white_balance_mode={wb_mode}")
        try:
            algo = getattr(rawpy.DemosaicAlgorithm, DEMOSAIC[demosaic])
        except KeyError:
            raise DevelopError("UNSUPPORTED_RECIPE", f"demosaic_mode={demosaic}") from None
        flip = int(raw.sizes.flip)
        img = raw.postprocess(user_flip=0, gamma=(1, 1), no_auto_bright=True, output_bps=16, user_wb=None,
                              use_camera_wb=wb_mode == "as-shot", use_auto_wb=False,
                              output_color=rawpy.ColorSpace.sRGB, highlight_mode=rawpy.HighlightMode.Clip,
                              demosaic_algorithm=algo)
    return img.astype(np.float32) / 65535.0, flip


def upright(img: np.ndarray, flip: int) -> np.ndarray:
    if flip not in _FLIP_ROT90:
        raise DevelopError("BAD_DNG", f"unsupported orientation flip={flip}")
    k = _FLIP_ROT90[flip]
    return np.ascontiguousarray(np.rot90(img, k)) if k else img


def normalize_geometry(path: Path, img: np.ndarray) -> tuple[np.ndarray, dict]:
    """Lens correction for CHDK DNGs (lens.py); other sources pass through unchanged."""
    info = lens.dng_info(path)
    table = lens.table_for(info)
    if table is None:
        return img, {"applied": False, "reason": "no lens table for this source"}
    if not info.get("focal_mm"):
        return img, {"applied": False, "reason": "DNG has no focal length", "table": table["file"]}
    return lens.correct(img, table, info["focal_mm"]), {
        "applied": True, "table": table["file"], "table_sha256": table["sha256"], "focal_mm": info["focal_mm"]}


STANDARD_LADDER = [
    (3000, 2000),
    (2000, 1333),
    (1600, 1200),
    (1200, 800),
]


def resolve_output_size(img_shape: tuple[int, int, ...], width: int, height: int) -> tuple[int, int, str | None]:
    """Given source image dimensions (h, w, ...) and requested target width and height:
    - If width and height are 0: returns (0, 0, None) for native size.
    - Orients target dimensions to match the source image orientation (portrait -> portrait).
    - If target fits within source: returns (target_w, target_h, None).
    - If target exceeds source resolution:
      - If requested size exceeds all standard presets (max > 3000): raises DevelopError('OUTPUT_LARGER_THAN_SOURCE').
      - Otherwise, automatically picks the next allowable smaller preset from the ladder that fits without upscaling.
        If none fit (frame is smaller than 1200x800), falls back to native frame size (0, 0).
        Returns (fit_w, fit_h, warning_message).
    """
    h, w = img_shape[:2]
    if not width and not height:
        return 0, 0, None

    # Match orientation
    if (h > w and width > height) or (w > h and height > width):
        width, height = height, width

    # Check if requested size fits directly
    if width <= w and height <= h:
        return width, height, None

    req_max = max(width, height)
    req_min = min(width, height)

    if req_max > 3000:
        raise DevelopError("OUTPUT_LARGER_THAN_SOURCE", f"requested {width}x{height}, source {w}x{h}")

    for lw, lh in STANDARD_LADDER:
        if (h > w and lw > lh) or (w > h and lh > lw):
            cw, ch = lh, lw
        else:
            cw, ch = lw, lh
        if (max(cw, ch) < req_max or (max(cw, ch) == req_max and min(cw, ch) < req_min)) and cw <= w and ch <= h:
            warning = f"Target size {width}×{height} exceeds frame resolution ({w}×{h}); rendered at {cw}×{ch}"
            return cw, ch, warning

    warning = f"Target size {width}×{height} exceeds frame resolution ({w}×{h}); rendered at native size ({w}×{h})"
    return 0, 0, warning


def fit_output(img: np.ndarray, width: int, height: int) -> np.ndarray:
    """Centre-crop to the requested aspect, then downscale. Never upscale.
    The aspect orientation follows the image: portrait images yield portrait
    renders, landscape images yield landscape renders."""
    from PIL import Image
    h, w, _ = img.shape
    if not width and not height:
        return img
    if (h > w and width > height) or (w > h and height > width):
        width, height = height, width
    if width > w or height > h:
        raise DevelopError("OUTPUT_LARGER_THAN_SOURCE", f"requested {width}x{height}, source {w}x{h}")
    if width * h != height * w:
        if width * h > height * w:
            ch = round(w * height / width)
            y0 = (h - ch) // 2
            img = img[y0:y0 + ch]
        else:
            cw = round(h * width / height)
            x0 = (w - cw) // 2
            img = img[:, x0:x0 + cw]
    if img.shape[1] == width and img.shape[0] == height:
        return img
    chans = [np.asarray(Image.fromarray(img[..., c], "F").resize((width, height), Image.LANCZOS)) for c in range(3)]
    return np.clip(np.stack(chans, -1), 0, 1)


def srgb_icc() -> bytes:
    """LittleCMS sRGB profile with its creation date and profile ID zeroed,
    so identical renders give identical bytes."""
    from PIL import ImageCms
    icc = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    icc[24:36] = bytes(12)          # dateTimeNumber
    icc[84:100] = bytes(16)         # profile ID (MD5), optional: 0 = not computed
    return bytes(icc)


def write_jpeg(img: np.ndarray, out: Path, quality: int, comment: str, captured_at: str | None = None,
               exif_extra: dict | None = None) -> None:
    from PIL import Image
    px = (np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)
    icc = srgb_icc()
    im = Image.fromarray(px, "RGB")
    exif = Image.Exif()
    exif[0x0131] = "Chromurgy Digital Darkroom (chromurgy-develop)"     # Software
    exif[0x010E] = comment                                    # ImageDescription
    if captured_at:                                           # so PhotoPrism dates the frame as shot
        try:
            t = dt.datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
            stamp = t.strftime("%Y:%m:%d %H:%M:%S")
            exif[0x0132] = stamp                              # DateTime
            sub = exif.get_ifd(0x8769)
            sub[0x9003] = stamp                               # DateTimeOriginal
            sub[0x9004] = stamp                               # DateTimeDigitized
            if t.utcoffset() is not None:
                off = t.strftime("%z")
                sub[0x9011] = f"{off[:3]}:{off[3:]}"          # OffsetTimeOriginal
        except ValueError:
            pass
    if exif_extra:                  # the real capture facts of the source (never the emulated look)
        for tag, v in exif_extra.get("ifd0", {}).items():
            exif[tag] = v
        sub = exif.get_ifd(0x8769)
        for tag, v in exif_extra.get("exif", {}).items():
            sub[tag] = v
    tmp = out.with_name(f".{out.name}.{os.getpid()}.part")
    im.save(tmp, "JPEG", quality=quality, icc_profile=icc, exif=exif, optimize=True)
    with Image.open(tmp) as chk:                             # decode back before promoting
        chk.load()
        if chk.size != (px.shape[1], px.shape[0]):
            tmp.unlink()
            raise DevelopError("OUTPUT_VALIDATION_FAILED", f"{chk.size}")
    os.replace(tmp, out)


def develop(input_path: Path, output: Path, *, profile: str | None, recipe: dict | None,
            device_id: str | None = None, roll_id: str | None = None, frame_id: str | None = None,
            bundle: core.Bundle | None = None, captured_at: str | None = None,
            exif_extra: dict | None = None) -> dict:
    bundle = bundle or core.Bundle()
    if recipe is None:
        if not profile:
            raise DevelopError("USAGE", "--profile or --recipe required")
        recipe = default_recipe(profile, bundle.sha256)
    elif profile and profile != recipe["film_profile_id"]:
        raise DevelopError("USAGE", "--profile disagrees with the recipe")
    profile = recipe["film_profile_id"]
    if recipe.get("profile_bundle_hash", "").lower() != bundle.sha256:
        raise DevelopError("PROFILE_BUNDLE_MISMATCH",
                           f"recipe wants {recipe.get('profile_bundle_hash')}, available {bundle.sha256}")
    if profile not in bundle.keys and profile != "none":     # "none": the Web Darkroom's switch-off for the film stage
        raise DevelopError("UNSUPPORTED_PROFILE", profile)
    if recipe.get("grain_seed_mode", "derived-per-frame") != "derived-per-frame":
        raise DevelopError("UNSUPPORTED_RECIPE", f"grain_seed_mode={recipe.get('grain_seed_mode')}")
    src_sha, src_bytes = sha256_file(input_path)
    device_id = device_id or "standalone"
    roll_id = roll_id or "standalone"
    frame_id = frame_id or src_sha
    seed = recipe_seed(recipe, device_id, roll_id, frame_id)

    t0 = dt.datetime.now(dt.timezone.utc)
    lin, flip = decode_raw(input_path, recipe.get("white_balance_mode", "as-shot"),
                           recipe.get("demosaic_mode", "reference"))
    lin, lens_info = normalize_geometry(input_path, lin)
    lin = upright(lin, flip)
    if recipe.get("rotate") or recipe.get("crop"):  # Web Darkroom rotate + crop: first, so every later stage sees the kept picture
        from .darkroom import cropping
        try:
            if recipe.get("rotate"):
                lin = cropping.apply_rotate(lin, recipe["rotate"])
            if recipe.get("crop"):
                lin = cropping.apply_crop(lin, recipe["crop"])
        except cropping.CropError as e:
            raise DevelopError("INVALID_CROP", str(e)) from None
    if recipe.get("wb_profile"):                  # Web Darkroom white-balance profile (gains in sRGB-linear)
        from .darkroom import wb
        lin = wb.apply(lin, recipe["wb_profile"])
    if recipe.get("creative"):                    # Web Darkroom optical effects + Camera Look, before the film stage
        from .darkroom import creative
        lin = creative.apply_creative(lin, recipe["creative"], salt=src_sha)
    lens_info = {**lens_info, "orientation_flip": flip}
    look = recipe.get("look_controls", {})
    if recipe.get("tone") or profile == "none":    # Web Darkroom: film off / development strength / contrast / filters
        from .darkroom import tone
        img, scanner_ev = tone.render_display(lin, recipe, bundle, seed)
        scanner_ev = scanner_ev if scanner_ev is not None else 0.0
    else:
        img, scanner_ev = bundle.develop(profile, lin, seed=seed, grain_scale=look.get("grain_scale", 1.0),
                                         halation_scale=look.get("halation_scale", 1.0),
                                         softness_scale=look.get("softness_scale", 1.0),
                                         exposure_ev=recipe.get("exposure_compensation_ev", 0.0))
    spec = recipe.get("output_spec", {})
    if spec.get("format", "image/jpeg") != "image/jpeg" or spec.get("colorspace", "sRGB") != "sRGB":
        raise DevelopError("UNSUPPORTED_RECIPE", "only image/jpeg sRGB output")
    req_w, req_h = int(spec.get("width") or 0), int(spec.get("height") or 0)
    fit_w, fit_h, warning = resolve_output_size(img.shape, req_w, req_h)
    img = fit_output(img, fit_w, fit_h)
    out_h, out_w = img.shape[:2]
    commit = core_commit()
    rid = recipe_render_id(src_sha, recipe, bundle.sha256, seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_jpeg(img, output, int(spec.get("jpeg_quality", 92)), f"M-Film {profile} render {rid[:16]}", captured_at,
               exif_extra)
    t1 = dt.datetime.now(dt.timezone.utc)
    prov = {
        "render_id": rid, "film_profile_id": profile, "profile_bundle_hash": bundle.sha256,
        "film_core_git_commit": commit, "film_core_version": film_core_version(),
        "film_core_abi_version": core.abi_version(),
        "recipe_schema_version": recipe.get("schema_version", 1), "recipe": recipe, "grain_seed": f"{seed:016x}",
        "raw_adapter_version": RAW_ADAPTER_VERSION, "demosaic_mode": recipe.get("demosaic_mode", "reference"),
        "wb_mode": recipe.get("white_balance_mode", "as-shot"), "scanner_ev": round(scanner_ev, 4),
        "lens_correction": lens_info, "creative": recipe.get("creative"), "crop": recipe.get("crop"), "tone": recipe.get("tone"), "wb_profile": recipe.get("wb_profile"),
        "source_width": int(lin.shape[1]), "source_height": int(lin.shape[0]),
        "output_width": out_w, "output_height": out_h, "jpeg_quality": int(spec.get("jpeg_quality", 92)),
        "warning": warning,
        "developed_by": "linux", "development_timestamp": t1.isoformat(timespec="seconds"),
        "elapsed_s": round((t1 - t0).total_seconds(), 3), "original_sha256": src_sha, "original_bytes": src_bytes,
        "device_id": device_id, "roll_id": roll_id, "frame_id": frame_id, "captured_at": captured_at,
        "output": str(output), "output_sha256": sha256_file(output)[0],
    }
    side = output.with_suffix(output.suffix + ".json")
    tmp = side.with_name(f".{side.name}.part")
    tmp.write_text(json.dumps(prov, indent=2) + "\n")
    os.replace(tmp, side)
    return prov


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mfilm-develop", description=__doc__.split("\n")[0])
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--profile", help="film key, e.g. portra400 (mfilm-develop --list-films)")
    ap.add_argument("--recipe", type=Path, help="render recipe JSON (contracts/render-recipe.example.json)")
    ap.add_argument("--device-id"), ap.add_argument("--roll-id"), ap.add_argument("--frame-id")
    ap.add_argument("--json", action="store_true", help="machine-readable result/error")
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "--list-films":
        b = core.Bundle()
        print("\n".join(b.keys))
        return 0
    a = ap.parse_args(argv)
    try:
        recipe = json.loads(a.recipe.read_text()) if a.recipe else None
        prov = develop(a.input, a.output, profile=a.profile, recipe=recipe, device_id=a.device_id,
                       roll_id=a.roll_id, frame_id=a.frame_id)
    except (DevelopError, core.CoreError) as e:
        if a.json:
            print(json.dumps({"ok": False, "error_code": e.code, "detail": e.detail}))
        else:
            print(f"mfilm-develop: {e.code}: {e.detail}", file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps({"ok": True, **prov}))
    else:
        print(f"{prov['output']}: {prov['output_width']}x{prov['output_height']} {prov['film_profile_id']} "
              f"in {prov['elapsed_s']} s (render {prov['render_id'][:16]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
