# SPDX-License-Identifier: GPL-2.0-only
"""White-balance profiles (Web Darkroom).

A profile says what light the scene was shot under: a colour temperature (Kelvin) and a tint (Lightroom
convention: + magenta, - green), or explicit RGB gains. Applying it multiplies the scene-linear sRGB frame
by gains that turn that light neutral, RELATIVE to the 5500 K daylight the LibRaw "daylight" decode already
assumes. This is a von-Kries style correction in sRGB-linear, not a camera-native characterisation (no
per-camera matrices), so it is a creative/corrective tool, not a metrology-grade one.

Built-in presets use published values (sources listed per entry). Profiles can be imported from JSON, CSV,
Adobe XMP / lrtemplate presets and RawTherapee .pp3 files and are stored, immutable, under <data>/wb-profiles."""
from __future__ import annotations

import configparser
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

import numpy as np

REFERENCE_K = 5500.0
K_RANGE = (1700.0, 25000.0)
TINT_RANGE = (-150.0, 150.0)
MAX_GAIN = 8.0
MAX_IMPORT_BYTES = 256 * 1024
MAX_USER_PROFILES = 500
LUMA = np.array([0.2126, 0.7152, 0.0722])
XYZ_TO_SRGB = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560], [0.0556434, -0.2040259, 1.0572252]])

SRC_NIKON = "Nikon Z-series online manuals (White Balance): https://onlinemanual.nikonimglib.com/z7_z6/en-nsg/05_basic_settings_02.html"
SRC_RED = "RED DSMC2 Helium operation guide (White Balance): https://docs.red.com/955-0171/DSMC2HELIUMOperationGuide/en-us/Content/5_Advanced_Menus/1_Settings/Look/Color_Temp.htm"
SRC_GUIDE = "B&C Camera white balance guide (typical light sources): https://store.bandccamera.com/blogs/how-to/white-balance-photography-what-is-white-balance"
SRC_CIE = "CIE standard illuminants (correlated colour temperature)"
SRC_ADOBE = "Adobe Camera Raw / Lightroom WB convention: temperature in K, tint -150..+150 (+ = magenta)"

