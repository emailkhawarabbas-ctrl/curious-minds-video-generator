"""Procedural, on-brand scene backgrounds.

Each background has a static layer (rendered once per scene into a cached surface,
slightly larger than the frame so camera moves never reveal edges) and an optional
animated ambient layer drawn every frame (twinkling stars, drifting clouds, rays).
"""
from __future__ import annotations

import math
import random
from typing import Callable, Dict, Tuple

import cairo

from src.animation.doodle_engine import fill_poly, rounded_rect, star_points
from src.animation.palette import PALETTE, darken, lighten, mix

RGB = Tuple[float, float, float]
OVERSCAN = 1.12   # static layer is 12 % larger than the frame for camera moves


def _vgrad(ctx: cairo.Context, w: float, h: float, top: RGB, bottom: RGB) -> None:
    g = cairo.LinearGradient(0, 0, 0, h)
    g.add_color_stop_rgb(0, *top)
    g.add_color_stop_rgb(1, *bottom)
    ctx.rectangle(0, 0, w, h)
    ctx.set_source(g)
    ctx.fill()


def _rgrad(ctx: cairo.Context, w: float, h: float, inner: RGB, outer: RGB, cx: float = 0.5, cy: float = 0.4) -> None:
    g = cairo.RadialGradient(w * cx, h * cy, 0, w * cx, h * cy, max(w, h) * 0.75)
    g.add_color_stop_rgb(0, *inner)
    g.add_color_stop_rgb(1, *outer)
    ctx.rectangle(0, 0, w, h)
    ctx.set_source(g)
    ctx.fill()


def _cloud(ctx: cairo.Context, x: float, y: float, s: float, color: RGB = (1, 1, 1), alpha: float = 1.0,
           outline: bool = False) -> None:
    ctx.new_path()
    for dx, dy, r in ((-0.55, 0.1, 0.38), (-0.15, -0.18, 0.5), (0.35, -0.05, 0.42), (0.7, 0.15, 0.3), (0.1, 0.2, 0.4)):
        ctx.new_sub_path()
        ctx.arc(x + dx * s, y + dy * s, r * s, 0, 2 * math.pi)
    if outline:
        ctx.set_source_rgba(*PALETTE["ink"], alpha)
        ctx.set_line_width(s * 0.06)
        ctx.stroke_preserve()
    ctx.set_source_rgba(*color, alpha)
    ctx.fill()


def _hills(ctx: cairo.Context, w: float, h: float, base_y: float, color: RGB, amp: float, seed: int) -> None:
    rnd = random.Random(seed)
    ctx.move_to(0, h)
    ctx.line_to(0, base_y)
    n = 6
    for i in range(n):
        x0 = w * i / n
        x1 = w * (i + 1) / n
        peak = base_y - amp * (0.5 + rnd.random() * 0.6)
        ctx.curve_to(x0 + (x1 - x0) * 0.3, peak, x0 + (x1 - x0) * 0.7, peak, x1, base_y)
    ctx.line_to(w, h)
    ctx.close_path()
    ctx.set_source_rgb(*color)
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(max(w, h) * 0.003)
    ctx.stroke()


def _stars_static(ctx: cairo.Context, w: float, h: float, n: int, seed: int, ymax: float = 1.0) -> None:
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.random() * w, rnd.random() * h * ymax
        r = rnd.uniform(1.5, 4.0) * max(w, h) / 1920
        ctx.arc(x, y, r, 0, 2 * math.pi)
        ctx.set_source_rgba(1, 1, 1, rnd.uniform(0.35, 0.9))
        ctx.fill()


def _doodle_dots(ctx: cairo.Context, w: float, h: float, color: RGB, alpha: float, step: float) -> None:
    ctx.set_source_rgba(*color, alpha)
    y = step / 2
    while y < h:
        x = step / 2
        while x < w:
            ctx.arc(x, y, step * 0.045, 0, 2 * math.pi)
            ctx.fill()
            x += step
        y += step


def _scribbles(ctx: cairo.Context, w: float, h: float, seed: int, colors, alpha: float = 0.22) -> None:
    """Faint decorative doodles (spirals, stars, plus signs) for paper backgrounds."""
    rnd = random.Random(seed)
    u = min(w, h) / 1080
    for i in range(14):
        x, y = rnd.random() * w, rnd.random() * h
        col = PALETTE[colors[i % len(colors)]]
        kind = i % 4
        ctx.set_line_width(5 * u)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_source_rgba(*col, alpha)
        if kind == 0:
            fill_poly(ctx, star_points(x, y, 22 * u, 5, 0.45, rnd.random() * 60), col, alpha, None)
        elif kind == 1:
            ctx.move_to(x - 16 * u, y)
            ctx.line_to(x + 16 * u, y)
            ctx.move_to(x, y - 16 * u)
            ctx.line_to(x, y + 16 * u)
            ctx.stroke()
        elif kind == 2:
            for k in range(30):
                a = k * 0.45
                r = 2 * u + k * 0.9 * u
                (ctx.move_to if k == 0 else ctx.line_to)(x + r * math.cos(a), y + r * math.sin(a))
            ctx.stroke()
        else:
            ctx.arc(x, y, 14 * u, 0, 2 * math.pi)
            ctx.stroke()


# --------------------------------------------------------------------------- static painters
def _paper(ctx, w, h, seed):
    _vgrad(ctx, w, h, PALETTE["cream"], mix(PALETTE["cream"], PALETTE["yellow_light"], 0.35))
    _doodle_dots(ctx, w, h, PALETTE["ink"], 0.08, min(w, h) / 18)
    _scribbles(ctx, w, h, seed, ("teal", "orange", "purple", "coral"))


