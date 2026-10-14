"""Locked Curious Minds brand palette and line language.

All assets, backgrounds, doodles and captions draw from this palette so every
episode shares the same visual identity. See docs/BRAND_GUIDE.md.
"""
from __future__ import annotations

from typing import Dict, Tuple

RGB = Tuple[float, float, float]


def hex_to_rgb(h: str) -> RGB:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


PALETTE_HEX: Dict[str, str] = {
    "ink": "#2B2D42",          # universal outline colour
    "ink_soft": "#4A4E69",
    "white": "#FFFFFF",
    "cream": "#FFF8E7",
    "paper": "#FDF6E3",
    "teal": "#2EC4B6",
    "teal_dark": "#1A9E92",
    "teal_light": "#9BE7DF",
    "orange": "#FF9F1C",
    "orange_dark": "#E07B00",
    "yellow": "#FFD23F",
    "yellow_light": "#FFE98A",
    "coral": "#FF5D73",
    "pink": "#FF8FAB",
    "pink_light": "#FFD6E0",
    "purple": "#8E7DFF",
    "purple_dark": "#5B4BC4",
    "lavender": "#CFC6FF",
    "blue": "#3A86FF",
    "sky": "#8ECAE6",
    "sky_light": "#D7F0FA",
    "green": "#06D6A0",
    "leaf": "#7BD389",
    "night": "#1B1F3B",
    "midnight": "#2A2E5C",
    "skin": "#F8C9A0",
    "skin_shadow": "#E9A97F",
    "hair": "#5B3A29",
    "navy": "#3D405B",
    "red": "#EF476F",
    "grey": "#B8BCC8",
}

PALETTE: Dict[str, RGB] = {k: hex_to_rgb(v) for k, v in PALETTE_HEX.items()}

# Accent cycle used to colour list items / diagram nodes so scenes stay varied.
ACCENTS = ["teal", "orange", "purple", "coral", "blue", "green", "yellow", "pink"]

# Line language: stroke widths in *pixels at 1080p short-side*; scaled per profile.
STROKE_BOLD = 7.0
STROKE_REGULAR = 5.0
STROKE_FINE = 3.0


def color(name_or_hex: str, alpha: float = 1.0) -> Tuple[float, float, float, float]:
    rgb = PALETTE[name_or_hex] if name_or_hex in PALETTE else hex_to_rgb(name_or_hex)
    return (rgb[0], rgb[1], rgb[2], alpha)


def mix(a: RGB, b: RGB, t: float) -> RGB:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def lighten(c: RGB, t: float) -> RGB:
    return mix(c, (1.0, 1.0, 1.0), t)


def darken(c: RGB, t: float) -> RGB:
    return mix(c, (0.0, 0.0, 0.0), t)
