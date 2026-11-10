# SPDX-License-Identifier: GPL-2.0-only
"""Curated Creative Color Grades catalog and user preset definitions.

Conforms to contracts/creative-color-grade.schema.json.
Provides 16 curated aesthetic presets inspired by VSCO, Instagram Classics,
Cinematic, Editorial, and Matte/Vintage/Monochrome aesthetic families.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .. import core

CATALOG_PRESETS: list[dict[str, Any]] = [
    {
        "id": "warm-muted-matte",
        "name": "Warm Muted Matte",
        "version": "1.0.0",
        "description": "Warm matte portrait grade with earthy muted colors and lifted blacks.",
        "category": "warm-matte",
        "tags": ["VSCO", "Matte", "Warm", "Muted", "Portrait"],
        "provenance": {
            "classification": "vsco-inspired",
            "notes": "Inspired by warm matte VSCO-era portrait aesthetics.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": -0.08,
                "global_saturation": -0.12,
                "vibrance": -0.04,
                "black_lift": 0.09,
                "white_rolloff": 0.06,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.08], [0.2, 0.22], [0.5, 0.52], [0.8, 0.82], [1.0, 0.98]],
            },
            "split_toning": {
                "shadows": {"hue": 85, "saturation": 0.08},
                "midtones": {"hue": 35, "saturation": 0.04},
                "highlights": {"hue": 42, "saturation": 0.10},
                "balance": 0.18,
            },
            "hsl": {
                "orange": {"saturation": -0.04, "luminance": 0.04},
                "yellow": {"saturation": -0.10},
                "green": {"saturation": -0.18, "hue": -0.06},
                "blue": {"saturation": -0.20, "luminance": -0.02},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.5,
            },
        },
    },
    {
        "id": "faded-vintage-portrait",
        "name": "Faded Vintage Portrait",
        "version": "1.0.0",
        "description": "Soft contrast, lifted blacks, gentle warm bias and subtle skin preservation.",
        "category": "vintage",
        "tags": ["VSCO", "Vintage", "Portrait", "Faded"],
        "provenance": {
            "classification": "vsco-inspired",
            "notes": "Inspired by faded film portrait aesthetics with lifted blacks.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": -0.12,
                "global_saturation": -0.08,
                "vibrance": -0.02,
                "black_lift": 0.11,
                "white_rolloff": 0.08,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.10], [0.25, 0.28], [0.5, 0.50], [0.75, 0.76], [1.0, 0.96]],
            },
            "split_toning": {
                "shadows": {"hue": 40, "saturation": 0.06},
                "midtones": {"hue": 30, "saturation": 0.04},
                "highlights": {"hue": 45, "saturation": 0.08},
                "balance": 0.10,
            },
            "hsl": {
                "red": {"saturation": -0.05},
                "orange": {"saturation": 0.02, "luminance": 0.03},
                "yellow": {"saturation": -0.12},
                "green": {"saturation": -0.20},
                "blue": {"saturation": -0.15},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.6,
            },
        },
    },
    {
        "id": "golden-editorial-soft",
        "name": "Golden Editorial Soft",
        "version": "1.0.0",
        "description": "Glowing warm highlights, refined contrast, elegant skin response.",
        "category": "editorial",
        "tags": ["VSCO", "Editorial", "Warm", "Golden Hour"],
        "provenance": {
            "classification": "vsco-inspired",
            "notes": "Editorial golden-hour glow with soft highlight rolloff.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": -0.04,
                "global_saturation": 0.04,
                "vibrance": 0.08,
                "black_lift": 0.04,
                "white_rolloff": 0.05,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.04], [0.2, 0.21], [0.5, 0.53], [0.8, 0.84], [1.0, 0.99]],
            },
            "split_toning": {
                "shadows": {"hue": 35, "saturation": 0.04},
                "midtones": {"hue": 40, "saturation": 0.08},
                "highlights": {"hue": 48, "saturation": 0.16},
                "balance": 0.30,
            },
            "hsl": {
                "orange": {"saturation": 0.06, "luminance": 0.05},
                "yellow": {"saturation": 0.08, "luminance": 0.03},
                "blue": {"saturation": -0.10, "luminance": -0.04},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.45,
            },
        },
    },
    {
        "id": "earthy-soft-fade",
        "name": "Earthy Soft Fade",
        "version": "1.0.0",
        "description": "Olive-brown shadows, lowered blue/green intensity, matte contrast.",
        "category": "warm-matte",
        "tags": ["VSCO", "Earthy", "Muted", "Vintage"],
        "provenance": {
            "classification": "vsco-inspired",
            "notes": "Earthy muted tones with olive shadow tint and matte blacks.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": -0.06,
                "global_saturation": -0.15,
                "vibrance": -0.06,
                "black_lift": 0.08,
                "white_rolloff": 0.06,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.07], [0.2, 0.20], [0.5, 0.49], [0.8, 0.80], [1.0, 0.97]],
            },
            "split_toning": {
                "shadows": {"hue": 95, "saturation": 0.10},
                "midtones": {"hue": 45, "saturation": 0.05},
                "highlights": {"hue": 52, "saturation": 0.06},
                "balance": -0.15,
            },
            "hsl": {
                "green": {"saturation": -0.22, "hue": -0.10},
                "yellow": {"saturation": -0.14},
                "blue": {"saturation": -0.25, "luminance": -0.05},
                "aqua": {"saturation": -0.20},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.5,
            },
        },
    },
    {
        "id": "valencia-inspired-soft-warmth",
        "name": "Valencia-Inspired Soft Warmth",
        "version": "1.0.0",
        "description": "Soft, warm, nostalgic color grade inspired by early Instagram classic aesthetics.",
        "category": "social-classics",
        "tags": ["Instagram Classics", "Warm", "Faded", "Vintage"],
        "provenance": {
            "classification": "instagram-classics-inspired",
            "notes": "Original preset inspired by early Instagram warm faded aesthetics.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": -0.05,
                "global_saturation": -0.08,
                "vibrance": -0.02,
                "black_lift": 0.06,
                "white_rolloff": 0.05,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.06], [0.18, 0.20], [0.5, 0.50], [0.82, 0.84], [1.0, 0.98]],
            },
            "split_toning": {
                "shadows": {"hue": 30, "saturation": 0.03},
                "midtones": {"hue": 28, "saturation": 0.05},
                "highlights": {"hue": 48, "saturation": 0.12},
                "balance": 0.25,
            },
            "hsl": {
                "orange": {"luminance": 0.03},
                "green": {"saturation": -0.12},
                "blue": {"saturation": -0.16},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.35,
            },
        },
    },
    {
        "id": "nashville-inspired-pastel-fade",
        "name": "Nashville-Inspired Pastel Fade",
        "version": "1.0.0",
        "description": "Pastel magenta warmth, low density contrast, airy faded shadows.",
        "category": "social-classics",
        "tags": ["Instagram Classics", "Pastel", "Faded", "Vintage"],
        "provenance": {
            "classification": "instagram-classics-inspired",
            "notes": "Pastel magenta/yellow retro tint inspired by early mobile photo culture.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": -0.10,
                "global_saturation": -0.05,
                "vibrance": 0.02,
                "black_lift": 0.10,
                "white_rolloff": 0.07,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.09], [0.22, 0.26], [0.5, 0.52], [0.78, 0.81], [1.0, 0.96]],
            },
            "split_toning": {
                "shadows": {"hue": 290, "saturation": 0.07},
                "midtones": {"hue": 330, "saturation": 0.04},
                "highlights": {"hue": 50, "saturation": 0.10},
                "balance": 0.05,
            },
            "hsl": {
                "magenta": {"saturation": 0.06},
                "purple": {"saturation": 0.04},
                "green": {"saturation": -0.15},
                "blue": {"saturation": -0.12},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.4,
            },
        },
    },
    {
        "id": "rise-inspired-cream-lift",
        "name": "Rise-Inspired Cream Lift",
        "version": "1.0.0",
        "description": "Lifted blacks, creamy brightness, nostalgic warmth and glowing midtones.",
        "category": "social-classics",
        "tags": ["Instagram Classics", "Warm", "Matte", "Soft"],
        "provenance": {
            "classification": "instagram-classics-inspired",
            "notes": "Soft creamy exposure lift with gentle golden highlight bias.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": -0.07,
                "global_saturation": -0.04,
                "vibrance": 0.03,
                "black_lift": 0.12,
                "white_rolloff": 0.08,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.11], [0.2, 0.25], [0.5, 0.54], [0.8, 0.85], [1.0, 0.97]],
            },
            "split_toning": {
                "shadows": {"hue": 45, "saturation": 0.05},
                "midtones": {"hue": 40, "saturation": 0.06},
                "highlights": {"hue": 46, "saturation": 0.14},
                "balance": 0.20,
            },
            "hsl": {
                "orange": {"luminance": 0.05, "saturation": 0.02},
                "yellow": {"luminance": 0.04},
                "blue": {"saturation": -0.18},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.45,
            },
        },
    },
    {
        "id": "toaster-inspired-retro-punch",
        "name": "Toaster-Inspired Retro Punch",
        "version": "1.0.0",
        "description": "Warm retro tone, punchy contrast, deep amber/reddish nostalgic tint.",
        "category": "social-classics",
        "tags": ["Instagram Classics", "Vintage", "Warm", "Punchy"],
        "provenance": {
            "classification": "instagram-classics-inspired",
            "notes": "Punchy retro warmth reminiscent of toaster-style golden-burnt tones.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": 0.10,
                "global_saturation": 0.06,
                "vibrance": 0.04,
                "black_lift": 0.03,
                "white_rolloff": 0.04,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.02], [0.2, 0.16], [0.5, 0.52], [0.8, 0.86], [1.0, 0.99]],
            },
            "split_toning": {
                "shadows": {"hue": 25, "saturation": 0.08},
                "midtones": {"hue": 32, "saturation": 0.06},
                "highlights": {"hue": 44, "saturation": 0.15},
                "balance": 0.10,
            },
            "hsl": {
                "red": {"saturation": 0.08},
                "orange": {"saturation": 0.10, "luminance": 0.02},
                "blue": {"saturation": -0.10, "luminance": -0.08},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.3,
            },
        },
    },
    {
        "id": "moody-earth-portrait",
        "name": "Moody Earth Portrait",
        "version": "1.0.0",
        "description": "Subdued palette, slightly darker mids, olive/cyan shadow shaping.",
        "category": "moody",
        "tags": ["VSCO", "Moody", "Earthy", "Portrait"],
        "provenance": {
            "classification": "vsco-inspired",
            "notes": "Deep moody portrait mood with subdued greens and cool/earthy undertones.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": 0.06,
                "global_saturation": -0.18,
                "vibrance": -0.08,
                "black_lift": 0.04,
                "white_rolloff": 0.05,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.03], [0.25, 0.20], [0.5, 0.46], [0.75, 0.77], [1.0, 0.98]],
            },
            "split_toning": {
                "shadows": {"hue": 165, "saturation": 0.08},
                "midtones": {"hue": 45, "saturation": 0.04},
                "highlights": {"hue": 40, "saturation": 0.06},
                "balance": -0.20,
            },
            "hsl": {
                "green": {"saturation": -0.30, "hue": -0.12},
                "aqua": {"saturation": -0.15},
                "orange": {"saturation": -0.04, "luminance": 0.02},
                "blue": {"saturation": -0.25, "luminance": -0.06},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.65,
            },
        },
    },
    {
        "id": "cool-cinematic-fade",
        "name": "Cool Cinematic Fade",
        "version": "1.0.0",
        "description": "Cooler shadows, restrained saturation, soft highlight rolloff.",
        "category": "cinematic",
        "tags": ["Cinematic", "Cool", "Faded"],
        "provenance": {
            "classification": "editorial-inspired",
            "notes": "Subtle teal-and-orange cinematic split tone with matte blacks.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": -0.04,
                "global_saturation": -0.10,
                "vibrance": -0.05,
                "black_lift": 0.07,
                "white_rolloff": 0.06,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.06], [0.22, 0.23], [0.5, 0.49], [0.78, 0.79], [1.0, 0.97]],
            },
            "split_toning": {
                "shadows": {"hue": 215, "saturation": 0.12},
                "midtones": {"hue": 200, "saturation": 0.04},
                "highlights": {"hue": 45, "saturation": 0.07},
                "balance": -0.10,
            },
            "hsl": {
                "blue": {"saturation": -0.05, "luminance": 0.02},
                "aqua": {"saturation": 0.04},
                "orange": {"luminance": 0.03},
                "yellow": {"saturation": -0.12},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.5,
            },
        },
    },
    {
        "id": "steel-blue-mood",
        "name": "Steel Blue Mood",
        "version": "1.0.0",
        "description": "Cool gray-blue palette with disciplined desaturation.",
        "category": "cinematic",
        "tags": ["Cinematic", "Cool", "Moody"],
        "provenance": {
            "classification": "editorial-inspired",
            "notes": "Moody steel-blue cinematic aesthetic for architecture and streets.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": 0.04,
                "global_saturation": -0.22,
                "vibrance": -0.10,
                "black_lift": 0.05,
                "white_rolloff": 0.04,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.04], [0.22, 0.19], [0.5, 0.48], [0.78, 0.80], [1.0, 0.98]],
            },
            "split_toning": {
                "shadows": {"hue": 220, "saturation": 0.16},
                "midtones": {"hue": 210, "saturation": 0.08},
                "highlights": {"hue": 205, "saturation": 0.06},
                "balance": -0.25,
            },
            "hsl": {
                "blue": {"saturation": -0.10, "luminance": 0.04},
                "aqua": {"saturation": -0.08},
                "red": {"saturation": -0.25},
                "green": {"saturation": -0.30},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.4,
            },
        },
    },
    {
        "id": "pastel-air",
        "name": "Pastel Air",
        "version": "1.0.0",
        "description": "Bright low-contrast look, reduced color density, soft lifted base.",
        "category": "editorial",
        "tags": ["VSCO", "Pastel", "Editorial", "Soft"],
        "provenance": {
            "classification": "vsco-inspired",
            "notes": "Airy pastel aesthetic with lifted shadows and bright midtones.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": -0.14,
                "global_saturation": -0.06,
                "vibrance": 0.04,
                "black_lift": 0.12,
                "white_rolloff": 0.08,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.11], [0.2, 0.28], [0.5, 0.57], [0.8, 0.86], [1.0, 0.98]],
            },
            "split_toning": {
                "shadows": {"hue": 200, "saturation": 0.04},
                "midtones": {"hue": 45, "saturation": 0.04},
                "highlights": {"hue": 55, "saturation": 0.08},
                "balance": 0.15,
            },
            "hsl": {
                "blue": {"saturation": -0.10, "luminance": 0.06},
                "aqua": {"saturation": -0.06, "luminance": 0.05},
                "orange": {"luminance": 0.04},
                "green": {"saturation": -0.14, "luminance": 0.04},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.4,
            },
        },
    },
    {
        "id": "soft-cream-editorial",
        "name": "Soft Cream Editorial",
        "version": "1.0.0",
        "description": "Cream-toned highlights, refined skin, low aggression blacks.",
        "category": "editorial",
        "tags": ["Editorial", "Warm", "Portrait", "Airy"],
        "provenance": {
            "classification": "editorial-inspired",
            "notes": "Contemporary editorial creamy warmth with gentle shadow contrast.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": -0.06,
                "global_saturation": -0.04,
                "vibrance": 0.05,
                "black_lift": 0.06,
                "white_rolloff": 0.07,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.05], [0.2, 0.23], [0.5, 0.53], [0.8, 0.83], [1.0, 0.97]],
            },
            "split_toning": {
                "shadows": {"hue": 45, "saturation": 0.04},
                "midtones": {"hue": 42, "saturation": 0.06},
                "highlights": {"hue": 46, "saturation": 0.12},
                "balance": 0.22,
            },
            "hsl": {
                "orange": {"luminance": 0.04, "saturation": 0.02},
                "yellow": {"luminance": 0.03},
                "blue": {"saturation": -0.15},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.55,
            },
        },
    },
    {
        "id": "dusty-summer",
        "name": "Dusty Summer",
        "version": "1.0.0",
        "description": "Dusty warm palette, muted foliage, nostalgic summertime finish.",
        "category": "vintage",
        "tags": ["VSCO", "Vintage", "Warm", "Muted"],
        "provenance": {
            "classification": "vsco-inspired",
            "notes": "Sun-bleached summer vacation look with warm muted tones.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": -0.05,
                "global_saturation": -0.10,
                "vibrance": -0.02,
                "black_lift": 0.08,
                "white_rolloff": 0.06,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.07], [0.2, 0.23], [0.5, 0.51], [0.8, 0.82], [1.0, 0.97]],
            },
            "split_toning": {
                "shadows": {"hue": 45, "saturation": 0.06},
                "midtones": {"hue": 38, "saturation": 0.05},
                "highlights": {"hue": 45, "saturation": 0.10},
                "balance": 0.10,
            },
            "hsl": {
                "green": {"saturation": -0.25, "hue": -0.08},
                "yellow": {"saturation": -0.08},
                "orange": {"saturation": 0.02, "luminance": 0.02},
                "blue": {"saturation": -0.22},
            },
            "skin_protection": {
                "enabled": True,
                "strength": 0.5,
            },
        },
    },
    {
        "id": "matte-monochrome-soft",
        "name": "Matte Monochrome Soft",
        "version": "1.0.0",
        "description": "Matte blacks, smooth highlight shoulders, soft classic B&W portrait mood.",
        "category": "monochrome",
        "tags": ["Matte", "Monochrome", "Portrait"],
        "provenance": {
            "classification": "editorial-inspired",
            "notes": "Silky matte black and white portrait look.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": -0.08,
                "global_saturation": -1.0,
                "vibrance": 0.0,
                "black_lift": 0.10,
                "white_rolloff": 0.06,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.09], [0.2, 0.24], [0.5, 0.52], [0.8, 0.83], [1.0, 0.97]],
            },
            "split_toning": {
                "shadows": {"hue": 0, "saturation": 0.0},
                "midtones": {"hue": 0, "saturation": 0.0},
                "highlights": {"hue": 0, "saturation": 0.0},
                "balance": 0.0,
            },
            "hsl": {},
            "skin_protection": {
                "enabled": False,
                "strength": 0.0,
            },
        },
    },
    {
        "id": "classic-silver-fade",
        "name": "Classic Silver Fade",
        "version": "1.0.0",
        "description": "Low-gloss monochrome with lifted blacks and gentle tonal rolloff.",
        "category": "monochrome",
        "tags": ["Vintage", "Monochrome", "Faded"],
        "provenance": {
            "classification": "community-inspired",
            "notes": "Silver gelatin inspired fade with gentle cool-silver shadow tint.",
        },
        "enabled": True,
        "parameters": {
            "global": {
                "contrast": 0.04,
                "global_saturation": -1.0,
                "vibrance": 0.0,
                "black_lift": 0.07,
                "white_rolloff": 0.05,
            },
            "tone_curve": {
                "rgb_master": [[0.0, 0.06], [0.2, 0.18], [0.5, 0.50], [0.8, 0.84], [1.0, 0.98]],
            },
            "split_toning": {
                "shadows": {"hue": 210, "saturation": 0.02},
                "midtones": {"hue": 0, "saturation": 0.0},
                "highlights": {"hue": 45, "saturation": 0.02},
                "balance": 0.0,
            },
            "hsl": {},
            "skin_protection": {
                "enabled": False,
                "strength": 0.0,
            },
        },
    },
]

_BY_ID: dict[str, dict[str, Any]] = {p["id"]: p for p in CATALOG_PRESETS}


def get_preset(preset_id: str) -> dict[str, Any] | None:
    """Return a deep copy of a preset if found in the catalog."""
    p = _BY_ID.get(preset_id)
    return copy.deepcopy(p) if p else None


def list_presets(tag: str | None = None, category: str | None = None, query: str | None = None) -> list[dict[str, Any]]:
    """Filter catalog presets by tag, category, and/or search query."""
    out = []
    q = (query or "").lower().strip()
    t = (tag or "").lower().strip()
    c = (category or "").lower().strip()
    for p in CATALOG_PRESETS:
        if not p.get("enabled", True):
            continue
        if c and p["category"].lower() != c:
            continue
        if t and not any(tag_str.lower() == t for tag_str in p.get("tags", [])):
            continue
        if q:
            name_match = q in p["name"].lower()
            desc_match = q in p.get("description", "").lower()
            tag_match = any(q in tag_str.lower() for tag_str in p.get("tags", []))
            id_match = q in p["id"].lower()
            if not (name_match or desc_match or tag_match or id_match):
                continue
        out.append(copy.deepcopy(p))
    return out