def _bedroom_night(ctx, w, h, seed):
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, PALETTE["midnight"], mix(PALETTE["midnight"], PALETTE["purple_dark"], 0.5))
    floor_y = h * 0.78
    # wallpaper stripes
    ctx.set_source_rgba(1, 1, 1, 0.035)
    x = 0.0
    while x < w:
        ctx.rectangle(x, 0, 40 * u, floor_y)
        ctx.fill()
        x += 110 * u
    # window
    ww, wh = min(w * 0.36, 520 * u), min(h * 0.28, 440 * u)
    wx, wy = w * 0.62 - ww / 2, h * 0.14
    rounded_rect(ctx, wx - 16 * u, wy - 16 * u, ww + 32 * u, wh + 32 * u, 26 * u)
    ctx.set_source_rgb(*PALETTE["orange_dark"])
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(7 * u)
    ctx.stroke()
    rounded_rect(ctx, wx, wy, ww, wh, 16 * u)
    ctx.set_source_rgb(*PALETTE["night"])
    ctx.fill_preserve()
    ctx.save()
    ctx.clip()
    _stars_static(ctx, w, h, 40, seed)
    ctx.arc(wx + ww * 0.7, wy + wh * 0.35, wh * 0.18, 0, 2 * math.pi)
    ctx.set_source_rgb(*PALETTE["yellow_light"])
    ctx.fill()
    ctx.arc(wx + ww * 0.7 + wh * 0.08, wy + wh * 0.32, wh * 0.16, 0, 2 * math.pi)
    ctx.set_source_rgb(*PALETTE["night"])
    ctx.fill()
    ctx.restore()
    ctx.set_source_rgb(*PALETTE["orange_dark"])
    ctx.rectangle(wx + ww / 2 - 6 * u, wy, 12 * u, wh)
    ctx.rectangle(wx, wy + wh / 2 - 6 * u, ww, 12 * u)
    ctx.fill()
    # curtains
    for side in (-1, 1):
        cx = wx + (0 if side < 0 else ww)
        ctx.move_to(cx - side * 10 * u, wy - 40 * u)
        ctx.curve_to(cx + side * 60 * u, wy + wh * 0.4, cx + side * 30 * u, wy + wh * 0.8, cx + side * 70 * u, wy + wh + 50 * u)
        ctx.line_to(cx + side * 140 * u, wy + wh + 50 * u)
        ctx.line_to(cx + side * 120 * u, wy - 40 * u)
        ctx.close_path()
        ctx.set_source_rgb(*PALETTE["purple"])
        ctx.fill_preserve()
        ctx.set_source_rgb(*PALETTE["ink"])
        ctx.set_line_width(6 * u)
        ctx.stroke()
    # floor + rug
    ctx.rectangle(0, floor_y, w, h - floor_y)
    ctx.set_source_rgb(*darken(PALETTE["purple_dark"], 0.35))
    ctx.fill()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(6 * u)
    ctx.move_to(0, floor_y)
    ctx.line_to(w, floor_y)
    ctx.stroke()
    ctx.save()
    ctx.translate(w * 0.5, floor_y + (h - floor_y) * 0.45)
    ctx.scale(w * 0.34, (h - floor_y) * 0.22)
    ctx.arc(0, 0, 1, 0, 2 * math.pi)
    ctx.restore()
    ctx.set_source_rgba(*PALETTE["teal_dark"], 0.55)
    ctx.fill()
    # lamp glow
    g = cairo.RadialGradient(w * 0.15, h * 0.5, 0, w * 0.15, h * 0.5, w * 0.35)
    g.add_color_stop_rgba(0, *PALETTE["yellow_light"], 0.20)
    g.add_color_stop_rgba(1, *PALETTE["yellow_light"], 0.0)
    ctx.rectangle(0, 0, w, h)
    ctx.set_source(g)
    ctx.fill()


def _night_sky(ctx, w, h, seed):
    _vgrad(ctx, w, h, PALETTE["night"], PALETTE["purple_dark"])
    _stars_static(ctx, w, h, 160, seed, 0.75)
    u = min(w, h) / 1080
    mx, my, mr = w * 0.78, h * 0.18, 90 * u
    g = cairo.RadialGradient(mx, my, mr, mx, my, mr * 3)
    g.add_color_stop_rgba(0, *PALETTE["yellow_light"], 0.35)
    g.add_color_stop_rgba(1, *PALETTE["yellow_light"], 0)
    ctx.rectangle(0, 0, w, h)
    ctx.set_source(g)
    ctx.fill()
    ctx.arc(mx, my, mr, 0, 2 * math.pi)
    ctx.set_source_rgb(*PALETTE["yellow_light"])
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(6 * u)
    ctx.stroke()
    _hills(ctx, w, h, h * 0.80, mix(PALETTE["midnight"], PALETTE["teal_dark"], 0.35), 90 * u, seed)
    _hills(ctx, w, h, h * 0.88, mix(PALETTE["midnight"], PALETTE["teal_dark"], 0.6), 70 * u, seed + 1)


def _dreamscape(ctx, w, h, seed):
    _vgrad(ctx, w, h, PALETTE["purple_dark"], mix(PALETTE["pink"], PALETTE["purple"], 0.45))
    _stars_static(ctx, w, h, 70, seed, 0.7)
    u = min(w, h) / 1080
    rnd = random.Random(seed)
    for i in range(7):
        _cloud(ctx, rnd.random() * w, h * (0.15 + 0.7 * rnd.random()), (120 + 120 * rnd.random()) * u,
               lighten(PALETTE["lavender"], 0.3), 0.35 + 0.25 * rnd.random())
    # swirls
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for i in range(5):
        x, y = rnd.random() * w, rnd.random() * h
        ctx.set_source_rgba(1, 1, 1, 0.18)
        ctx.set_line_width(6 * u)
        for k in range(40):
            a = k * 0.35
            r = 4 * u + k * 2.2 * u
            (ctx.move_to if k == 0 else ctx.line_to)(x + r * math.cos(a), y + r * math.sin(a))
        ctx.stroke()
    _cloud(ctx, w * 0.5, h * 1.02, w * 0.55, lighten(PALETTE["lavender"], 0.5), 0.9)


