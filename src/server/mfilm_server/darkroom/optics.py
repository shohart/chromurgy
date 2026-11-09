# SPDX-License-Identifier: GPL-2.0-only
"""The seven additional optical operators and the compound Vintage Glass of spec v0.6/v0.7
(docs/optical-engine/algorithms.md), implemented in numpy inside the one Linux Web Darkroom renderer.

Common rules (docs/optical-engine/algorithms.md "Common assumptions"):
 * input/output are scene-linear float32 RGB of the *oriented and cropped* frame (1.0 = white, HDR kept);
 * every position is normalized to that frame, every length is a fraction of the image diagonal or height,
   so a 1280 px preview and a 24 MP render of one recipe compose identically;
 * strength 0 (or amount 0) is a numerical bypass: the input array is returned untouched;
 * no RNG outside `analog_light_leaks`, which is seeded from (recipe seed, per-source salt, seed_offset) and
   sampled on a fixed grid in normalized coordinates (same layout at every output size);
 * source-driven effects (ghosting, starburst, anamorphic) act only on detected or manually placed compact
   sources; no source = exactly no change (never decorative orbs).

HONEST LIMITS: original artistic approximations on provisional parameters, not measured recreations of any
lens or filter; lensbaby/tilt-shift are 2-D emulations (no depth map). `IMPLEMENTATION_VERSION` is part of the
creative render identity of every recipe that uses one of these operators."""
from __future__ import annotations

import hashlib
import math

import numpy as np
from PIL import Image

from .imgops import LUMA, blur, luma, smoothstep

IMPLEMENTATION_VERSION = "mfilm-optics-1"
CHUNK_ROWS = 256