# (id, name, kelvin, tint, group, source)
BUILTIN: list[tuple[str, str, float, float, str, str]] = [
    ("daylight-5500", "Daylight 5500 K (reference, no change)", 5500, 0, "Reference", SRC_ADOBE),
    ("candle-1900", "Candlelight 1900 K", 1900, 0, "Light sources", SRC_GUIDE),
    ("incandescent-2700", "Household incandescent 2700 K", 2700, 0, "Light sources", SRC_GUIDE),
    ("sodium-2700", "Sodium-vapour / warm fluorescent 2700 K", 2700, 8, "Light sources", SRC_NIKON),
    ("cie-a-2856", "CIE illuminant A, tungsten 2856 K", 2856, 0, "Light sources", SRC_CIE),
    ("tungsten-film-3200", "Tungsten film / studio lamp 3200 K", 3200, 0, "Light sources", SRC_RED),
    ("sunrise-3500", "Golden hour 3500 K", 3500, 0, "Light sources", SRC_GUIDE),
    ("fluor-warm-3000", "Warm-white fluorescent 3000 K", 3000, 12, "Fluorescent", SRC_NIKON),
    ("fluor-white-3700", "White fluorescent 3700 K", 3700, 15, "Fluorescent", SRC_NIKON),
    ("cie-f11-4000", "CIE F11 narrow-band fluorescent 4000 K", 4000, 15, "Fluorescent", SRC_CIE),
    ("fluor-cool-4200", "Cool-white fluorescent 4200 K", 4200, 15, "Fluorescent", SRC_NIKON),
    ("fluor-red-4500", "Fluorescent (RED camera preset) 4500 K", 4500, 10, "Fluorescent", SRC_RED),
    ("fluor-day-5000", "Day-white fluorescent 5000 K", 5000, 10, "Fluorescent", SRC_NIKON),
    ("fluor-daylight-6500", "Daylight fluorescent 6500 K", 6500, 8, "Fluorescent", SRC_NIKON),
    ("cie-d50-5003", "CIE D50, horizon light / print viewing 5003 K", 5003, 0, "Daylight", SRC_CIE),
    ("nikon-sun-5200", "Direct sunlight 5200 K (Nikon preset)", 5200, 0, "Daylight", SRC_NIKON),
    ("nikon-flash-5400", "Flash 5400 K (Nikon preset)", 5400, 0, "Flash", SRC_NIKON),
    ("cie-d55-5503", "CIE D55, mid-morning daylight 5503 K", 5503, 0, "Daylight", SRC_CIE),
    ("red-daylight-5600", "Daylight / studio flash / HMI 5600 K", 5600, 0, "Daylight", SRC_RED),
    ("nikon-cloudy-6000", "Cloudy 6000 K (Nikon preset)", 6000, 0, "Daylight", SRC_NIKON),
    ("cie-d65-6504", "CIE D65, average daylight 6504 K", 6504, 0, "Daylight", SRC_CIE),
    ("overcast-7000", "Heavy overcast 7000 K", 7000, 0, "Daylight", SRC_GUIDE),
    ("red-cloudy-7500", "Cloudy (RED camera preset) 7500 K", 7500, 0, "Daylight", SRC_RED),
    ("cie-d75-7504", "CIE D75, north-sky daylight 7504 K", 7504, 0, "Daylight", SRC_CIE),
    ("nikon-shade-8000", "Shade 8000 K (Nikon preset)", 8000, 0, "Daylight", SRC_NIKON),
    ("red-shade-9000", "Deep shade (RED camera preset) 9000 K", 9000, 0, "Daylight", SRC_RED),
    ("blue-hour-12000", "Blue hour / clear blue sky 12000 K", 12000, 0, "Daylight", SRC_GUIDE),
    ("look-warm", "Creative: warm (+600 K)", 6100, 0, "Creative", "M-Film Darkroom"),
    ("look-cool", "Creative: cool (-600 K)", 4900, 0, "Creative", "M-Film Darkroom"),
    ("look-magenta", "Creative: magenta push (+20 tint)", 5500, 20, "Creative", "M-Film Darkroom"),
    ("look-green", "Creative: green push (-20 tint)", 5500, -20, "Creative", "M-Film Darkroom"),
]


class WBError(ValueError):
    pass


def kelvin_to_linear_rgb(k: float) -> np.ndarray:
    """Linear sRGB of a black-body-like white at colour temperature k (Kim et al. cubic approximation of the Planckian locus)."""
    t = float(min(max(k, 1667.0), 25000.0))
    if t <= 4000:
        x = -0.2661239e9 / t ** 3 - 0.2343589e6 / t ** 2 + 0.8776956e3 / t + 0.179910
    else:
        x = -3.0258469e9 / t ** 3 + 2.1070379e6 / t ** 2 + 0.2226347e3 / t + 0.240390
    if t <= 2222:
        y = -1.1063814 * x ** 3 - 1.34811020 * x ** 2 + 2.18555832 * x - 0.20219683
    elif t <= 4000:
        y = -0.9549476 * x ** 3 - 1.37418593 * x ** 2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x ** 3 - 5.87338670 * x ** 2 + 3.75112997 * x - 0.37001483
    xyz = np.array([x / y, 1.0, (1 - x - y) / y])
    return np.maximum(XYZ_TO_SRGB @ xyz, 0.03)         # very warm lights fall outside sRGB: keep the blue finite


def gains_for(kelvin: float, tint: float = 0.0) -> list[float]:
    """Per-channel gains (linear sRGB) that make light of `kelvin`/`tint` neutral, relative to REFERENCE_K, luminance kept."""
    g = kelvin_to_linear_rgb(REFERENCE_K) / kelvin_to_linear_rgb(kelvin)
    g[1] /= 1.0 + tint * 0.003                                   # + tint = push magenta = pull green
    g = np.clip(g / float(g @ LUMA), 1.0 / MAX_GAIN, MAX_GAIN)
    g = g / float(g @ LUMA)                                      # luminance of white stays 1 even where a gain was clipped
    return [round(float(v), 4) for v in g]


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:48] or "profile"