def _lab(ctx, w, h, seed):
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, lighten(PALETTE["teal_light"], 0.45), lighten(PALETTE["teal_light"], 0.15))
    floor_y = h * 0.8
    # tiles
    ctx.set_source_rgba(1, 1, 1, 0.35)
    ctx.set_line_width(3 * u)
    step = 90 * u
    y = 0.0
    while y < floor_y:
        ctx.move_to(0, y)
        ctx.line_to(w, y)
        y += step
    ctx.stroke()
    # shelves with flasks & books
    rnd = random.Random(seed)
    for sy in (h * 0.22, h * 0.42):
        for sx0, sx1 in ((w * 0.04, w * 0.30), (w * 0.70, w * 0.96)):
            ctx.rectangle(sx0, sy, sx1 - sx0, 16 * u)
            ctx.set_source_rgb(*PALETTE["orange_dark"])
            ctx.fill_preserve()
            ctx.set_source_rgb(*PALETTE["ink"])
            ctx.set_line_width(5 * u)
            ctx.stroke()
            x = sx0 + 20 * u
            while x < sx1 - 60 * u:
                col = PALETTE[rnd.choice(["coral", "purple", "yellow", "blue", "green"])]
                kind = rnd.random()
                if kind < 0.5:
                    bh = (60 + 50 * rnd.random()) * u
                    rounded_rect(ctx, x, sy - bh, 30 * u, bh, 5 * u)
                    ctx.set_source_rgba(*col, 0.85)
                    ctx.fill_preserve()
                    ctx.set_source_rgb(*PALETTE["ink"])
                    ctx.stroke()
                    x += 36 * u
                else:
                    r = 26 * u
                    ctx.arc(x + r, sy - r, r, 0, 2 * math.pi)
                    ctx.set_source_rgba(*lighten(col, 0.2), 0.8)
                    ctx.fill_preserve()
                    ctx.set_source_rgb(*PALETTE["ink"])
                    ctx.stroke()
                    ctx.rectangle(x + r - 8 * u, sy - 2 * r - 26 * u, 16 * u, 30 * u)
                    ctx.set_source_rgb(1, 1, 1)
                    ctx.fill_preserve()
                    ctx.set_source_rgb(*PALETTE["ink"])
                    ctx.stroke()
                    x += 2 * r + 16 * u
    ctx.rectangle(0, floor_y, w, h - floor_y)
    ctx.set_source_rgb(*mix(PALETTE["teal_dark"], PALETTE["navy"], 0.4))
    ctx.fill()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(6 * u)
    ctx.move_to(0, floor_y)
    ctx.line_to(w, floor_y)
    ctx.stroke()


def _chalkboard(ctx, w, h, seed):
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, mix(PALETTE["orange_dark"], PALETTE["hair"], 0.6), PALETTE["hair"])
    m = 40 * u
    rounded_rect(ctx, m, m, w - 2 * m, h * 0.82 - m, 20 * u)
    ctx.set_source_rgb(0.17, 0.33, 0.28)
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(8 * u)
    ctx.stroke()
    rnd = random.Random(seed)
    ctx.set_source_rgba(1, 1, 1, 0.06)
    for _ in range(30):
        ctx.set_line_width(rnd.uniform(10, 40) * u)
        x, y = rnd.random() * w, rnd.random() * h * 0.8
        ctx.move_to(x, y)
        ctx.line_to(x + rnd.uniform(-200, 200) * u, y + rnd.uniform(-30, 30) * u)
        ctx.stroke()
    _scribbles(ctx, w, h * 0.8, seed, ("white", "yellow_light", "sky"), 0.25)


def _brain_space(ctx, w, h, seed):
    _rgrad(ctx, w, h, mix(PALETTE["purple"], PALETTE["midnight"], 0.55), PALETTE["night"])
    rnd = random.Random(seed)
    u = min(w, h) / 1080
    nodes = [(rnd.random() * w, rnd.random() * h) for _ in range(40)]
    ctx.set_line_width(2.5 * u)
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            d = math.hypot(a[0] - b[0], a[1] - b[1])
            if d < 260 * u:
                ctx.move_to(*a)
                ctx.line_to(*b)
                ctx.set_source_rgba(*PALETTE["lavender"], 0.12 * (1 - d / (260 * u)) + 0.04)
                ctx.stroke()
    for x, y in nodes:
        ctx.arc(x, y, 5 * u, 0, 2 * math.pi)
        ctx.set_source_rgba(*PALETTE["pink"], 0.35)
        ctx.fill()


def _sunny(ctx, w, h, seed):
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, PALETTE["sky"], lighten(PALETTE["sky_light"], 0.3))
    sx, sy, sr = w * 0.15, h * 0.13, 80 * u
    for i in range(12):
        a = i * math.pi / 6
        ctx.move_to(sx + math.cos(a) * sr * 1.3, sy + math.sin(a) * sr * 1.3)
        ctx.line_to(sx + math.cos(a) * sr * 1.75, sy + math.sin(a) * sr * 1.75)
    ctx.set_source_rgb(*PALETTE["yellow"])
    ctx.set_line_width(12 * u)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()
    ctx.arc(sx, sy, sr, 0, 2 * math.pi)
    ctx.set_source_rgb(*PALETTE["yellow"])
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(6 * u)
    ctx.stroke()
    _hills(ctx, w, h, h * 0.78, PALETTE["leaf"], 80 * u, seed)
    _hills(ctx, w, h, h * 0.87, mix(PALETTE["leaf"], PALETTE["green"], 0.5), 60 * u, seed + 3)


def _space(ctx, w, h, seed):
    _rgrad(ctx, w, h, PALETTE["midnight"], PALETTE["night"], 0.3, 0.3)
    _stars_static(ctx, w, h, 220, seed)
    u = min(w, h) / 1080
    ctx.arc(w * 0.88, h * 0.82, 160 * u, 0, 2 * math.pi)
    ctx.set_source_rgb(*PALETTE["coral"])
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(7 * u)
    ctx.stroke()


