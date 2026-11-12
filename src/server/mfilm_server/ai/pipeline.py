# SPDX-License-Identifier: GPL-2.0-only
"""AI Darkroom Processing Pipeline: orchestrates Auto-Enhance, SA-LUT, and Neural Engine."""
from __future__ import annotations

import logging
from typing import Any
import numpy as np

from .types import AIRecipe
from .adaptive_lut import auto_enhance_image
from .sa_lut import apply_style_reference
from .neural_engine import apply_neural_engine

logger = logging.getLogger("mfilm.ai.pipeline")


def apply_ai_pipeline(
    img: np.ndarray,
    recipe: AIRecipe | dict[str, Any] | None,
    ref_img: np.ndarray | None = None
) -> np.ndarray:
    """Executes configured AI pipeline stages in correct sequence.

    Order:
      1. AI Denoise / Neural Sensor processing (pre-tone)
      2. Image-Adaptive 3D LUT (Auto-Enhancement)
      3. SA-LUT (Style transfer from reference sample)
    """
    if recipe is None:
        return img

    if isinstance(recipe, dict):
        ai_cfg = AIRecipe.from_dict(recipe)
    elif isinstance(recipe, AIRecipe):
        ai_cfg = recipe
    else:
        return img

    res = img

    # Stage 1: Neural Denoise / Sensor Engine
    if ai_cfg.neural_engine.enabled:
        res = apply_neural_engine(res, ai_cfg.neural_engine)

    # Stage 2: Auto-Enhance (Image-Adaptive 3D LUT)
    if ai_cfg.auto_enhance.enabled:
        res = auto_enhance_image(res, ai_cfg.auto_enhance)

    # Stage 3: Style by Reference (SA-LUT)
    if ai_cfg.style_reference.enabled:
        res = apply_style_reference(res, ref_img, ai_cfg.style_reference)

    return res
