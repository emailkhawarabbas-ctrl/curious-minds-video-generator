"""Typed loader for ``config/style.yaml`` (the lively look's colours, fonts and timings)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.animation.palette import hex_to_rgb
from src.config.settings import PROJECT_ROOT

STYLE_FILE = PROJECT_ROOT / "config" / "style.yaml"
RGB = Tuple[float, float, float]


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StylePalette(_S):
    paper: str = "#FBF7EE"
    paper_shade: str = "#EFE6D2"
    ink: str = "#2B2D42"
    caption: str = "#FFFFFF"
    caption_active: str = "#FFD23F"
    highlight: str = "#FF5D73"
    accents: List[str] = Field(default_factory=lambda: ["#2EC4B6", "#FF9F1C", "#8E7DFF", "#FF5D73"])

    @field_validator("paper", "paper_shade", "ink", "caption", "caption_active", "highlight")
    @classmethod
    def _hex(cls, v: str) -> str:
        hex_to_rgb(v)
        return v

    def rgb(self, name: str) -> RGB:
        return hex_to_rgb(getattr(self, name))

    def accent(self, i: int) -> RGB:
        return hex_to_rgb(self.accents[i % len(self.accents)])


class StyleFonts(_S):
    caption: str = "Lilita One"
    headline: str = "Luckiest Guy"
    hand: str = "Patrick Hand"


class StyleCamera(_S):
    zoom: float = Field(0.16, ge=0, le=0.5)
    pan: float = Field(0.07, ge=0, le=0.3)
    base_zoom: float = Field(1.06, ge=1.0, le=1.5)
    punch: float = Field(0.13, ge=0, le=0.5)
    punch_in_s: float = 0.12
    punch_hold_s: float = 0.45
    punch_out_s: float = 0.5
    shake_px: float = 18
    shake_s: float = 0.55
    sway_deg: float = 0.8


class StyleAnimation(_S):
    pop_s: float = 0.42
    pop_overshoot: float = Field(1.1, ge=1.0, le=1.5)
    draw_on_s: float = 1.1
    boil_fps: float = Field(8, gt=0, le=30)
    boil_amount: float = Field(1.6, ge=0, le=8)
    idle_bob: float = 0.03


class StyleBeats(_S):
    max_gap_s: float = Field(1.8, gt=0.5)
    target_gap_s: float = Field(1.6, gt=0.5)


class StyleTransitions(_S):
    duration_s: float = Field(0.26, ge=0.1, le=1.0)


class StyleCaptions(_S):
    center_y: float = Field(0.675, gt=0, lt=1)
    center_y_horizontal: float = Field(0.86, gt=0, lt=1)
    size: float = 96
    max_words: int = Field(3, ge=1, le=8)
    max_chars: int = Field(20, ge=6, le=60)
    uppercase: bool = True
    outline: float = 0.2
    shadow: bool = True


class StyleHost(_S):
    scale: float = Field(1.0, gt=0.3, le=2.0)


class Style(_S):
    palette: StylePalette = Field(default_factory=StylePalette)
    fonts: StyleFonts = Field(default_factory=StyleFonts)
    camera: StyleCamera = Field(default_factory=StyleCamera)
    animation: StyleAnimation = Field(default_factory=StyleAnimation)
    beats: StyleBeats = Field(default_factory=StyleBeats)
    transitions: StyleTransitions = Field(default_factory=StyleTransitions)
    captions: StyleCaptions = Field(default_factory=StyleCaptions)
    host: StyleHost = Field(default_factory=StyleHost)


def load_style(path: Optional[Path] = None) -> Style:
    p = Path(path) if path else STYLE_FILE
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return Style.model_validate(data or {})


@lru_cache(maxsize=1)
def get_style() -> Style:
    return load_style()