def _city(ctx, w, h, seed):
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, PALETTE["sky"], lighten(PALETTE["sky_light"], 0.2))
    rnd = random.Random(seed)
    base = h * 0.82
    x = 0.0
    while x < w:
        bw = (90 + 120 * rnd.random()) * u
        bh = (160 + 380 * rnd.random()) * u
        col = PALETTE[rnd.choice(["lavender", "teal_light", "pink_light", "sky", "yellow_light"])]
        rounded_rect(ctx, x, base - bh, bw, bh + 10 * u, 10 * u)
        ctx.set_source_rgb(*col)
        ctx.fill_preserve()
        ctx.set_source_rgb(*PALETTE["ink"])
        ctx.set_line_width(5 * u)
        ctx.stroke()
        for wy in range(int(bh / (50 * u)) - 1):
            for wx in range(int(bw / (40 * u))):
                ctx.rectangle(x + 14 * u + wx * 40 * u, base - bh + 20 * u + wy * 50 * u, 18 * u, 24 * u)
        ctx.set_source_rgba(1, 1, 1, 0.75)
        ctx.fill()
        x += bw + 12 * u
    ctx.rectangle(0, base, w, h - base)
    ctx.set_source_rgb(*PALETTE["grey"])
    ctx.fill()


def _burst_static(color: str) -> Callable:
    def paint(ctx, w, h, seed):
        _rgrad(ctx, w, h, lighten(PALETTE[color], 0.25), darken(PALETTE[color], 0.15), 0.5, 0.42)
    return paint


# --------------------------------------------------------------------------- niche environments
# Human Body ------------------------------------------------------------------
def _blob_cell(ctx, x, y, r, fill: RGB, u: float, alpha: float = 1.0, dimple: bool = True) -> None:
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(1, 0.72)
    ctx.arc(0, 0, r, 0, 2 * math.pi)
    ctx.restore()
    ctx.set_source_rgba(*fill, alpha)
    ctx.fill_preserve()
    ctx.set_source_rgba(*PALETTE["ink"], alpha)
    ctx.set_line_width(max(1.0, r * 0.09))
    ctx.stroke()
    if dimple:
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(1, 0.62)
        ctx.arc(0, 0, r * 0.48, 0, 2 * math.pi)
        ctx.restore()
        ctx.set_source_rgba(*darken(fill, 0.18), alpha)
        ctx.fill()


def _bloodstream(ctx, w, h, seed):
    """Inside a vessel: warm red lumen, curved wall bands, soft depth cells."""
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, mix(PALETTE["red"], PALETTE["coral"], 0.35), darken(PALETTE["red"], 0.32))
    for k, (y0, amp, col, a) in enumerate(((0.06, 40, "pink", 0.55), (0.94, -40, "pink", 0.55),
                                           (0.17, 26, "pink_light", 0.25), (0.83, -26, "pink_light", 0.25))):
        ctx.move_to(0, h * y0)
        for i in range(9):
            x0, x1 = w * i / 8, w * (i + 1) / 8
            ctx.curve_to(x0 + (x1 - x0) * 0.3, h * y0 + amp * u, x0 + (x1 - x0) * 0.7, h * y0 + amp * u, x1, h * y0)
        ctx.line_to(w, 0 if y0 < 0.5 else h)
        ctx.line_to(0, 0 if y0 < 0.5 else h)
        ctx.close_path()
        ctx.set_source_rgba(*PALETTE[col], a)
        ctx.fill()
    rnd = random.Random(seed)
    for _ in range(26):
        _blob_cell(ctx, rnd.random() * w, h * (0.2 + 0.6 * rnd.random()), (24 + 30 * rnd.random()) * u,
                   lighten(PALETTE["red"], 0.15), u, 0.28)


def _body_lab(ctx, w, h, seed):
    """Bright clinic: mint walls, anatomy poster, wall monitor frame, counter."""
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, lighten(PALETTE["teal_light"], 0.62), lighten(PALETTE["teal_light"], 0.32))
    _doodle_dots(ctx, w, h, PALETTE["teal_dark"], 0.06, min(w, h) / 16)
    floor_y = h * 0.82
    # anatomy poster (body outline with heart) top-left
    px, py, pw, ph = w * 0.05, h * 0.08, 210 * u, 300 * u
    rounded_rect(ctx, px, py, pw, ph, 18 * u)
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(6 * u)
    ctx.stroke()
    cx = px + pw / 2
    ctx.arc(cx, py + 70 * u, 28 * u, 0, 2 * math.pi)
    ctx.move_to(cx - 50 * u, py + 110 * u)
    ctx.line_to(cx + 50 * u, py + 110 * u)
    ctx.line_to(cx + 34 * u, py + 270 * u)
    ctx.line_to(cx - 34 * u, py + 270 * u)
    ctx.close_path()
    ctx.set_source_rgb(*PALETTE["sky_light"])
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(4 * u)
    ctx.stroke()
    ctx.arc(cx + 8 * u, py + 150 * u, 14 * u, 0, 2 * math.pi)
    ctx.set_source_rgb(*PALETTE["coral"])
    ctx.fill()
    # wall monitor frame top-right (trace drawn in the ambient layer)
    mx, my, mw, mh = w * 0.66, h * 0.09, 300 * u, 170 * u
    rounded_rect(ctx, mx, my, mw, mh, 20 * u)
    ctx.set_source_rgb(*PALETTE["navy"])
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(6 * u)
    ctx.stroke()
    rounded_rect(ctx, mx + 16 * u, my + 16 * u, mw - 32 * u, mh - 32 * u, 12 * u)
    ctx.set_source_rgb(*PALETTE["night"])
    ctx.fill()
    # counter
    ctx.rectangle(0, floor_y, w, h - floor_y)
    ctx.set_source_rgb(*lighten(PALETTE["teal_dark"], 0.1))
    ctx.fill()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(6 * u)
    ctx.move_to(0, floor_y)
    ctx.line_to(w, floor_y)
    ctx.stroke()
    ctx.set_source_rgba(1, 1, 1, 0.3)
    ctx.set_line_width(10 * u)
    ctx.move_to(0, floor_y + 22 * u)
    ctx.line_to(w, floor_y + 22 * u)
    ctx.stroke()


