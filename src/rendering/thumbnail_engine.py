"""Thumbnail renderer: colourful, high-contrast, mascot + one main visual + <= 4 words.

Renders each thumbnail concept at 1280x720 (YouTube) and a 1080x1920 cover frame for
Shorts/TikTok, using the same vector assets and rig as the videos (brand consistency).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import cairo
from PIL import Image

from src.animation.asset_manager import get_asset_manager
from src.animation.backgrounds import Background
from src.animation.character_rig import Placement, draw_character, load_character, make_pose
from src.animation.doodle_engine import Burst, Sparkle, StarDoodle, fill_poly, rounded_rect, star_points
from src.animation.expression_engine import expression_state, with_overrides
from src.animation.palette import PALETTE
from src.animation.text_render import TextStyle, draw_lines, fit_size
from src.utils.fonts import TITLE_FONT


@dataclass
class ThumbnailConcept:
    name: str
    text: str                 # <= 4 words
    asset: str                # main visual
    expression: str = "surprised"
    pose: str = "surprised"
    background: str = "burst_purple"
    accent: str = "yellow"
    rationale: str = ""


def _render(concept: ThumbnailConcept, W: int, H: int, char_id: str = "milo") -> cairo.ImageSurface:
    am = get_asset_manager()
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surf)
    Background(concept.background, W, H, seed=11).draw(ctx, 2.0)
    u = min(W, H) / 720 if W > H else W / 1080
    vertical = H > W
    # main visual with glow + burst
    a = am.get(concept.asset)
    if vertical:
        cx, cy, h = W * 0.5, H * 0.4, H * 0.3
    else:
        cx, cy, h = W * 0.7, H * 0.55, H * 0.62
    glow = cairo.RadialGradient(cx, cy, 0, cx, cy, h * 0.85)
    glow.add_color_stop_rgba(0, 1, 1, 1, 0.75)
    glow.add_color_stop_rgba(1, 1, 1, 1, 0.0)
    ctx.rectangle(0, 0, W, H)
    ctx.set_source(glow)
    ctx.fill()
    b = Burst(center=(cx, cy), r0=h * 0.55 / u, r1=h * 0.75 / u, rays=14, start=0, duration=0.5,
              color=PALETTE[concept.accent], unit=u)
    b.draw(ctx, 0.5)
    a.draw(ctx, cx, cy, min(h, W * 0.5 / a.aspect), rotation=-6)
    for i, (dx, dy, r) in enumerate(((-0.5, -0.45, 40), (0.48, -0.38, 28), (0.42, 0.42, 34))):
        Sparkle(center=(cx + dx * h, cy + dy * h), radius=r, start=0, duration=0.1, unit=u).draw(ctx, 0.7)
    # mascot
    style = load_character(char_id)
    pose = make_pose(concept.pose)
    face = with_overrides(expression_state(concept.expression), look_x=0.6, look_y=-0.2, head_turn=0.25)
    if vertical:
        draw_character(ctx, style, pose, face, Placement(W * 0.3, H * 0.8, H * 0.42, 1))
    else:
        draw_character(ctx, style, pose, face, Placement(W * 0.24, H * 1.13, H * 1.12, 1))
    # text
    st = TextStyle(font=TITLE_FONT, size=(120 if not vertical else 130) * u, color=PALETTE["yellow"],
                   outline=PALETTE["ink"], shadow=True)
    max_w = W * (0.56 if not vertical else 0.88)
    size, lines = fit_size(ctx, concept.text.upper(), st, max_w, 2, 40 * u)
    st.size = size
    st.outline_width = size * 0.22
    tx = W * (0.5 if vertical else 0.64)
    ty = H * (0.06 if vertical else 0.05)
    ctx.save()
    ctx.translate(tx, ty + size)
    ctx.rotate(math.radians(-4))
    cols = [PALETTE["yellow"], (1, 1, 1)]
    draw_lines(ctx, lines, 0, -size, st, "center", line_colors=cols)
    ctx.restore()
    # brand tag
    tag = TextStyle(font=TITLE_FONT, size=30 * u, color=(1, 1, 1), outline=PALETTE["ink"], outline_width=6 * u)
    rounded_rect(ctx, 18 * u, H - 64 * u, 290 * u, 48 * u, 16 * u)
    ctx.set_source_rgb(*PALETTE["teal"])
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(4 * u)
    ctx.stroke()
    draw_lines(ctx, ["CURIOUS MINDS"], 18 * u + 145 * u, H - 60 * u, tag, "center")
    StarDoodle(center=(W - 60 * u, 60 * u), radius=30, start=0, duration=0.1, unit=u).draw(ctx, 0.5)
    surf.flush()
    return surf


def render_thumbnails(concepts: List[ThumbnailConcept], out_dir: Path, char_id: str = "milo",
                      size=(1280, 720)) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    for i, c in enumerate(concepts, 1):
        for W, H, suffix in ((size[0], size[1], "16x9"), (1080, 1920, "9x16")):
            surf = _render(c, W, H, char_id)
            png = out_dir / f"thumbnail_{i}_{c.name}_{suffix}.png"
            surf.write_to_png(str(png))
            jpg = png.with_suffix(".jpg")
            Image.open(png).convert("RGB").save(jpg, quality=92)   # YouTube limit is 2 MB
            png.unlink()
            paths.append(jpg)
    return paths


def default_concepts(topic: str, main_asset: str, alt_asset: Optional[str] = None,
                     short_text: Optional[str] = None) -> List[ThumbnailConcept]:
    words = [w for w in topic.replace("?", "").split() if w]
    if not short_text and len(words) > 4:
        # start at the subject: the tail is often filler ("...Substance on Earth?" for a topic about water)
        from src.research.researcher import keywords
        subject = keywords(topic)[0]
        i = next((k for k, w in enumerate(words) if w.lower().startswith(subject[:5])), len(words) - 3)
        short_text = " ".join(words[i:i + 4]) + "?"
    text = short_text or " ".join(words) + "?"
    return [
        ThumbnailConcept("question", text if len(text.split()) <= 4 else " ".join(text.split()[:4]), main_asset,
                         "surprised", "surprised", "burst_purple", "yellow",
                         "Mascot surprised by the main visual; the topic as a short question."),
        ThumbnailConcept("discovery", "THE SCIENCE!" if not alt_asset else "WHAT'S HAPPENING?", alt_asset or main_asset,
                         "excited", "point_forward", "burst_teal", "orange",
                         "Mascot pointing at the key visual; promise of an explanation."),
    ]


_ = (fill_poly, star_points)