def make_profile(name: str, *, kelvin: float | None = None, tint: float = 0.0, gains: list[float] | None = None,
                 pid: str | None = None, group: str = "Imported", source: str = "") -> dict:
    name = re.sub(r"[\x00-\x1f\x7f]", "", str(name)).strip()[:80] or "Unnamed"
    if gains is not None:
        if len(gains) != 3 or not all(isinstance(v, (int, float)) and math.isfinite(v) and 0.05 <= v <= MAX_GAIN for v in gains):
            raise WBError("gains must be three numbers between 0.05 and 8")
        g = np.array(gains, float)
        gains = [round(float(v), 4) for v in g / float(g @ LUMA)]
        kelvin = None if kelvin is None else float(kelvin)
    else:
        if kelvin is None or not math.isfinite(float(kelvin)) or not K_RANGE[0] <= float(kelvin) <= K_RANGE[1]:
            raise WBError(f"kelvin must be between {K_RANGE[0]:.0f} and {K_RANGE[1]:.0f}")
        if not math.isfinite(float(tint)) or not TINT_RANGE[0] <= float(tint) <= TINT_RANGE[1]:
            raise WBError(f"tint must be between {TINT_RANGE[0]:.0f} and {TINT_RANGE[1]:.0f}")
        gains = gains_for(float(kelvin), float(tint))
    return {"id": pid or slug(name), "name": name, "kelvin": kelvin, "tint": float(tint), "gains": gains, "group": group, "source": source}


def builtins() -> list[dict]:
    return [{**make_profile(n, kelvin=k, tint=t, pid=f"builtin:{i}", group=g, source=s), "builtin": True} for i, n, k, t, g, s in BUILTIN]


_BUILTIN_BY_ID: dict[str, dict] = {}


def builtin(pid: str) -> dict | None:
    if not _BUILTIN_BY_ID:
        _BUILTIN_BY_ID.update({p["id"]: p for p in builtins()})
    return _BUILTIN_BY_ID.get(pid)


def canonical(p: dict) -> dict:
    """What a recipe embeds: only what changes pixels plus the label, so edited/deleted profiles never change old renders."""
    return {"id": p["id"], "name": p["name"], "kelvin": p.get("kelvin"), "tint": p.get("tint", 0.0), "gains": list(p["gains"])}


def apply(lin: np.ndarray, prof: dict | None) -> np.ndarray:
    if not prof:
        return lin
    g = np.array(prof["gains"], np.float32)
    return np.ascontiguousarray(lin * g, dtype=np.float32)


# ---- import ---------------------------------------------------------------------------------------------
def _num(s) -> float | None:
    try:
        return float(str(s).strip().replace(",", "."))
    except ValueError:
        return None