def _anatomy_blueprint(ctx, w, h, seed):
    """Medical blueprint: deep blue grid, faint organ outlines and measurement marks."""
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, mix(PALETTE["blue"], PALETTE["navy"], 0.55), mix(PALETTE["navy"], PALETTE["night"], 0.5))
    step = 60 * u
    ctx.set_line_width(1.5 * u)
    ctx.set_source_rgba(1, 1, 1, 0.08)
    x = 0.0
    while x < w:
        ctx.move_to(x, 0)
        ctx.line_to(x, h)
        x += step
    y = 0.0
    while y < h:
        ctx.move_to(0, y)
        ctx.line_to(w, y)
        y += step
    ctx.stroke()
    ctx.set_source_rgba(1, 1, 1, 0.16)
    ctx.set_line_width(3 * u)
    x = 0.0
    while x < w:
        ctx.move_to(x, 0)
        ctx.line_to(x, h)
        x += step * 5
    ctx.stroke()
    rnd = random.Random(seed)
    ctx.set_source_rgba(*PALETTE["sky_light"], 0.14)
    ctx.set_line_width(5 * u)
    for _ in range(5):
        cx, cy, r = rnd.random() * w, rnd.random() * h, (70 + 90 * rnd.random()) * u
        ctx.move_to(cx, cy + r * 0.6)        # heart-ish outline
        ctx.curve_to(cx - r * 1.2, cy - r * 0.1, cx - r * 0.5, cy - r * 1.0, cx, cy - r * 0.35)
        ctx.curve_to(cx + r * 0.5, cy - r * 1.0, cx + r * 1.2, cy - r * 0.1, cx, cy + r * 0.6)
        ctx.stroke()


def _cell_world(ctx, w, h, seed):
    """Microscope view: soft pink-lavender field with translucent cells at two depths."""
    u = min(w, h) / 1080
    _rgrad(ctx, w, h, lighten(PALETTE["pink_light"], 0.35), mix(PALETTE["pink"], PALETTE["lavender"], 0.55), 0.5, 0.45)
    rnd = random.Random(seed)
    for depth, (n, rmin, rmax, a) in enumerate(((10, 70, 130, 0.22), (8, 40, 70, 0.35))):
        for _ in range(n):
            x, y, r = rnd.random() * w, rnd.random() * h, rnd.uniform(rmin, rmax) * u
            ctx.arc(x, y, r, 0, 2 * math.pi)
            ctx.set_source_rgba(1, 1, 1, a)
            ctx.fill_preserve()
            ctx.set_source_rgba(*PALETTE["purple_dark"], a * 0.8)
            ctx.set_line_width(4 * u)
            ctx.stroke()
            ctx.arc(x + r * 0.15, y - r * 0.1, r * 0.35, 0, 2 * math.pi)
            ctx.set_source_rgba(*PALETTE["purple"], a * 1.2)
            ctx.fill()
    # vignette ring like a microscope eyepiece
    g = cairo.RadialGradient(w / 2, h / 2, min(w, h) * 0.45, w / 2, h / 2, max(w, h) * 0.72)
    g.add_color_stop_rgba(0, 0, 0, 0, 0)
    g.add_color_stop_rgba(1, *PALETTE["purple_dark"], 0.45)
    ctx.rectangle(0, 0, w, h)
    ctx.set_source(g)
    ctx.fill()


# Science ---------------------------------------------------------------------
def _sky_day(ctx, w, h, seed):
    """Wide open blue sky: deep zenith to pale horizon, sun glow, distant hills."""
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, mix(PALETTE["blue"], PALETTE["sky"], 0.35), lighten(PALETTE["sky_light"], 0.45))
    g = cairo.RadialGradient(w * 0.82, h * 0.12, 0, w * 0.82, h * 0.12, min(w, h) * 0.55)
    g.add_color_stop_rgba(0, 1, 1, 0.92, 0.85)
    g.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.rectangle(0, 0, w, h)
    ctx.set_source(g)
    ctx.fill()
    ctx.arc(w * 0.82, h * 0.12, 70 * u, 0, 2 * math.pi)
    ctx.set_source_rgb(*PALETTE["yellow_light"])
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(5 * u)
    ctx.stroke()
    _hills(ctx, w, h, h * 0.86, mix(PALETTE["leaf"], PALETTE["sky"], 0.35), 50 * u, seed)
    _hills(ctx, w, h, h * 0.92, PALETTE["leaf"], 40 * u, seed + 5)