# ---- helpers ----
def _ss(x, lo, hi):
    """smoothstep with array-valued edges (imgops.smoothstep takes scalar edges)."""
    t = np.clip((x - lo) / np.maximum(hi - lo, 1e-6), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# --------------------------------------------------------------------------------------
def _diag(x: np.ndarray) -> float:
    return float(np.hypot(*x.shape[:2]))


def _hsv(h: float, s: float, v: float) -> np.ndarray:
    h = (h % 1.0) * 6.0
    i = int(h)
    f = h - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    return np.array([(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6], np.float32)


def _seed_u64(*parts) -> int:
    return int.from_bytes(hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()[:8], "big")


def _add_clipped(x: np.ndarray, patch: np.ndarray, cx: float, cy: float) -> None:
    """x += patch (HxWx3 or HxW*colour) centred on pixel (cx, cy); parts outside the frame are dropped."""
    ph, pw = patch.shape[:2]
    x0, y0 = int(round(cx)) - pw // 2, int(round(cy)) - ph // 2
    X0, Y0, X1, Y1 = max(x0, 0), max(y0, 0), min(x0 + pw, x.shape[1]), min(y0 + ph, x.shape[0])
    if X0 >= X1 or Y0 >= Y1:
        return
    x[Y0:Y1, X0:X1] += patch[Y0 - y0:Y1 - y0, X0 - x0:X1 - x0]


# ---- bright-source detection --------------------------------------------------------------------------
def detect_sources(x: np.ndarray, threshold: float, limit: int, *, max_area: float = 0.02, contrast: float = 2.5) -> list[dict]:
    """Compact energetic light sources of a scene-linear frame, strongest first.

    A candidate must exceed `threshold` (scene-linear luma), stand out from its surroundings by `contrast`
    (a uniformly bright wall or sky has none) and be compact (connected area below `max_area` of the frame).
    Works on a block-max reduction (<= ~512 px) so the result is nearly the same for a preview and the full
    frame; positions are normalized to the frame: [{x, y, peak, energy, area, confidence, color}]."""
    h, w = x.shape[:2]
    lum = luma(x)
    f = max(1, int(math.ceil(max(h, w) / 512)))
    hh, ww = h // f, w // f
    if hh < 2 or ww < 2:
        f, hh, ww = 1, h, w
    tl = lum[:hh * f, :ww * f].reshape(hh, f, ww, f)
    peak_map, mean_map = tl.max(axis=(1, 3)), tl.mean(axis=(1, 3))
    bg = blur(mean_map[..., None], max(2.0, 0.04 * max(hh, ww)))[..., 0]
    cand = (peak_map >= threshold) & (peak_map >= contrast * bg + 0.02)
    idx = np.flatnonzero(cand)
    if idx.size == 0:
        return []
    if idx.size > 40000:                                       # pathological: keep the brightest only
        idx = idx[np.argsort(peak_map.ravel()[idx])[-40000:]]
    pts = set(idx.tolist())
    out = []
    while pts:
        s = pts.pop()
        stack, comp = [s], [s]
        while stack:
            p = stack.pop()
            yy, xx = divmod(p, ww)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    y2, x2 = yy + dy, xx + dx
                    if (dy or dx) and 0 <= y2 < hh and 0 <= x2 < ww:
                        q = y2 * ww + x2
                        if q in pts:
                            pts.remove(q)
                            stack.append(q)
                            comp.append(q)
        area = len(comp) / float(hh * ww)
        if area > max_area:
            continue
        arr = np.asarray(comp)
        ys, xs = arr // ww, arr % ww
        vals = peak_map[ys, xs]
        wt = vals - threshold + 1e-3
        cx, cy = float((wt * xs).sum() / wt.sum()), float((wt * ys).sum() / wt.sum())
        pk = int(np.argmax(vals))
        by, bx = int(ys[pk]) * f, int(xs[pk]) * f
        col = x[by:by + f, bx:bx + f].reshape(-1, 3).mean(axis=0)
        col = col / max(float(col.max()), 1e-6)
        out.append({"x": float(np.clip((cx + 0.5) * f / w, 0, 1)), "y": float(np.clip((cy + 0.5) * f / h, 0, 1)),
                    "peak": float(vals.max()), "energy": float(wt.sum() * f * f), "area": area,
                    "confidence": float(np.clip(math.log2(max(float(vals.max()), threshold) / max(threshold, 1e-3) + 1.0) / 2.5, 0.05, 1.0)
                                        * (1.0 - area / max_area * 0.5)),
                    "color": [float(c) for c in col]})
    out.sort(key=lambda s: (-s["energy"], s["x"], s["y"]))
    return out[:max(1, int(limit))]


def resolve_sources(x: np.ndarray, selection: dict | None, threshold: float, limit: int) -> list[dict]:
    """Sources an effect acts on, per its `source_selection` (auto | manual | auto_plus_manual | off)."""
    sel = selection or {"mode": "auto"}
    mode = sel.get("mode", "auto")
    if mode == "off":
        return []
    h, w = x.shape[:2]
    srcs = detect_sources(x, threshold, limit) if mode in ("auto", "auto_plus_manual") else []
    if mode in ("manual", "auto_plus_manual"):
        for i, pt in enumerate(sel.get("points") or []):
            px, py = int(np.clip(pt["x"] * w, 0, w - 1)), int(np.clip(pt["y"] * h, 0, h - 1))
            near = [s for s in srcs if math.hypot((s["x"] - pt["x"]) * w, (s["y"] - pt["y"]) * h) < 0.02 * math.hypot(h, w)]
            if near:                                          # de-duplicate: the manual point wins over the detection next to it
                srcs.remove(near[0])
            r = max(1, int(0.004 * math.hypot(h, w)))
            win = x[max(py - r, 0):py + r + 1, max(px - r, 0):px + r + 1].reshape(-1, 3)
            col = win.mean(axis=0)
            col = col / max(float(col.max()), 1e-6) if col.max() > 1e-4 else np.ones(3, np.float32)
            wgt = float(pt.get("weight", 1.0))
            srcs.append({"x": float(pt["x"]), "y": float(pt["y"]), "peak": max(threshold * 3.0, float(win.max())) * max(wgt, 0.05),
                         "energy": 1e9 - i, "area": 0.0, "confidence": 1.0, "color": [float(c) for c in col], "manual": True})
    excl = set(sel.get("excluded_ids") or [])
    if excl:
        srcs = [s for s in srcs if source_id(s) not in excl]
    return srcs


def source_id(s: dict) -> str:
    """Stable id of a detected source (rounded normalized position): lets a user suppress one detection."""
    return f"{round(s['x'], 3):.3f},{round(s['y'], 3):.3f}"


def _src_gain(s: dict, threshold: float) -> float:
    """Brightness scaling of a source's artefacts: bounded, grows slowly with how far above threshold it is."""
    return float(np.clip(0.3 + 0.25 * math.log2(max(s["peak"], threshold) / max(threshold, 1e-3) + 1.0), 0.3, 1.6))


# ---- Wave 1: optical_vignetting ----------------------------------------------------------------------
def optical_vignetting(x, p, k, ctx):
    stops = p["strength_stops"] * k
    if stops <= 0:
        return x
    h, w = x.shape[:2]
    pw_ = float(p["shape_power"])
    asp = math.sqrt(p["aspect_ratio"])
    ax = (np.abs(((np.arange(w, dtype=np.float32) + 0.5) / w - p["center_x"]) * 2.0 * asp)) ** pw_
    norm = 2.0 ** (1.0 / pw_)
    out = np.empty_like(x)
    for y0 in range(0, h, CHUNK_ROWS):
        y1 = min(h, y0 + CHUNK_ROWS)
        ay = (np.abs(((np.arange(y0, y1, dtype=np.float32) + 0.5) / h - p["center_y"]) * 2.0 / asp)) ** pw_
        r = (ax[None, :] + ay[:, None]) ** (1.0 / pw_) / norm
        gain = np.exp2(-stops * smoothstep(r, p["inner_radius"], p["inner_radius"] + p["feather"]))
        blk = x[y0:y1]
        if p["highlight_protection"] > 0:
            gain = gain + (1.0 - gain) * p["highlight_protection"] * smoothstep(luma(blk), 0.8, 3.0)
        out[y0:y1] = blk * gain[..., None]
    return out


# ---- Wave 2: lens_flare_ghosting ---------------------------------------------------------------------
def _poly_profile(R: int, a: float, blades: int, soft: float) -> np.ndarray:
    """Soft-edged regular polygon (apothem a px) on a (2R+1)^2 grid; brighter towards the rim like a real reflection."""
    g = np.arange(-R, R + 1, dtype=np.float32)
    yy, xx = g[:, None], g[None, :]
    rho, th = np.hypot(xx, yy), np.arctan2(yy, xx)
    sector = 2 * math.pi / blades
    phi = np.mod(th + math.pi / blades, sector) - math.pi / blades
    rb = a / np.cos(phi)
    edge = max(0.7, soft * a * 0.7)
    prof = np.clip(0.5 - (rho - rb) / (2 * edge), 0.0, 1.0)
    prof = prof * prof * (3 - 2 * prof)
    return prof * (0.55 + 0.45 * np.clip(rho / np.maximum(rb, 1e-3), 0, 1) ** 2)


def lens_flare_ghosting(x, p, k, ctx):
    amount = p["amount"] * k
    if amount <= 0:
        return x
    srcs = resolve_sources(x, ctx.selection("lens_flare_ghosting"), p["source_threshold"], int(p["auto_source_limit"]))
    ctx.note("lens_flare_ghosting", srcs)
    if not srcs:
        return x
    h, w = x.shape[:2]
    diag = _diag(x)
    out = x.copy()
    n = int(p["ghost_count"])
    cs = p["chromatic_separation"]
    for s in srcs:
        gain = _src_gain(s, p["source_threshold"])
        sx, sy = s["x"] * w, s["y"] * h
        for i in range(n):
            fr = ((i + 1) * 0.6180339887) % 1.0
            fr2 = ((i + 1) * 0.7548776662) % 1.0
            alpha = p["spread"] * (-0.35 + 1.85 * ((i + 0.5) / n))          # deterministic positions along the optical axis
            gx, gy = w / 2 + alpha * (w / 2 - sx), h / 2 + alpha * (h / 2 - sy)
            r = p["radius_fraction"] * diag * (0.5 + 1.5 * fr2)
            inten = amount * 0.45 * gain / (1.0 + 0.25 * i) * float(np.clip(s["confidence"] + 0.35, 0, 1))
            tint = _hsv(p["hue_bias"] + 0.08 + 0.17 * i + 0.05 * fr, 0.55, 1.0) * 0.8 + 0.2
            Rr = int(math.ceil(r * (1 + cs) * 1.35 + 3))
            if Rr > 2 * max(h, w):
                continue
            patch = np.empty((2 * Rr + 1, 2 * Rr + 1, 3), np.float32)
            for c, scale in enumerate((1 + cs, 1.0, 1 - cs)):                # R, G, B at slightly different sizes
                patch[..., c] = _poly_profile(Rr, max(r * scale, 0.8), int(p["aperture_blades"]), p["softness"]) * tint[c] * inten
            _add_clipped(out, patch, gx, gy)
    return out


# ---- Wave 2: starburst_cross_screen ------------------------------------------------------------------
def _star_kernel(R: int, sigma: float, falloff: float, points: int, angle: float) -> np.ndarray:
    g = np.arange(-R, R + 1, dtype=np.float32)
    yy, xx = g[:, None], g[None, :]
    acc = np.zeros((2 * R + 1, 2 * R + 1), np.float32)
    L = float(R)
    for i in range(points):                                                    # `points` arms, evenly spaced
        th = math.radians(angle + i * 360.0 / points)
        c, s = math.cos(th), math.sin(th)
        d, perp = xx * c + yy * s, -xx * s + yy * c
        acc += np.where(d > 0, np.clip(1 - d / L, 0, 1) ** falloff, 0.0) * np.exp(-0.5 * (perp / sigma) ** 2)
    rho = np.hypot(xx, yy)
    acc += 0.9 * np.exp(-0.5 * (rho / (sigma * 2.2)) ** 2)                     # compact core
    return acc


def starburst_cross_screen(x, p, k, ctx):
    amount = p["amount"] * k
    if amount <= 0:
        return x
    srcs = resolve_sources(x, ctx.selection("starburst_cross_screen"), p["highlight_threshold"], int(p["max_sources"]))
    ctx.note("starburst_cross_screen", srcs)
    if not srcs:
        return x
    h, w = x.shape[:2]
    diag = _diag(x)
    R = int(min(max(math.ceil(p["ray_length_fraction"] * diag), 2), 1.2 * max(h, w)))
    ker = _star_kernel(R, max(0.6, p["ray_width"] * diag), p["falloff"], int(p["points"]), p["angle_degrees"])
    out = x.copy()
    for s in srcs:
        col = np.asarray(s["color"], np.float32) * 0.7 + 0.3
        _add_clipped(out, ker[..., None] * (col * amount * _src_gain(s, p["highlight_threshold"])), s["x"] * w, s["y"] * h)
    return out


# ---- Wave 3: anamorphic_streak -----------------------------------------------------------------------
def _streak_kernel(Lpx: float, sigma: float, falloff: float, split: float, angle: float) -> np.ndarray:
    th = math.radians(angle)
    c, s = math.cos(th), math.sin(th)
    rp = int(math.ceil(5 * sigma + 1))
    L = int(math.ceil(Lpx))
    ex = int(math.ceil(L * abs(c) + rp * abs(s)))
    ey = int(math.ceil(L * abs(s) + rp * abs(c)))
    yy = np.arange(-ey, ey + 1, dtype=np.float32)[:, None]
    xx = np.arange(-ex, ex + 1, dtype=np.float32)[None, :]
    d, perp = xx * c + yy * s, -xx * s + yy * c
    core = np.exp(-0.5 * (perp / sigma) ** 2)
    ker = np.empty((2 * ey + 1, 2 * ex + 1, 3), np.float32)
    tint = np.array([0.55, 0.8, 1.3], np.float32)                              # blue-white anamorphic streak
    for ch, ls in enumerate((1.0 - 0.5 * split, 1.0, 1.0 + 0.5 * split)):     # R, G, B reach different lengths
        La = max(L * ls, 1.0)
        ad = np.abs(d)
        along = 0.35 * np.exp(-ad / (0.12 * La)) + 0.65 * np.clip(1 - ad / La, 0, 1) ** falloff
        ker[..., ch] = core * along * tint[ch]
    return ker


def anamorphic_streak(x, p, k, ctx):
    amount = p["amount"] * k
    if amount <= 0:
        return x
    srcs = resolve_sources(x, ctx.selection("anamorphic_streak"), p["threshold"], int(p["auto_source_limit"]))
    ctx.note("anamorphic_streak", srcs)
    if not srcs:
        return x
    h, w = x.shape[:2]
    diag = _diag(x)
    Lpx = min(p["length_fraction"] * diag, 1.5 * max(h, w))
    ker = _streak_kernel(max(Lpx, 2.0), max(0.6, p["core_width"] * diag), p["falloff"], p["chromatic_split"], p["angle_degrees"])
    out = x.copy()
    for s in srcs:
        _add_clipped(out, ker * (amount * 0.8 * _src_gain(s, p["threshold"])), s["x"] * w, s["y"] * h)
    return out


# ---- Wave 3: analog_light_leaks ----------------------------------------------------------------------
LEAK_GRID = 256


def _smooth_noise(rng: np.random.Generator, cells: int, size: int = LEAK_GRID) -> np.ndarray:
    g = rng.random((cells + 3, cells + 3)).astype(np.float32)
    im = Image.fromarray(g, "F").resize((size * (cells + 3) // cells, size * (cells + 3) // cells), Image.BICUBIC)
    a = np.asarray(im)
    o = size // cells
    return a[o:o + size, o:o + size]


def _smooth_curve(rng: np.random.Generator, n: int = 7, size: int = LEAK_GRID) -> np.ndarray:
    pts = rng.random(n + 2).astype(np.float32)
    xs = np.linspace(0, 1, n + 2)
    t = np.linspace(0, 1, size)
    c = np.interp(t, xs, pts)
    k = np.ones(25, np.float32) / 25
    return np.convolve(np.pad(c, 12, mode="edge"), k, mode="valid")[:size]


def leak_canvas(p: dict, k: float, seed: int, salt: str) -> np.ndarray:
    """Light-leak exposure (LEAK_GRID^2 x 3, scene-linear) over normalized (u, v) space. Pure function of
    (seed, salt, parameters): independent of the image size, tiling or worker count."""
    layout = np.random.Generator(np.random.PCG64(_seed_u64("leaks-v1", seed, p["seed_offset"])))
    frame = np.random.Generator(np.random.PCG64(_seed_u64("leaks-frame-v1", salt, seed, p["seed_offset"])))
    fv = float(p["frame_variation"])
    edge = int(round(p.get("edge", 4))) if "edge" in p else 4                    # 0 left 1 right 2 top 3 bottom 4 auto
    if edge == 4:
        edge = int(layout.integers(0, 4))
        if fv > 0.5 and frame.random() < fv - 0.5:                             # strong frame variation may flip the edge
            edge = int(frame.integers(0, 4))
    s0 = float(np.clip(layout.uniform(0.2, 0.8) + fv * (frame.random() - 0.5) * 0.6, 0.05, 0.95))
    yy, xx = np.mgrid[0:LEAK_GRID, 0:LEAK_GRID].astype(np.float32) / (LEAK_GRID - 1)
    d, s = [(xx, yy), (1 - xx, yy), (yy, xx), (1 - yy, xx)][edge]              # distance from the edge, position along it
    irr = float(p["irregularity"])
    wvar = _smooth_curve(layout)
    width = p["width_fraction"] * (1.0 + irr * (2 * wvar - 1) * 0.9)
    width = np.maximum(width, 0.02)[np.clip((s * (LEAK_GRID - 1)).astype(np.int32), 0, LEAK_GRID - 1)]
    hl = max(p["coverage"] * 0.5, 1e-3)
    env = 1.0 - _ss(np.abs(s - s0), hl * 0.6, hl + 0.12) if p["coverage"] < 1.0 else np.ones_like(s)
    fe = float(p["feather"])
    band = 1.0 - _ss(d, width * (1 - 0.8 * fe), width * (1 + fe) + 1e-3)
    bleed = np.exp(-d / (width * 3.0)) * float(p["bleed"]) * 0.5
    nz = _smooth_noise(layout, 4)
    m = env * (band + bleed) * np.clip(1.0 + irr * (nz - 0.5) * 1.6, 0.0, None)
    hue_shift = (frame.random() * 2 - 1) * float(p["hue_variance"]) * 0.08
    warm = _hsv(0.045 + hue_shift, 0.9, 1.0) * np.array([1.0, 0.8, 0.45], np.float32)
    neutral = np.array([1.0, 0.92, 0.82], np.float32)
    col = neutral + (warm - neutral) * float(p["warmth"])
    hot = np.clip(m, 0, 1.2)[..., None] ** 2
    rgb = col[None, None, :] + (np.array([1.0, 0.85, 0.5], np.float32) - col)[None, None, :] * 0.5 * hot
    return (m[..., None] * rgb).astype(np.float32)


def analog_light_leaks(x, p, k, ctx):
    amount = p["amount"] * k
    if amount <= 0:
        return x
    leak = leak_canvas(p, k, ctx.seed, ctx.salt)
    h, w = x.shape[:2]
    out = x.copy()
    for c in range(3):
        up = np.asarray(Image.fromarray(np.ascontiguousarray(leak[..., c]), "F").resize((w, h), Image.BILINEAR))
        out[..., c] += amount * 0.6 * up / (1.0 + 0.8 * out[..., c])
    return out


# ---- level-blend machinery for the spatially varying blurs ------------------------------------------
def _level_blend(x: np.ndarray, weight_rows, sigma_max: float, levels: int = 4) -> np.ndarray:
    """Blend between the sharp frame and `levels` progressively blurrier copies by a per-pixel weight in [0,1].
    weight_rows(y0, y1) -> (y1-y0, w) weights; weight 0 keeps the original pixel exactly."""
    h, w = x.shape[:2]
    if sigma_max < 0.5:
        return x
    wmap = np.empty((h, w), np.float32)
    for y0 in range(0, h, CHUNK_ROWS):
        y1 = min(h, y0 + CHUNK_ROWS)
        wmap[y0:y1] = weight_rows(y0, y1)
    q = wmap * levels
    out = x * np.clip(1 - q, 0, 1)[..., None]
    for j in range(1, levels + 1):
        wj = np.clip(1 - np.abs(q - j), 0, 1)
        if not wj.any():
            continue
        out += blur(x, sigma_max * j / levels) * wj[..., None]
    return out


def _gradient_eased(t: np.ndarray, falloff: float) -> np.ndarray:
    return smoothstep(t, 0.0, 1.0) ** (max(falloff, 0.05) / 2.0)


# ---- Wave 5: lensbaby_sweet_spot ---------------------------------------------------------------------
def lensbaby_sweet_spot(x, p, k, ctx):
    a = p["amount"] * k
    h, w = x.shape[:2]
    diag = _diag(x)
    sigma = min(p["max_blur_radius_fraction"] * diag * a, 0.2 * diag)
    if a <= 0 or sigma < 0.5:
        return x
    fx, fy = p["focus_x"] * w, p["focus_y"] * h
    R, T = p["focus_radius_fraction"], max(p["transition_width"] * 0.5, 1e-3)
    xs = np.arange(w, dtype=np.float32) + 0.5

    def rows(y0, y1):
        ys = np.arange(y0, y1, dtype=np.float32)[:, None] + 0.5
        dist = np.hypot(xs[None, :] - fx, ys - fy) / diag
        return _gradient_eased(np.clip((dist - R) / T, 0, 1), p["falloff_power"])
    out = _level_blend(x, rows, sigma)
    if p["edge_bloom"] > 0:
        out = out + p["edge_bloom"] * 0.5 * blur(np.maximum(x - 1.0, 0.0), sigma * 0.6)
    return out


# ---- Wave 10: tilt_shift_miniature -------------------------------------------------------------------
def tilt_shift_miniature(x, p, k, ctx):
    a = p["amount"] * k
    h, w = x.shape[:2]
    diag = _diag(x)
    sigma = min(p["max_blur_radius_fraction"] * diag * a, 0.2 * diag)
    if a <= 0 or sigma < 0.5:
        return x
    th = math.radians(p["angle_degrees"])
    nx, ny = -math.sin(th), math.cos(th)
    cx, cy = p["band_center_x"] * w, p["band_center_y"] * h
    half, feather = p["sharp_band_width_fraction"] / 2.0, max(p["transition_width"], 1e-3)
    xs = np.arange(w, dtype=np.float32) + 0.5

    def rows(y0, y1):
        ys = np.arange(y0, y1, dtype=np.float32)[:, None] + 0.5
        dist = np.abs((xs[None, :] - cx) * nx + (ys - cy) * ny) / h             # distance from the band centre line, in image heights
        return _gradient_eased(np.clip((dist - half) / feather, 0, 1), p["falloff"])
    out = _level_blend(x, rows, sigma)
    vb = float(p["vividness_boost"])
    if vb > 0:
        y = luma(out)[..., None]
        out = np.maximum(y + (1 + vb * min(k, 1.0)) * (out - y), 0.0)
    return out


# ---- Wave 5: Vintage Glass components ----------------------------------------------------------------
def _sample_bilinear(x: np.ndarray, sy: np.ndarray, sx: np.ndarray, zero_fill: bool = False) -> np.ndarray:
    h, w = x.shape[:2]
    x0 = np.floor(sx).astype(np.int32)
    y0 = np.floor(sy).astype(np.int32)
    fx, fy = (sx - x0).astype(np.float32), (sy - y0).astype(np.float32)
    x1, y1 = np.clip(x0 + 1, 0, w - 1), np.clip(y0 + 1, 0, h - 1)
    x0c, y0c = np.clip(x0, 0, w - 1), np.clip(y0, 0, h - 1)
    out = (x[y0c, x0c] * ((1 - fx) * (1 - fy))[..., None] + x[y0c, x1] * (fx * (1 - fy))[..., None]
           + x[y1, x0c] * ((1 - fx) * fy)[..., None] + x[y1, x1] * (fx * fy)[..., None])
    if zero_fill:
        ok = (sx >= 0) & (sx <= w - 1) & (sy >= 0) & (sy <= h - 1)
        out = out * ok[..., None]
    return out


def _r0(w: int, h: int, cx: float, cy: float) -> float:
    """Normalising radius: distance from the centre to the farthest corner (0.5*diag for a centred lens)."""
    return max(math.hypot(px - cx * w, py - cy * h) for px in (0, w) for py in (0, h))


def _barrel_scale(rd: np.ndarray, k1: float, k2: float) -> np.ndarray:
    """source radius / distorted radius, solving rd = rs (1 + k1 rs^2 + k2 rs^4) by Newton steps."""
    rs = rd.copy()
    for _ in range(5):
        f = rs * (1 + k1 * rs ** 2 + k2 * rs ** 4) - rd
        df = np.maximum(1 + 3 * k1 * rs ** 2 + 5 * k2 * rs ** 4, 0.2)
        rs = np.maximum(rs - f / df, 0.0)
    return np.where(rd > 1e-9, rs / np.maximum(rd, 1e-9), 1.0 / np.maximum(1 + 0 * rd, 1))


def _auto_zoom(w: int, h: int, cx: float, cy: float, R0: float, k1: float, k2: float) -> float:
    """Smallest zoom >= 1 so every border pixel samples inside the source (barrel pulls the corners inward)."""
    t = np.linspace(0, 1, 129, dtype=np.float32)
    bx = np.concatenate([t * (w - 1), t * (w - 1), np.zeros_like(t), np.full_like(t, w - 1)])
    by = np.concatenate([np.zeros_like(t), np.full_like(t, h - 1), t * (h - 1), t * (h - 1)])
    dx, dy = bx - cx * w, by - cy * h
    rd = np.hypot(dx, dy) / R0

    def inside(z: float) -> bool:
        sc = _barrel_scale(rd / z, k1, k2) / z
        sx, sy = cx * w + dx * sc, cy * h + dy * sc
        return bool((sx >= -0.5).all() and (sx <= w - 0.5).all() and (sy >= -0.5).all() and (sy <= h - 0.5).all())
    if inside(1.0):
        return 1.0
    lo, hi = 1.0, 2.5
    for _ in range(24):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if inside(mid) else (mid, hi)
    return hi


def vintage_glass_barrel_distortion(x, p, k, ctx):
    a = p["amount"] * k
    k1, k2 = p["k1"] * a, p["k2"] * a
    if abs(k1) < 1e-7 and abs(k2) < 1e-7:
        return x
    h, w = x.shape[:2]
    cx, cy = p["center_x"], p["center_y"]
    R0 = _r0(w, h, cx, cy)
    mode = int(round(p.get("crop_mode", 1)))              # 0 extend (edge replicate), 1 auto crop (zoom), 2 transparent edge (black)
    z = _auto_zoom(w, h, cx, cy, R0, k1, k2) if mode == 1 else 1.0
    xs = np.arange(w, dtype=np.float32)
    out = np.empty_like(x)
    for y0 in range(0, h, 128):
        y1 = min(h, y0 + 128)
        dx = xs[None, :] - cx * w
        dy = np.arange(y0, y1, dtype=np.float32)[:, None] - cy * h
        rd = np.hypot(dx, dy) / R0
        sc = _barrel_scale(rd / z, k1, k2) / z
        out[y0:y1] = _sample_bilinear(x, cy * h + dy * sc, cx * w + dx * sc, zero_fill=(mode == 2))
    return out


def vintage_glass_chromatic_aberration(x, p, k, ctx):
    a = p["amount"] * k
    rs, bs = p["red_shift_fraction"] * a, p["blue_shift_fraction"] * a
    if rs <= 0 and bs <= 0:
        return x
    h, w = x.shape[:2]
    diag = _diag(x)
    cx, cy = p["center_x"], p["center_y"]
    R0 = _r0(w, h, cx, cy)
    xs = np.arange(w, dtype=np.float32)
    out = x.copy()
    for y0 in range(0, h, 128):
        y1 = min(h, y0 + 128)
        dx = xs[None, :] - cx * w
        dy = np.arange(y0, y1, dtype=np.float32)[:, None] - cy * h
        r = np.hypot(dx, dy)
        rn = r / R0
        ux, uy = dx / np.maximum(r, 1e-6), dy / np.maximum(r, 1e-6)
        mag = rn ** p["radial_power"] * diag
        X, Y = xs[None, :] + 0 * dy, np.arange(y0, y1, dtype=np.float32)[:, None] + 0 * dx
        out[y0:y1, :, 0] = _sample_bilinear(x, Y - uy * mag * rs, X - ux * mag * rs)[..., 0]
        out[y0:y1, :, 2] = _sample_bilinear(x, Y + uy * mag * bs, X + ux * mag * bs)[..., 2]
    return out


def vintage_glass_edge_softness(x, p, k, ctx):
    a = p["amount"] * k
    h, w = x.shape[:2]
    diag = _diag(x)
    sigma = min(p["edge_blur_radius_fraction"] * diag * a, 0.2 * diag)
    if a <= 0 or sigma < 0.5:
        return x
    clear = float(p["center_clear_fraction"])
    xs = np.arange(w, dtype=np.float32) + 0.5

    def rows(y0, y1):
        ys = np.arange(y0, y1, dtype=np.float32)[:, None] + 0.5
        rn = np.hypot(xs[None, :] - w / 2, ys - h / 2) / (0.5 * diag)
        return _gradient_eased(np.clip((rn - clear) / max(1 - clear, 1e-3), 0, 1), p["falloff_power"])
    return _level_blend(x, rows, sigma)


OPERATORS = {
    "optical_vignetting": optical_vignetting,
    "lens_flare_ghosting": lens_flare_ghosting,
    "starburst_cross_screen": starburst_cross_screen,
    "anamorphic_streak": anamorphic_streak,
    "analog_light_leaks": analog_light_leaks,
    "lensbaby_sweet_spot": lensbaby_sweet_spot,
    "tilt_shift_miniature": tilt_shift_miniature,
    "vintage_glass_barrel_distortion": vintage_glass_barrel_distortion,
    "vintage_glass_chromatic_aberration": vintage_glass_chromatic_aberration,
    "vintage_glass_edge_softness": vintage_glass_edge_softness,
}
SOURCE_DRIVEN = {"lens_flare_ghosting", "starburst_cross_screen", "anamorphic_streak"}
