"""Quick (0.2-0.3 s) lively transitions, split into an "out" half and an "in" half.

As in the classic engine, the last half-duration of scene A and the first half-duration of
scene B each render on their own, so scenes stay independent (parallel rendering). Whips and
the zoom-through move the stage content (with motion blur and speed lines) over the shared
paper background; the ink swipe covers the cut point with thick marker strokes.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import cairo

from src.animation.easing import clamp, ease_in_cubic, ease_out_cubic
from src.lively.style import Style

# classic transitions used in a lively storyboard are mapped onto lively ones
FROM_CLASSIC = {"circle_wipe": "zoom_through", "star_zoom": "zoom_through", "dots": "zoom_through",
                "slide": "whip_left", "blinds": "whip_up", "doodle_swipe": "ink_swipe", "dip_cream": "zoom_through"}
LIVELY = ("whip_left", "whip_right", "whip_up", "zoom_through", "ink_swipe")


def lively_kind(kind: str) -> str:
    if kind == "cut" or kind in LIVELY:
        return kind
    return FROM_CLASSIC.get(kind, "whip_left")


@dataclass
class Phase:
    kind: str
    side: str          # "out" (end of the outgoing scene) | "in" (start of the incoming scene)
    q: float           # 0 = far from the cut .. 1 = at the cut


def phase_at(t: float, duration: float, kind_in: str, kind_out: str, half: float) -> Optional[Phase]:
    if kind_out != "cut" and t >= duration - half:
        return Phase(lively_kind(kind_out), "out", clamp((t - (duration - half)) / half))
    if kind_in != "cut" and t < half:
        return Phase(lively_kind(kind_in), "in", clamp(1 - t / half))
    return None


def _offset(ph: Phase, W: int, H: int) -> Tuple[float, float, float]:
    """(dx, dy, scale) applied to the stage for this phase."""
    e = ease_in_cubic(ph.q)
    sign = -1 if ph.side == "out" else 1          # out: leaves towards -x; in: arrives from +x
    if ph.kind == "whip_left":
        return sign * W * 1.15 * e, 0.0, 1.0
    if ph.kind == "whip_right":
        return -sign * W * 1.15 * e, 0.0, 1.0
    if ph.kind == "whip_up":
        return 0.0, sign * H * 1.05 * e, 1.0
    if ph.kind == "zoom_through":
        return 0.0, 0.0, (1 + 3.0 * e) if ph.side == "out" else (1 - 0.55 * e)
    return 0.0, 0.0, 1.0


def draw_stage_with_transition(ctx: cairo.Context, draw_stage: Callable[[cairo.Context], None], ph: Optional[Phase],
                               W: int, H: int, fps: int, style: Style, seed: int = 0) -> None:
    """Draw the stage (already camera-transformed by draw_stage) moved by the transition, with motion blur."""
    if ph is None or ph.kind == "ink_swipe":
        draw_stage(ctx)
        if ph is not None:
            _ink_swipe(ctx, ph, W, H, style, seed)
        return
    # sample the motion over one frame for blur; alpha fades content in the zoom-through
    dt_q = 1.0 / max(1.0, style.transitions.duration_s / 2 * fps)
    samples = 4 if ph.q > 0.05 else 1
    alpha_total = 1.0
    if ph.kind == "zoom_through":
        alpha_total = 1 - ease_in_cubic(ph.q) ** 1.5
    for i in range(samples):
        q = clamp(ph.q - dt_q * i / samples * (1 if ph.side == "out" else -1))
        dx, dy, s = _offset(Phase(ph.kind, ph.side, q), W, H)
        ctx.save()
        ctx.translate(W / 2 + dx, H / 2 + dy)
        ctx.scale(s, s)
        ctx.translate(-W / 2, -H / 2)
        ctx.push_group()
        draw_stage(ctx)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(alpha_total / samples if samples > 1 else alpha_total)
        ctx.restore()
    _speed_lines(ctx, ph, W, H, style, seed)


def _speed_lines(ctx: cairo.Context, ph: Phase, W: int, H: int, style: Style, seed: int) -> None:
    k = ease_out_cubic(clamp(ph.q * 1.6))        # strongest at the cut, so that frame is never flat
    if k <= 0.05:
        return
    u = min(W, H) / 1080
    rnd = random.Random(seed * 13 + (1 if ph.side == "in" else 0))
    ink = style.palette.rgb("ink")
    ctx.save()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for i in range(14):
        col = style.palette.accent(i) if i % 3 else ink
        ctx.set_source_rgba(*col, 0.55 * k)
        ctx.set_line_width((5 + 7 * rnd.random()) * u)
        if ph.kind == "zoom_through":
            a = rnd.random() * 2 * math.pi
            r0 = (0.18 + 0.2 * rnd.random()) * max(W, H)
            r1 = r0 + (0.15 + 0.25 * rnd.random()) * max(W, H) * k
            ctx.move_to(W / 2 + math.cos(a) * r0, H / 2 + math.sin(a) * r0)
            ctx.line_to(W / 2 + math.cos(a) * r1, H / 2 + math.sin(a) * r1)
        elif ph.kind == "whip_up":
            x = rnd.random() * W
            y0 = rnd.random() * H
            ctx.move_to(x, y0)
            ctx.line_to(x, y0 + (0.2 + 0.3 * rnd.random()) * H * k)
        else:
            y = rnd.random() * H
            x0 = rnd.random() * W
            ctx.move_to(x0, y)
            ctx.line_to(x0 + (0.25 + 0.35 * rnd.random()) * W * k, y)
        ctx.stroke()
    ctx.restore()


def _ink_swipe(ctx: cairo.Context, ph: Phase, W: int, H: int, style: Style, seed: int) -> None:
    """Thick marker strokes sweep across and fully cover the frame at the cut."""
    u = min(W, H) / 1080
    cover = ease_in_cubic(ph.q) if ph.side == "out" else ease_out_cubic(ph.q)
    if cover <= 0.001:
        return
    n = 5
    band = math.hypot(W, H) / n * 1.25
    ink = style.palette.rgb("ink")
    ctx.save()
    ctx.translate(W / 2, H / 2)
    ctx.rotate(math.radians(-24))
    span = math.hypot(W, H)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for i in range(n):
        f = clamp(cover * 1.45 - i * 0.45 / n)
        if f <= 0:
            continue
        y = -span / 2 + (i + 0.5) * span / n
        if ph.side == "out":
            x0, x1 = -span / 2 - band, -span / 2 - band + (span + 2 * band) * f
        else:                                     # reveal: strokes leave on the far side
            x0, x1 = span / 2 + band - (span + 2 * band) * f, span / 2 + band
        ctx.move_to(x0, y)
        ctx.line_to(x1, y)
        ctx.set_source_rgb(*ink)
        ctx.set_line_width(band + 14 * u)
        ctx.stroke_preserve()
        ctx.set_source_rgb(*style.palette.accent(i + seed))
        ctx.set_line_width(band)
        ctx.stroke()
    ctx.restore()