def _science_grid(ctx, w, h, seed):
    """Explorer's notebook: graph paper with faint formulas-free sketches (orbits, waves, atoms)."""
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, lighten(PALETTE["sky_light"], 0.55), lighten(PALETTE["sky_light"], 0.25))
    step = 48 * u
    ctx.set_line_width(1.5 * u)
    ctx.set_source_rgba(*PALETTE["blue"], 0.10)
    x = 0.0
    while x < w:
        ctx.move_to(x, 0)
        ctx.line_to(x, h)
        x += step
    y = 0.0
    while y < h:
        ctx.move_to(0, y)
        ctx.line_to(w, y)
        y += step
    ctx.stroke()
    rnd = random.Random(seed)
    ctx.set_line_width(5 * u)
    for i in range(7):
        x, y, r = rnd.random() * w, rnd.random() * h, (40 + 50 * rnd.random()) * u
        col = PALETTE[("blue", "orange", "purple", "teal")[i % 4]]
        ctx.set_source_rgba(*col, 0.18)
        if i % 3 == 0:                       # atom orbits
            for k in range(3):
                ctx.save()
                ctx.translate(x, y)
                ctx.rotate(k * math.pi / 3)
                ctx.scale(1, 0.38)
                ctx.arc(0, 0, r, 0, 2 * math.pi)
                ctx.restore()
                ctx.stroke()
        elif i % 3 == 1:                     # wave
            for k in range(40):
                xx = x - r * 1.5 + k * r * 3 / 39
                (ctx.move_to if k == 0 else ctx.line_to)(xx, y + math.sin(k * 0.6) * r * 0.25)
            ctx.stroke()
        else:                                # orbit with planet
            ctx.arc(x, y, r, 0, 2 * math.pi)
            ctx.stroke()
            ctx.arc(x + r, y, 9 * u, 0, 2 * math.pi)
            ctx.fill()


def _atmosphere_view(ctx, w, h, seed):
    """Earth's limb from high above: space on top, glowing blue atmosphere band, planet below."""
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, PALETTE["night"], PALETTE["midnight"])
    _stars_static(ctx, w, h, 90, seed, 0.45)
    cy = h * 1.9
    R = h * 1.25
    for k, (dr, col, a) in enumerate(((0.16, "sky_light", 0.25), (0.10, "sky", 0.5), (0.05, "blue", 0.85))):
        ctx.arc(w / 2, cy, R + R * dr, 0, 2 * math.pi)
        ctx.set_source_rgba(*PALETTE[col], a)
        ctx.fill()
    ctx.arc(w / 2, cy, R, 0, 2 * math.pi)
    ctx.set_source_rgb(*mix(PALETTE["blue"], PALETTE["navy"], 0.3))
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(7 * u)
    ctx.stroke()
    rnd = random.Random(seed)
    for _ in range(6):
        a = math.pi * (1.3 + 0.4 * rnd.random())
        x, y = w / 2 + math.cos(a) * R * 0.92, cy + math.sin(a) * R * 0.92
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(1.6, 0.6)
        ctx.arc(0, 0, (50 + 50 * rnd.random()) * u, 0, 2 * math.pi)
        ctx.restore()
        ctx.set_source_rgba(*PALETTE["green"], 0.85)
        ctx.fill()


def _sunset_sky(ctx, w, h, seed):
    """Low sun: purple zenith through pink to orange horizon, silhouetted hills."""
    u = min(w, h) / 1080
    g = cairo.LinearGradient(0, 0, 0, h)
    for stop, col in ((0, PALETTE["purple_dark"]), (0.35, PALETTE["pink"]), (0.62, PALETTE["orange"]),
                      (0.8, PALETTE["yellow"])):
        g.add_color_stop_rgb(stop, *col)
    ctx.rectangle(0, 0, w, h)
    ctx.set_source(g)
    ctx.fill()
    ctx.arc(w * 0.3, h * 0.8, 150 * u, math.pi, 2 * math.pi)
    ctx.set_source_rgb(*PALETTE["coral"])
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(6 * u)
    ctx.stroke()
    _hills(ctx, w, h, h * 0.82, PALETTE["purple_dark"], 70 * u, seed)
    _hills(ctx, w, h, h * 0.9, mix(PALETTE["purple_dark"], PALETTE["night"], 0.5), 50 * u, seed + 2)


# Psychology ------------------------------------------------------------------
def _mind_maze(ctx, w, h, seed):
    """Abstract mind: deep violet with concentric thought rings and looping paths."""
    u = min(w, h) / 1080
    _rgrad(ctx, w, h, mix(PALETTE["purple"], PALETTE["pink"], 0.25), mix(PALETTE["purple_dark"], PALETTE["night"], 0.45),
           0.5, 0.42)
    rnd = random.Random(seed)
    cx, cy = w * 0.5, h * 0.42
    ctx.set_line_width(4 * u)
    for k in range(9):
        r = (90 + k * 85) * u
        ctx.set_source_rgba(1, 1, 1, 0.09 if k % 2 else 0.05)
        a0 = rnd.random() * 2 * math.pi
        ctx.arc(cx, cy, r, a0, a0 + math.pi * (1.2 + 0.6 * rnd.random()))
        ctx.stroke()
    ctx.set_line_width(6 * u)
    for i in range(4):
        x, y, r = rnd.random() * w, rnd.random() * h, (40 + 40 * rnd.random()) * u
        ctx.set_source_rgba(*PALETTE[("pink", "lavender", "yellow_light", "teal_light")[i]], 0.16)
        for k in range(50):
            a = k * 0.32
            rr = r * (0.2 + k / 50)
            (ctx.move_to if k == 0 else ctx.line_to)(x + rr * math.cos(a), y + rr * math.sin(a))
        ctx.stroke()


