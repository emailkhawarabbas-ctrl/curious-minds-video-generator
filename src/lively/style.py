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
    float_px: float = 6.0     # slow hand-held float (px at 1080 short side)
    max_punches: int = Field(99, ge=0)   # punch-ins per scene
    punch_overshoot: bool = True         # springy punch (True) or a smooth ease (False)


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


def _calm_camera() -> "StyleCamera":
    return StyleCamera(zoom=0.04, pan=0.0, base_zoom=1.02, punch=0.06, punch_in_s=0.45, punch_hold_s=0.7,
                       punch_out_s=0.8, shake_px=8, shake_s=0.4, sway_deg=0.0, float_px=0.0, max_punches=1,
                       punch_overshoot=False)


class WhiteboardDrawing(_S):
    scene_fraction: float = Field(0.6, ge=0.3, le=0.85)   # share of the scene the main drawing takes
    min_s: float = Field(1.4, gt=0.2)                      # never faster than this
    max_s: float = Field(7.0, gt=0.5)
    fill_s: float = Field(0.55, ge=0.1, le=2.0)            # colour fades in after the last line
    lift_s: float = Field(0.07, ge=0, le=0.5)              # pen lift between strokes
    outline_fills: bool = True                             # trace an outline around fill-only shapes
    boil_amount: float = Field(0.8, ge=0, le=8)            # line wobble once drawn (viewBox units)
    boil_fps: float = Field(6, gt=0, le=30)
    text_size: float = 92                                  # handwritten labels (px at 1080 short side)
    text_s_per_char: float = Field(0.09, gt=0.01, le=0.5)
    text_font: str = "Patrick Hand"
    underline: bool = True


class WhiteboardHand(_S):
    show: bool = True
    size: float = Field(0.42, gt=0.05, le=1.0)             # hand height as a fraction of the frame's short side
    lift_px: float = 16                                    # how far the pen lifts off the board between strokes
    travel_s: float = Field(0.4, gt=0.05)                  # move between drawings
    rest_after_s: float = Field(1.0, gt=0.1)               # leave the frame when idle longer than this
    shadow: float = Field(0.14, ge=0, le=1)


class WhiteboardHost(_S):
    draw_labels: bool = True        # a host whose action is "draw" writes the keyword itself
    count_step_s: float = Field(0.55, gt=0.1)


class WhiteboardStyle(_S):
    camera: StyleCamera = Field(default_factory=_calm_camera)
    drawing: WhiteboardDrawing = Field(default_factory=WhiteboardDrawing)
    hand: WhiteboardHand = Field(default_factory=WhiteboardHand)
    host: WhiteboardHost = Field(default_factory=WhiteboardHost)


class Style(_S):
    palette: StylePalette = Field(default_factory=StylePalette)
    fonts: StyleFonts = Field(default_factory=StyleFonts)
    camera: StyleCamera = Field(default_factory=StyleCamera)
    animation: StyleAnimation = Field(default_factory=StyleAnimation)
    beats: StyleBeats = Field(default_factory=StyleBeats)
    transitions: StyleTransitions = Field(default_factory=StyleTransitions)
    captions: StyleCaptions = Field(default_factory=StyleCaptions)
    host: StyleHost = Field(default_factory=StyleHost)
    whiteboard: WhiteboardStyle = Field(default_factory=WhiteboardStyle)

    @field_validator("whiteboard", mode="before")
    @classmethod
    def _wb_camera(cls, v):
        # a partial whiteboard.camera in the YAML only overrides the calm defaults it names
        if isinstance(v, dict) and isinstance(v.get("camera"), dict):
            v = {**v, "camera": {**_calm_camera().model_dump(), **v["camera"]}}
        return v


def load_style(path: Optional[Path] = None) -> Style:
    p = Path(path) if path else STYLE_FILE
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    return Style.model_validate(data or {})


@lru_cache(maxsize=1)
def get_style() -> Style:
    return load_style()
