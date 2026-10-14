"""Scene transitions implemented as colourful cover / reveal overlays.

A transition between scene A and scene B is split into two halves: the last
``DURATION`` seconds of A are progressively *covered* by the transition graphic,
and the first ``DURATION`` seconds of B are *revealed* from under the same graphic.
Because each half only needs its own scene, scenes can be rendered independently
(and in parallel) while the cut point stays seamless.
"""
from __future__ import annotations

import math
import random
from typing import Tuple

import cairo

from src.animation.doodle_engine import star_points
from src.animation.easing import clamp, ease_in_cubic, ease_in_out_cubic, ease_out_cubic
from src.animation.palette import PALETTE

DURATION = 0.42
TRANSITION_COLORS = {
    "circle_wipe": "teal", "doodle_swipe": "orange", "slide": "purple", "star_zoom": "yellow",
    "dots": "coral", "dip_cream": "cream", "blinds": "blue",
}


def _shape(ctx: cairo.Context, kind: str, cover: float, w: float, h: float, seed: int) -> None:
    """Build the covered region (path) for coverage `cover` in 0..1."""
    diag = math.hypot(w, h)
    u = min(w, h) / 1080
    if kind == "circle_wipe":
        ctx.arc(w / 2, h / 2, diag / 2 * cover + 1, 0, 2 * math.pi)
    elif kind == "star_zoom":
        pts = star_points(w / 2, h / 2, diag * 1.15 * cover + 1, 5, 0.5, -90 + 90 * cover)
        ctx.move_to(*pts[0])
        for p in pts[1:]:
            ctx.line_to(*p)
        ctx.close_path()
    elif kind == "slide":
        x = -w * 0.35 + (w * 1.7) * cover
        ctx.move_to(-10, -10)
        ctx.line_to(x + w * 0.2, -10)
        ctx.line_to(x - w * 0.2, h + 10)
        ctx.line_to(-10, h + 10)
        ctx.close_path()
    elif kind == "blinds":
        n = 8
        for i in range(n):
            f = clamp(cover * 1.6 - i * 0.6 / n)
            bh = h / n
            ctx.rectangle(0, i * bh, w * f, bh + 1)
    elif kind == "dots":
        step = 120 * u
        cols, rows = int(w / step) + 2, int(h / step) + 2
        for r in range(rows):
            for c in range(cols):
                d = (c / cols + r / rows) / 2
                f = clamp(cover * 1.8 - d * 0.8)
                if f > 0:
                    ctx.new_sub_path()
                    ctx.arc(c * step, r * step, step * 0.75 * f, 0, 2 * math.pi)
    elif kind == "doodle_swipe":
        # thick marker zig-zag strokes filling the frame
        rnd = random.Random(seed)
        n = 7
        bw = h / n * 1.5
        for i in range(n):
            f = clamp(cover * 1.5 - i * 0.5 / n)
            if f <= 0:
                continue
            y = (i + 0.5) * h / n + rnd.uniform(-10, 10) * u
            x0, x1 = (-bw, -bw + (w + 2 * bw) * f) if i % 2 == 0 else (w + bw, w + bw - (w + 2 * bw) * f)
            ctx.move_to(x0, y)
            ctx.line_to(x1, y + rnd.uniform(-20, 20) * u)
    else:  # dip_cream handled by alpha
        ctx.rectangle(0, 0, w, h)


