# SPDX-License-Identifier: GPL-2.0-only
"""AI Darkroom Extension types and schema definitions (contracts/mfilm_ai_darkroom_spec.md)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AIStudioMode = Literal["pure", "hybrid"]
AutoEnhanceStyle = Literal["standard", "vivid", "portrait", "cinematic"]
NeuralEngineType = Literal["none", "neural_isp", "rawnind", "nafnet", "realesrgan"]
UpscaleModelType = Literal["RealESRGAN_x2plus", "RealESRGAN_x4plus"]


@dataclass
class AutoEnhanceConfig:
    enabled: bool = False
    strength: float = 1.0
    style: AutoEnhanceStyle = "standard"
    model: str = "image_adaptive_3dlut"

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "strength": round(float(self.strength), 3),
            "style": self.style,
            "model": self.model
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AutoEnhanceConfig:
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", False)),
            strength=float(data.get("strength", 1.0)),
            style=data.get("style", "standard"),
            model=data.get("model", "image_adaptive_3dlut")
        )


@dataclass
class StyleReferenceConfig:
    enabled: bool = False
    strength: float = 1.0
    reference_id: str | None = None
    reference_name: str | None = None
    reference_thumb: str | None = None
    preserve_skin: bool = True
    model: str = "sa_lut"

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "strength": round(float(self.strength), 3),
            "reference_id": self.reference_id,
            "reference_name": self.reference_name,
            "reference_thumb": self.reference_thumb,
            "preserve_skin": self.preserve_skin,
            "model": self.model
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StyleReferenceConfig:
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", False)),
            strength=float(data.get("strength", 1.0)),
            reference_id=data.get("reference_id"),
            reference_name=data.get("reference_name"),
            reference_thumb=data.get("reference_thumb"),
            preserve_skin=bool(data.get("preserve_skin", True)),
            model=data.get("model", "sa_lut")
        )


@dataclass
class NeuralEngineConfig:
    enabled: bool = False
    engine: NeuralEngineType = "none"
    chroma_strength: float = 0.5
    luma_strength: float = 0.3
    detail_preservation: float = 0.8
    upscale_scale: int = 2
    upscale_model: UpscaleModelType = "RealESRGAN_x2plus"

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "engine": self.engine,
            "chroma_strength": round(float(self.chroma_strength), 3),
            "luma_strength": round(float(self.luma_strength), 3),
            "detail_preservation": round(float(self.detail_preservation), 3),
            "upscale_scale": int(self.upscale_scale),
            "upscale_model": self.upscale_model
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> NeuralEngineConfig:
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", False)),
            engine=data.get("engine", "none"),
            chroma_strength=float(data.get("chroma_strength", 0.5)),
            luma_strength=float(data.get("luma_strength", 0.3)),
            detail_preservation=float(data.get("detail_preservation", 0.8)),
            upscale_scale=int(data.get("upscale_scale", 2)),
            upscale_model=data.get("upscale_model", "RealESRGAN_x2plus")
        )


@dataclass
class AIRecipe:
    mode: AIStudioMode = "pure"
    auto_enhance: AutoEnhanceConfig = field(default_factory=AutoEnhanceConfig)
    style_reference: StyleReferenceConfig = field(default_factory=StyleReferenceConfig)
    neural_engine: NeuralEngineConfig = field(default_factory=NeuralEngineConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "auto_enhance": self.auto_enhance.to_dict(),
            "style_reference": self.style_reference.to_dict(),
            "neural_engine": self.neural_engine.to_dict()
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AIRecipe:
        if not data:
            return cls()
        return cls(
            mode="hybrid" if data.get("mode") == "hybrid" else "pure",
            auto_enhance=AutoEnhanceConfig.from_dict(data.get("auto_enhance")),
            style_reference=StyleReferenceConfig.from_dict(data.get("style_reference")),
            neural_engine=NeuralEngineConfig.from_dict(data.get("neural_engine"))
        )