def _thought_room(ctx, w, h, seed):
    """A quiet room late in the evening: desk, lamp glow, window, wall clock — where overthinking happens."""
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, mix(PALETTE["midnight"], PALETTE["purple_dark"], 0.35), mix(PALETTE["purple_dark"], PALETTE["navy"], 0.5))
    # warm lamp glow
    g = cairo.RadialGradient(w * 0.78, h * 0.62, 0, w * 0.78, h * 0.62, min(w, h) * 0.75)
    g.add_color_stop_rgba(0, *PALETTE["yellow_light"], 0.45)
    g.add_color_stop_rgba(1, *PALETTE["yellow_light"], 0.0)
    ctx.rectangle(0, 0, w, h)
    ctx.set_source(g)
    ctx.fill()
    # window with night sky
    wx, wy, ww, wh = w * 0.1, h * 0.1, 300 * u, 360 * u
    rounded_rect(ctx, wx, wy, ww, wh, 16 * u)
    ctx.set_source_rgb(*PALETTE["night"])
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(8 * u)
    ctx.stroke()
    ctx.move_to(wx + ww / 2, wy)
    ctx.line_to(wx + ww / 2, wy + wh)
    ctx.move_to(wx, wy + wh / 2)
    ctx.line_to(wx + ww, wy + wh / 2)
    ctx.set_source_rgb(*PALETTE["hair"])
    ctx.set_line_width(10 * u)
    ctx.stroke()
    ctx.arc(wx + ww * 0.72, wy + wh * 0.25, 30 * u, 0, 2 * math.pi)
    ctx.set_source_rgb(*PALETTE["yellow_light"])
    ctx.fill()
    # wall clock
    cx, cy, r = w * 0.55, h * 0.14, 62 * u
    ctx.arc(cx, cy, r, 0, 2 * math.pi)
    ctx.set_source_rgb(*PALETTE["cream"])
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(7 * u)
    ctx.stroke()
    # desk
    dy = h * 0.8
    ctx.rectangle(0, dy, w, h - dy)
    ctx.set_source_rgb(*mix(PALETTE["hair"], PALETTE["orange_dark"], 0.35))
    ctx.fill()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(7 * u)
    ctx.move_to(0, dy)
    ctx.line_to(w, dy)
    ctx.stroke()
    # lamp
    lx = w * 0.86
    ctx.move_to(lx, dy)
    ctx.line_to(lx - 10 * u, dy - 170 * u)
    ctx.set_line_width(12 * u)
    ctx.stroke()
    ctx.move_to(lx - 90 * u, dy - 160 * u)
    ctx.line_to(lx + 50 * u, dy - 160 * u)
    ctx.line_to(lx + 10 * u, dy - 240 * u)
    ctx.line_to(lx - 50 * u, dy - 240 * u)
    ctx.close_path()
    ctx.set_source_rgb(*PALETTE["yellow"])
    ctx.fill_preserve()
    ctx.set_source_rgb(*PALETTE["ink"])
    ctx.set_line_width(6 * u)
    ctx.stroke()


def _emotion_waves(ctx, w, h, seed):
    """Soft layered colour waves (calm → warm) for feelings, insight and endings."""
    u = min(w, h) / 1080
    _vgrad(ctx, w, h, lighten(PALETTE["lavender"], 0.4), lighten(PALETTE["pink_light"], 0.2))
    cols = ("lavender", "pink_light", "teal_light", "yellow_light", "pink")
    for i, col in enumerate(cols):
        base = h * (0.45 + i * 0.12)
        amp = (50 + 20 * i) * u
        ctx.move_to(0, h)
        ctx.line_to(0, base)
        for k in range(7):
            x0, x1 = w * k / 6, w * (k + 1) / 6
            ctx.curve_to(x0 + (x1 - x0) * 0.33, base - amp * (1 if k % 2 else -1),
                         x0 + (x1 - x0) * 0.66, base - amp * (1 if k % 2 else -1), x1, base)
        ctx.line_to(w, h)
        ctx.close_path()
        ctx.set_source_rgba(*PALETTE[col], 0.55)
        ctx.fill()
    _scribbles(ctx, w, h * 0.5, seed, ("purple", "pink", "teal"), 0.14)


STATIC: Dict[str, Callable] = {
    "paper": _paper, "bedroom_night": _bedroom_night, "night_sky": _night_sky, "dreamscape": _dreamscape,
    "lab": _lab, "chalkboard": _chalkboard, "brain_space": _brain_space, "sunny_outdoors": _sunny,
    "space": _space, "city": _city, "burst_teal": _burst_static("teal"), "burst_orange": _burst_static("orange"),
    "burst_purple": _burst_static("purple"),
    # niche environments
    "bloodstream": _bloodstream, "body_lab": _body_lab, "anatomy_blueprint": _anatomy_blueprint,
    "cell_world": _cell_world, "sky_day": _sky_day, "science_grid": _science_grid,
    "atmosphere_view": _atmosphere_view, "sunset_sky": _sunset_sky, "mind_maze": _mind_maze,
    "thought_room": _thought_room, "emotion_waves": _emotion_waves,
}

DARK_BACKGROUNDS = {"bedroom_night", "night_sky", "dreamscape", "brain_space", "space", "chalkboard", "burst_purple",
                    "bloodstream", "anatomy_blueprint", "atmosphere_view", "mind_maze", "thought_room"}