def draw_transition(ctx: cairo.Context, kind: str, cover: float, w: float, h: float, seed: int = 0) -> None:
    """Draw the transition overlay at coverage `cover` (0 = invisible, 1 = fully covered)."""
    if kind == "cut" or cover <= 0.0:
        return
    col = PALETTE[TRANSITION_COLORS.get(kind, "teal")]
    ink = PALETTE["ink"]
    u = min(w, h) / 1080
    if kind == "dip_cream":
        # soft dip to cream with a popping brand spark, so the dip frame is never flat
        c = clamp(cover)
        ctx.rectangle(0, 0, w, h)
        ctx.set_source_rgba(*col, 0.82 * c)
        ctx.fill()
        if c > 0.04:
            k = min(1.0, 0.35 + c)
            pts = star_points(w / 2, h / 2, 190 * u * k, 4, 0.32, -90 + 40 * c)
            ctx.move_to(*pts[0])
            for p in pts[1:]:
                ctx.line_to(*p)
            ctx.close_path()
            ctx.set_source_rgba(*PALETTE["yellow"], k)
            ctx.fill_preserve()
            ctx.set_source_rgba(*ink, k)
            ctx.set_line_width(8 * u)
            ctx.stroke()
        return
    if cover >= 0.999:
        ctx.rectangle(0, 0, w, h)
        ctx.set_source_rgb(*col)
        ctx.fill()
        _logo_mark(ctx, w, h, u)
        return
    ctx.new_path()
    _shape(ctx, kind, cover, w, h, seed)
    if kind == "doodle_swipe":
        # strokes are drawn into a group; the brand pattern is composited ATOP them only
        ctx.push_group()
        ctx.append_path(ctx.copy_path())
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.set_source_rgb(*ink)
        ctx.set_line_width(h / 7 * 1.5 + 14 * u)
        ctx.stroke_preserve()
        ctx.set_source_rgb(*col)
        ctx.set_line_width(h / 7 * 1.5)
        ctx.stroke()
        ctx.set_operator(cairo.OPERATOR_ATOP)
        _logo_mark(ctx, w, h, u)
        ctx.pop_group_to_source()
        ctx.paint()
        return
    path = ctx.copy_path()
    ctx.set_source_rgb(*col)
    ctx.fill_preserve()
    ctx.save()
    ctx.clip()
    _logo_mark(ctx, w, h, u)
    ctx.restore()
    ctx.append_path(path)
    ctx.set_source_rgb(*ink)
    ctx.set_line_width(12 * u)
    ctx.stroke()


def _logo_mark(ctx: cairo.Context, w: float, h: float, u: float) -> None:
    """Brand pattern on a fully covered frame (the cut point): stripes, sparkles and a big spark.

    A cover frame must never be a flat colour (that would read as a blank frame)."""
    ctx.save()
    ctx.set_source_rgba(1, 1, 1, 0.16)
    step = 90 * u
    x = -h
    while x < w + h:
        ctx.move_to(x, 0)
        ctx.line_to(x + 40 * u, 0)
        ctx.line_to(x + 40 * u + h * 0.6, h)
        ctx.line_to(x + h * 0.6, h)
        ctx.close_path()
        x += step
    ctx.fill()
    rnd = random.Random(7)
    for _ in range(14):
        px, py, r = rnd.random() * w, rnd.random() * h, (10 + 22 * rnd.random()) * u
        pts = star_points(px, py, r, 4, 0.3)
        ctx.move_to(*pts[0])
        for p in pts[1:]:
            ctx.line_to(*p)
        ctx.close_path()
        ctx.set_source_rgba(1, 1, 1, 0.75)
        ctx.fill()
    pts = star_points(w / 2, h / 2, 130 * u, 4, 0.32)
    ctx.move_to(*pts[0])
    for p in pts[1:]:
        ctx.line_to(*p)
    ctx.close_path()
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(8 * u)
    ctx.stroke()
    ctx.restore()


def coverage(t: float, scene_duration: float, kind_in: str, kind_out: str) -> Tuple[str, float]:
    """Return (kind, cover) for scene-relative time t."""
    if kind_out != "cut" and t >= scene_duration - DURATION:
        return kind_out, ease_in_cubic(clamp((t - (scene_duration - DURATION)) / DURATION)) if kind_out != "doodle_swipe" \
            else ease_in_out_cubic(clamp((t - (scene_duration - DURATION)) / DURATION))
    if kind_in != "cut" and t < DURATION:
        return kind_in, 1.0 - ease_out_cubic(clamp(t / DURATION))
    return "cut", 0.0
