"""Text layout helpers on top of Cairo's text API (brand fonts via fontconfig)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cairo

from src.utils.fonts import CAPTION_FONT

RGB = Tuple[float, float, float]


@dataclass
class TextStyle:
    font: str = CAPTION_FONT
    size: float = 48
    color: RGB = (1, 1, 1)
    outline: Optional[RGB] = (0.169, 0.176, 0.259)
    outline_width: float = 0.0     # absolute px; 0 = auto (size * 0.16) when outline set
    shadow: bool = False
    line_spacing: float = 1.12
    bold: bool = False


def _select(ctx: cairo.Context, st: TextStyle) -> None:
    ctx.select_font_face(st.font, cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD if st.bold else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(st.size)


def text_width(ctx: cairo.Context, text: str, st: TextStyle) -> float:
    _select(ctx, st)
    return ctx.text_extents(text).x_advance


def wrap_text(ctx: cairo.Context, text: str, st: TextStyle, max_width: float) -> List[str]:
    _select(ctx, st)
    words = text.split()
    lines: List[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if ctx.text_extents(trial).x_advance <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_size(ctx: cairo.Context, text: str, st: TextStyle, max_width: float, max_lines: int,
             min_size: float = 18) -> Tuple[float, List[str]]:
    """Largest font size (<= st.size) whose wrap fits in max_lines."""
    size = st.size
    while True:
        s2 = TextStyle(**{**st.__dict__, "size": size})
        lines = wrap_text(ctx, text, s2, max_width)
        if len(lines) <= max_lines or size <= min_size:
            return size, lines
        size *= 0.92


def block_height(st: TextStyle, n_lines: int) -> float:
    return st.size * (1 + (n_lines - 1) * st.line_spacing)


def draw_lines(ctx: cairo.Context, lines: Sequence[str], x: float, y: float, st: TextStyle,
               align: str = "center", alpha: float = 1.0, line_colors: Optional[Sequence[RGB]] = None) -> None:
    """Draw lines with the *first baseline-box top* at y. align: left|center|right relative to x."""
    if alpha <= 0.001 or not lines:
        return
    _select(ctx, st)
    fe = ctx.font_extents()
    ascent = fe[0]
    for i, line in enumerate(lines):
        ext = ctx.text_extents(line)
        w = ext.x_advance
        lx = x - w / 2 if align == "center" else (x - w if align == "right" else x)
        ly = y + ascent * 0.92 + i * st.size * st.line_spacing
        ctx.new_path()
        ctx.move_to(lx, ly)
        ctx.text_path(line)
        if st.shadow:
            ctx.save()
            ctx.translate(0, st.size * 0.07)
            ctx.set_source_rgba(0.1, 0.1, 0.15, 0.35 * alpha)
            ctx.fill_preserve()
            ctx.restore()
        if st.outline is not None:
            ow = st.outline_width or st.size * 0.16
            ctx.set_source_rgba(*st.outline, alpha)
            ctx.set_line_width(ow)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.stroke_preserve()
        col = line_colors[i] if line_colors and i < len(line_colors) else st.color
        ctx.set_source_rgba(*col, alpha)
        ctx.fill()


def draw_text_box(ctx: cairo.Context, text: str, cx: float, top: float, st: TextStyle, max_width: float,
                  max_lines: int = 3, alpha: float = 1.0) -> Tuple[float, float]:
    """Wrap + auto-fit + centre. Returns (width, height) of the block."""
    size, lines = fit_size(ctx, text, st, max_width, max_lines)
    st2 = TextStyle(**{**st.__dict__, "size": size})
    draw_lines(ctx, lines, cx, top, st2, "center", alpha)
    _select(ctx, st2)
    w = max((ctx.text_extents(ln).x_advance for ln in lines), default=0)
    return w, block_height(st2, len(lines))