class Background:
    """A background instance for one scene (static cached layer + ambient animation)."""

    def __init__(self, name: str, width: int, height: int, seed: int = 0):
        if name not in STATIC:
            raise KeyError(f"unknown background {name!r}")
        self.name, self.w, self.h, self.seed = name, width, height, seed
        self.sw, self.sh = int(width * OVERSCAN), int(height * OVERSCAN)
        self.surface = cairo.ImageSurface(cairo.FORMAT_RGB24, self.sw, self.sh)
        ctx = cairo.Context(self.surface)
        STATIC[name](ctx, self.sw, self.sh, seed)
        self.surface.flush()
        self.dark = name in DARK_BACKGROUNDS

    def draw(self, ctx: cairo.Context, t: float) -> None:
        """Draw in frame coordinates (camera transform already applied by the caller)."""
        ox, oy = -(self.sw - self.w) / 2, -(self.sh - self.h) / 2
        ctx.set_source_surface(self.surface, ox, oy)
        ctx.paint()
        self._ambient(ctx, t, ox, oy)

    def _ambient(self, ctx: cairo.Context, t: float, ox: float, oy: float) -> None:
        w, h, u = self.sw, self.sh, min(self.w, self.h) / 1080
        n = self.name
        if n.startswith("burst_"):
            cx, cy = ox + w * 0.5, oy + h * 0.42
            R = max(w, h)
            rays = 18
            rot = t * 0.12
            ctx.set_source_rgba(1, 1, 1, 0.13)
            for i in range(rays):
                a0 = rot + i * 2 * math.pi / rays
                a1 = a0 + math.pi / rays
                ctx.move_to(cx, cy)
                ctx.line_to(cx + R * math.cos(a0), cy + R * math.sin(a0))
                ctx.line_to(cx + R * math.cos(a1), cy + R * math.sin(a1))
                ctx.close_path()
            ctx.fill()
        elif n in ("night_sky", "space", "dreamscape", "brain_space", "bedroom_night"):
            rnd = random.Random(self.seed + 99)
            count = 14 if n == "bedroom_night" else 26
            for i in range(count):
                x, y = ox + rnd.random() * w, oy + rnd.random() * h * (0.35 if n == "bedroom_night" else 0.8)
                if n == "bedroom_night":
                    x, y = ox + w * (0.45 + 0.34 * rnd.random()), oy + h * (0.13 + 0.25 * rnd.random())
                k = 0.5 + 0.5 * math.sin(t * (1.2 + 2 * rnd.random()) + i * 1.7)
                r = (6 + 10 * rnd.random()) * u * (0.4 + 0.6 * k)
                fill_poly(ctx, star_points(x, y, r, 4, 0.3), (1, 1, 1), 0.35 + 0.6 * k, None)
        elif n in ("sunny_outdoors", "city"):
            rnd = random.Random(self.seed + 7)
            for i in range(3):
                speed = (12 + 10 * rnd.random()) * u
                y = oy + h * (0.12 + 0.18 * rnd.random())
                x = ox + ((rnd.random() * w + t * speed) % (w + 400 * u)) - 200 * u
                _cloud(ctx, x, y, (70 + 40 * rnd.random()) * u, (1, 1, 1), 0.95, outline=True)
        elif n in ("sky_day", "sunset_sky"):
            rnd = random.Random(self.seed + 11)
            for i in range(4):
                speed = (10 + 12 * rnd.random()) * u
                y = oy + h * (0.1 + 0.3 * rnd.random())
                x = ox + ((rnd.random() * w + t * speed) % (w + 400 * u)) - 200 * u
                col = (1, 1, 1) if n == "sky_day" else lighten(PALETTE["pink_light"], 0.3)
                _cloud(ctx, x, y, (60 + 50 * rnd.random()) * u, col, 0.9, outline=True)
        elif n == "bloodstream":
            rnd = random.Random(self.seed + 21)
            for i in range(9):
                speed = (90 + 120 * rnd.random()) * u
                y = oy + h * (0.22 + 0.56 * rnd.random()) + math.sin(t * 1.3 + i) * 10 * u
                x = ox + ((rnd.random() * w + t * speed) % (w + 300 * u)) - 150 * u
                _blob_cell(ctx, x, y, (26 + 22 * rnd.random()) * u, PALETTE["red"], u, 0.55)
        elif n == "cell_world":
            rnd = random.Random(self.seed + 31)
            for i in range(6):
                x = ox + w * rnd.random() + math.sin(t * 0.4 + i) * 30 * u
                y = oy + h * rnd.random() + math.cos(t * 0.5 + i * 2) * 24 * u
                r = (18 + 18 * rnd.random()) * u
                ctx.arc(x, y, r, 0, 2 * math.pi)
                ctx.set_source_rgba(1, 1, 1, 0.35)
                ctx.fill()
        elif n == "body_lab":
            # live ECG trace on the wall monitor
            mx, my, mw, mh = ox + w * 0.66 + 16 * u, oy + h * 0.09 + 16 * u, 268 * u, 138 * u
            ctx.save()
            ctx.rectangle(mx, my, mw, mh)
            ctx.clip()
            ctx.set_source_rgb(*PALETTE["green"])
            ctx.set_line_width(4 * u)
            base = my + mh * 0.55
            for k in range(70):
                xx = mx + k * mw / 69
                ph = (k / 69 * 2.2 + t * 1.1) % 1.0
                yy = base - (mh * 0.42 if 0.46 < ph < 0.5 else -mh * 0.25 if 0.5 <= ph < 0.53 else 0)
                (ctx.move_to if k == 0 else ctx.line_to)(xx, yy)
            ctx.stroke()
            ctx.restore()
        elif n == "anatomy_blueprint":
            y = oy + ((t * 120 * u) % h)
            ctx.rectangle(ox, y, w, 3 * u)
            ctx.set_source_rgba(*PALETTE["sky_light"], 0.25)
            ctx.fill()
        elif n == "mind_maze":
            cx, cy = ox + w * 0.5, oy + h * 0.42
            ctx.set_line_width(5 * u)
            for k in range(3):
                r = (180 + k * 170) * u
                a0 = t * (0.15 + 0.07 * k) * (1 if k % 2 else -1)
                ctx.set_source_rgba(*PALETTE[("pink", "lavender", "yellow_light")[k]], 0.22)
                ctx.arc(cx, cy, r, a0, a0 + 1.4)
                ctx.stroke()
        elif n == "thought_room":
            cx, cy, r = ox + w * 0.55, oy + h * 0.14, 50 * u
            ctx.set_source_rgb(*PALETTE["ink"])
            ctx.set_line_width(6 * u)
            for ang, ln in ((t * 0.5, 0.75), (t * 0.04, 0.5)):
                ctx.move_to(cx, cy)
                ctx.line_to(cx + math.sin(ang) * r * ln, cy - math.cos(ang) * r * ln)
            ctx.stroke()
        elif n == "emotion_waves":
            ctx.set_line_width(5 * u)
            for i in range(2):
                base = oy + h * (0.4 + 0.18 * i)
                ctx.set_source_rgba(1, 1, 1, 0.35)
                for k in range(60):
                    x = ox + w * k / 59
                    y = base + math.sin(k * 0.25 + t * (0.8 + 0.3 * i)) * 26 * u
                    (ctx.move_to if k == 0 else ctx.line_to)(x, y)
                ctx.stroke()
        elif n == "paper":
            pass
