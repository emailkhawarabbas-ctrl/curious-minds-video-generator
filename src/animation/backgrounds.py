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


STATIC: Dict[str, Callable] = {
    "paper": _paper, "bedroom_night": _bedroom_night, "night_sky": _night_sky, "dreamscape": _dreamscape,
    "lab": _lab, "chalkboard": _chalkboard, "brain_space": _brain_space, "sunny_outdoors": _sunny,
    "space": _space, "city": _city, "burst_teal": _burst_static("teal"), "burst_orange": _burst_static("orange"),
    "burst_purple": _burst_static("purple"),
}

DARK_BACKGROUNDS = {"bedroom_night", "night_sky", "dreamscape", "brain_space", "space", "chalkboard", "burst_purple"}


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
        elif n == "paper":
            pass