def parse_import(filename: str, data: bytes) -> list[dict]:
    """Profiles found in an uploaded file (not yet stored). Raises WBError with a readable reason."""
    if len(data) > MAX_IMPORT_BYTES:
        raise WBError(f"file larger than {MAX_IMPORT_BYTES // 1024} KiB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    ext = Path(filename).suffix.lower()
    base = Path(filename).stem
    found: list[dict] = []
    if ext == ".json":
        try:
            doc = json.loads(text)
        except ValueError as e:
            raise WBError(f"not valid JSON: {e}") from None
        items = doc.get("profiles", [doc]) if isinstance(doc, dict) else doc
        if not isinstance(items, list):
            raise WBError("JSON must be a profile object, a list of them, or {\"profiles\": [...]}")
        for it in items:
            if not isinstance(it, dict):
                raise WBError("every profile must be an object")
            found.append(make_profile(it.get("name") or base, kelvin=_num(it.get("kelvin", it.get("temperature"))),
                                      tint=_num(it.get("tint", 0)) or 0.0, gains=it.get("gains")))
    elif ext == ".csv":
        for ln in text.splitlines():
            parts = [p.strip() for p in re.split(r"[;,\t]", ln) if p.strip() != ""]
            if len(parts) < 2 or _num(parts[1]) is None:
                continue                                          # header or blank line
            found.append(make_profile(parts[0], kelvin=_num(parts[1]), tint=(_num(parts[2]) if len(parts) > 2 else 0.0) or 0.0))
    elif ext in (".xmp", ".lrtemplate"):
        if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
            raise WBError("XML with DOCTYPE/ENTITY is refused")
        k = re.search(r'(?:crs:Temperature\s*=\s*"|<crs:Temperature>|\bTemperature\s*=\s*)\s*([0-9.]+)', text)
        t = re.search(r'(?:crs:Tint\s*=\s*"|<crs:Tint>|\bTint\s*=\s*)\s*([+-]?[0-9.]+)', text)
        name = re.search(r'(?:crs:Name|title)\s*(?:=\s*"|>)\s*(?:<rdf:Alt>\s*<rdf:li[^>]*>)?([^"<]+)', text)
        if not k:
            raise WBError("no Temperature found (expected crs:Temperature in an Adobe XMP preset or Temperature in an .lrtemplate)")
        found.append(make_profile((name.group(1).strip() if name else base), kelvin=_num(k.group(1)), tint=_num(t.group(1)) if t else 0.0))
    elif ext == ".pp3":
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            cp.read_string(text)
        except configparser.Error as e:
            raise WBError(f"not a valid .pp3: {e}") from None
        if not cp.has_section("White Balance") or not cp.has_option("White Balance", "Temperature"):
            raise WBError("[White Balance] Temperature not found in the .pp3")
        green = _num(cp.get("White Balance", "Green", fallback="1")) or 1.0
        found.append(make_profile(base, kelvin=_num(cp.get("White Balance", "Temperature")), tint=(1.0 / green - 1.0) / 0.003 if green > 0 else 0.0))
    else:
        raise WBError(f"unsupported file type {ext or '(none)'}: use .json, .csv, .xmp, .lrtemplate or .pp3")
    if not found:
        raise WBError("no profiles found in the file")
    if len(found) > 200:
        raise WBError("more than 200 profiles in one file")
    return found


class UserProfiles:
    """Imported profiles on disk, one immutable JSON file per profile id (user:<slug>-<hash>)."""

    def __init__(self, root: Path):
        self.dir = Path(root) / "wb-profiles"

    def list(self) -> list[dict]:
        out = []
        for f in sorted(self.dir.glob("*.json")) if self.dir.is_dir() else []:
            try:
                out.append(json.loads(f.read_text()))
            except (OSError, ValueError):
                continue
        return out

    def get(self, pid: str) -> dict | None:
        if not re.fullmatch(r"user:[a-z0-9-]{1,48}-[0-9a-f]{8}", pid):
            return None
        f = self.dir / (pid[5:] + ".json")
        try:
            return json.loads(f.read_text())
        except (OSError, ValueError):
            return None

    def add(self, p: dict, filename: str) -> dict:
        if len(list(self.dir.glob("*.json"))) >= MAX_USER_PROFILES if self.dir.is_dir() else False:
            raise WBError(f"at most {MAX_USER_PROFILES} imported profiles")
        digest = hashlib.sha256(json.dumps([p["name"], p["kelvin"], p["tint"], p["gains"]], sort_keys=True).encode()).hexdigest()[:8]
        pid = f"{slug(p['name'])}-{digest}"
        rec = {**p, "id": f"user:{pid}", "group": "Imported", "source": f"imported from {re.sub(r'[^A-Za-z0-9._ -]', '_', filename)[:80]}", "builtin": False}
        self.dir.mkdir(parents=True, exist_ok=True)
        f = self.dir / f"{pid}.json"
        if not f.exists():
            tmp = f.with_name(f".{f.name}.part")
            tmp.write_text(json.dumps(rec, indent=1, ensure_ascii=False))
            tmp.replace(f)
        return rec

    def delete(self, pid: str) -> bool:
        if not self.get(pid):
            return False
        (self.dir / (pid[5:] + ".json")).unlink(missing_ok=True)
        return True


def lookup(root: Path):
    """id -> profile resolver (built-in, then imported) for recipe normalization."""
    users = UserProfiles(root)

    def f(pid: str) -> dict | None:
        return builtin(pid) if pid.startswith("builtin:") else users.get(pid)
    return f
