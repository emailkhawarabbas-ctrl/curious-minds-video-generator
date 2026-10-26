"""Colorful doodle animation engine.

Reusable, time-based vector elements with a hand-drawn feel:
  * draw-on strokes with "line boil" (lines jitter slightly ~8x per second like hand animation)
  * arrows, circle highlights, underlines / marker highlights, stars, sparkles, bursts
  * speech & thought bubbles, labels with leader lines, big pop text, counters
  * icon pops with bounce / elastic / float / spin / pulse, morphing shapes
  * particle systems (burst, confetti, float-up, twinkle field, zzz) and animated
    pathways with travelling pulses (neural signals, flows)
  * animated charts: bar chart, line / hypnogram chart, brain-wave line

Every element exposes ``draw(ctx, t)`` with scene-relative time ``t`` and is fully
deterministic (seeded), so parallel scene rendering produces identical frames.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import cairo

from src.animation.boil import boil_variant, boiled
from src.animation.easing import (clamp, ease_in_back, ease_in_out_sine, ease_out_back, ease_out_cubic,
                                  ease_out_elastic, ease_pop, get_ease, progress, squash)
from src.animation.palette import PALETTE, lighten
from src.animation.svg_loader import SvgAsset
from src.animation.text_render import TextStyle, draw_lines, fit_size, wrap_text
from src.utils.fonts import CAPTION_FONT, HAND_FONT, TITLE_FONT

Point = Tuple[float, float]
RGB = Tuple[float, float, float]
INK = PALETTE["ink"]


# --------------------------------------------------------------------------- helpers
def boil(t: float, fps: float = 8.0) -> int:
    """Discrete 'line boil' frame index (hand-drawn jitter changes ~8x per second)."""
    return int(t * fps)


def jitter_points(pts: Sequence[Point], amount: float, seed: int) -> List[Point]:
    rnd = random.Random(seed)
    return [(x + rnd.uniform(-amount, amount), y + rnd.uniform(-amount, amount)) for x, y in pts]


def polyline_len(pts: Sequence[Point]) -> float:
    return sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1))


def partial_polyline(pts: Sequence[Point], frac: float) -> List[Point]:
    if frac >= 1:
        return list(pts)
    total = polyline_len(pts) * max(0.0, frac)
    out = [pts[0]]
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if total >= seg:
            out.append(b)
            total -= seg
        else:
            f = total / seg if seg else 0
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            break
    return out


def smooth_path(ctx: cairo.Context, pts: Sequence[Point]) -> None:
    """Catmull-Rom spline through points."""
    if len(pts) < 2:
        return
    ctx.move_to(*pts[0])
    if len(pts) == 2:
        ctx.line_to(*pts[1])
        return
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        ctx.curve_to(*c1, *c2, *p2)


def stroke_doodle(ctx: cairo.Context, pts: Sequence[Point], color: RGB, width: float, alpha: float = 1.0,
                  outline: Optional[RGB] = None, smooth: bool = True) -> None:
    if len(pts) < 2 or alpha <= 0:
        return
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    (smooth_path if smooth else _poly)(ctx, pts)
    if outline is not None:
        ctx.set_source_rgba(*outline, alpha)
        ctx.set_line_width(width * 1.9)
        ctx.stroke_preserve()
    ctx.set_source_rgba(*color, alpha)
    ctx.set_line_width(width)
    ctx.stroke()


def _poly(ctx: cairo.Context, pts: Sequence[Point]) -> None:
    ctx.move_to(*pts[0])
    for p in pts[1:]:
        ctx.line_to(*p)


def bezier_points(p0: Point, p1: Point, bend: float, n: int = 28) -> List[Point]:
    """Quadratic curve from p0 to p1 bulging sideways by `bend` (fraction of length)."""
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy) or 1
    cx, cy = mx - dy / L * bend * L, my + dx / L * bend * L
    out = []
    for i in range(n + 1):
        t = i / n
        out.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * cx + t * t * p1[0],
                    (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * cy + t * t * p1[1]))
    return out


def star_points(cx: float, cy: float, r: float, points: int = 5, inner: float = 0.45,
                rot: float = -90) -> List[Point]:
    pts = []
    for i in range(points * 2):
        rr = r if i % 2 == 0 else r * inner
        a = math.radians(rot + i * 180 / points)
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def fill_poly(ctx: cairo.Context, pts: Sequence[Point], color: RGB, alpha: float = 1.0,
              outline: Optional[RGB] = INK, width: float = 4.0) -> None:
    _poly(ctx, pts)
    ctx.close_path()
    ctx.set_source_rgba(*color, alpha)
    if outline is not None:
        ctx.fill_preserve()
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.set_source_rgba(*outline, alpha)
        ctx.set_line_width(width)
        ctx.stroke()
    else:
        ctx.fill()


def rounded_rect(ctx: cairo.Context, x: float, y: float, w: float, h: float, r: float) -> None:
    r = min(r, w / 2, h / 2)
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


def pop_scale(t: float, start: float, dur: float = 0.45, style: str = "back") -> float:
    p = progress(t, start, dur)
    if style == "elastic":
        return ease_out_elastic(p)
    if style == "bounce":
        return get_ease("out_bounce")(p)
    if style == "linear":
        return p
    return ease_out_back(p, 2.0)


# --------------------------------------------------------------------------- base
@dataclass
class Doodle:
    start: float = 0.0
    duration: float = 0.6          # build-in duration
    end: Optional[float] = None    # time at which the element exits (None = stays)
    exit_dur: float = 0.3
    unit: float = 1.0              # px per design unit (1.0 at 1080 short side)
    seed: int = 0
    z: int = 0                     # draw order

    def visible(self, t: float) -> bool:
        if t < self.start:
            return False
        return self.end is None or t < self.end + self.exit_dur

    def exit_factor(self, t: float) -> float:
        if self.end is None or t < self.end:
            return 1.0
        return 1.0 - ease_in_back(clamp((t - self.end) / self.exit_dur))

    def build(self, t: float) -> float:
        return progress(t, self.start, self.duration)

    def draw(self, ctx: cairo.Context, t: float) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


# --------------------------------------------------------------------------- strokes
@dataclass
class DrawPath(Doodle):
    points: List[Point] = field(default_factory=list)
    color: RGB = INK
    width: float = 6.0
    outline: Optional[RGB] = None
    wobble: float = 1.6
    smooth: bool = True

    def draw(self, ctx, t):
        if not self.visible(t) or len(self.points) < 2:
            return
        p = ease_out_cubic(self.build(t))
        pts = jitter_points(self.points, self.wobble * self.unit, self.seed * 31 + boil(t))
        stroke_doodle(ctx, partial_polyline(pts, p), self.color, self.width * self.unit,
                      self.exit_factor(t), self.outline, self.smooth)


@dataclass
class Arrow(Doodle):
    p0: Point = (0, 0)
    p1: Point = (100, 0)
    bend: float = 0.18
    color: RGB = PALETTE["orange"]
    width: float = 9.0
    head: float = 34.0
    dashed: bool = False

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        a = self.exit_factor(t)
        p = ease_out_cubic(self.build(t))
        pts = bezier_points(self.p0, self.p1, self.bend)
        pts = jitter_points(pts, 1.2 * self.unit, self.seed * 17 + boil(t))
        part = partial_polyline(pts, p)
        u = self.unit
        if self.dashed:
            ctx.set_dash([18 * u, 14 * u])
        stroke_doodle(ctx, part, self.color, self.width * u, a, outline=INK)
        ctx.set_dash([])
        if p > 0.85 and len(part) >= 2:
            hp = pop_scale(t, self.start + self.duration * 0.85, 0.3)
            (x0, y0), (x1, y1) = part[-2], part[-1]
            ang = math.atan2(y1 - y0, x1 - x0)
            h = self.head * u * hp
            tip = (x1 + math.cos(ang) * h * 0.25, y1 + math.sin(ang) * h * 0.25)
            left = (tip[0] - h * math.cos(ang - 0.5), tip[1] - h * math.sin(ang - 0.5))
            right = (tip[0] - h * math.cos(ang + 0.5), tip[1] - h * math.sin(ang + 0.5))
            fill_poly(ctx, [left, tip, right], self.color, a, INK, 4.5 * u)


@dataclass
class CircleHighlight(Doodle):
    center: Point = (0, 0)
    rx: float = 100
    ry: float = 70
    color: RGB = PALETTE["coral"]
    width: float = 8.0
    loops: float = 1.15

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        p = ease_out_cubic(self.build(t))
        n = 60
        rnd = random.Random(self.seed)
        ph = rnd.uniform(0, 2 * math.pi)
        pts = []
        for i in range(int(n * self.loops) + 1):
            a = ph + i / n * 2 * math.pi
            k = 1 + 0.06 * (i / n)
            pts.append((self.center[0] + self.rx * k * math.cos(a), self.center[1] + self.ry * k * math.sin(a)))
        pts = jitter_points(pts, 1.5 * self.unit, self.seed + boil(t))
        stroke_doodle(ctx, partial_polyline(pts, p), self.color, self.width * self.unit, self.exit_factor(t))


@dataclass
class MarkerHighlight(Doodle):
    """Translucent marker swipe (drawn behind text) or a scribbly underline."""
    x0: float = 0
    x1: float = 100
    y: float = 0
    color: RGB = PALETTE["yellow"]
    thickness: float = 30
    alpha: float = 0.55
    underline: bool = False

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        p = ease_out_cubic(self.build(t))
        a = self.exit_factor(t)
        if self.underline:
            pts = [(self.x0 + (self.x1 - self.x0) * i / 12, self.y + 3 * math.sin(i * 1.3)) for i in range(13)]
            stroke_doodle(ctx, partial_polyline(jitter_points(pts, 1.2, self.seed + boil(t)), p),
                          self.color, 8 * self.unit, a)
            return
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.move_to(self.x0, self.y)
        ctx.line_to(self.x0 + (self.x1 - self.x0) * p, self.y + 2)
        ctx.set_source_rgba(*self.color, self.alpha * a)
        ctx.set_line_width(self.thickness)
        ctx.stroke()


# --------------------------------------------------------------------------- shapes
@dataclass
class StarDoodle(Doodle):
    center: Point = (0, 0)
    radius: float = 30
    color: RGB = PALETTE["yellow"]
    spin: float = 25.0           # degrees per second
    twinkle: bool = True

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        s = pop_scale(t, self.start, self.duration) * self.exit_factor(t)
        if s <= 0.01:
            return
        tw = 1 + (0.12 * math.sin(t * 5 + self.seed) if self.twinkle else 0)
        pts = star_points(self.center[0], self.center[1], self.radius * self.unit * s * tw,
                          rot=-90 + (t - self.start) * self.spin)
        fill_poly(ctx, pts, self.color, 1.0, INK, 4 * self.unit)


@dataclass
class Sparkle(Doodle):
    center: Point = (0, 0)
    radius: float = 22
    color: RGB = (1, 1, 1)
    period: float = 1.4

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        k = 0.5 + 0.5 * math.sin((t - self.start) * 2 * math.pi / self.period + self.seed)
        s = pop_scale(t, self.start, self.duration) * self.exit_factor(t) * (0.55 + 0.45 * k)
        if s <= 0.02:
            return
        pts = star_points(self.center[0], self.center[1], self.radius * self.unit * s, 4, 0.28, -90)
        fill_poly(ctx, pts, self.color, 1.0, None)


@dataclass
class Burst(Doodle):
    """Radial 'pow' lines around a point."""
    center: Point = (0, 0)
    r0: float = 60
    r1: float = 110
    rays: int = 10
    color: RGB = PALETTE["yellow"]
    width: float = 7

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        p = ease_out_cubic(progress(t, self.start, self.duration))
        fade = 1 - progress(t, self.start + self.duration, 0.6)
        if fade <= 0:
            return
        for i in range(self.rays):
            a = 2 * math.pi * i / self.rays + self.seed
            ra, rb = self.r0 * self.unit, (self.r0 + (self.r1 - self.r0) * p) * self.unit
            stroke_doodle(ctx, [(self.center[0] + ra * math.cos(a), self.center[1] + ra * math.sin(a)),
                                (self.center[0] + rb * math.cos(a), self.center[1] + rb * math.sin(a))],
                          self.color, self.width * self.unit, fade * self.exit_factor(t), INK, smooth=False)


@dataclass
class MorphShape(Doodle):
    """Morph through a sequence of shapes (circle, star, heart, square, cloud, drop)."""
    center: Point = (0, 0)
    size: float = 120
    shapes: Tuple[str, ...] = ("circle", "star", "heart")
    colors: Tuple[str, ...] = ("teal", "yellow", "coral")
    hold: float = 0.9
    morph: float = 0.6

    N = 120

    def _shape(self, name: str) -> List[Point]:
        out = []
        for i in range(self.N):
            a = 2 * math.pi * i / self.N - math.pi / 2
            if name == "circle":
                r = 1.0
            elif name == "star":
                k = (a + math.pi / 2) / (2 * math.pi / 5) % 1
                r = 0.45 + 0.55 * abs(1 - 2 * k) ** 1.6
            elif name == "square":
                r = 1 / max(abs(math.cos(a)), abs(math.sin(a))) * 0.8
            elif name == "drop":
                r = 0.7 + 0.35 * (-math.sin(a)) ** 3 if math.sin(a) < 0 else 0.7
            elif name == "cloud":
                r = 0.82 + 0.12 * abs(math.sin(3 * a))
            elif name == "heart":
                tt = 2 * math.pi * i / self.N
                x = 16 * math.sin(tt) ** 3
                y = -(13 * math.cos(tt) - 5 * math.cos(2 * tt) - 2 * math.cos(3 * tt) - math.cos(4 * tt))
                out.append((x / 17, y / 17))
                continue
            else:
                r = 1.0
            out.append((r * math.cos(a), r * math.sin(a)))
        return out

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        lt = t - self.start
        cycle = self.hold + self.morph
        k = int(lt / cycle)
        f = clamp((lt - k * cycle - self.hold) / self.morph)
        n = len(self.shapes)
        a_i, b_i = k % n, (k + 1) % n
        A, B = self._shape(self.shapes[a_i]), self._shape(self.shapes[b_i])
        e = ease_in_out_sine(f)
        s = self.size * self.unit * pop_scale(t, self.start, self.duration) * self.exit_factor(t)
        pts = [(self.center[0] + (pa[0] + (pb[0] - pa[0]) * e) * s,
                self.center[1] + (pa[1] + (pb[1] - pa[1]) * e) * s) for pa, pb in zip(A, B)]
        ca = PALETTE[self.colors[a_i % len(self.colors)]]
        cb = PALETTE[self.colors[b_i % len(self.colors)]]
        col = tuple(ca[j] + (cb[j] - ca[j]) * e for j in range(3))
        fill_poly(ctx, pts, col, 1.0, INK, 6 * self.unit)


# --------------------------------------------------------------------------- text & bubbles
@dataclass
class Label(Doodle):
    """Rounded tag with text, optional leader line to an anchor point."""
    text: str = ""
    pos: Point = (0, 0)              # centre of the tag
    anchor: Optional[Point] = None   # leader line target
    bg: RGB = (1, 1, 1)
    fg: RGB = INK
    size: float = 40
    font: str = CAPTION_FONT
    max_width: float = 420

    def draw(self, ctx, t):
        if not self.visible(t) or not self.text:
            return
        u = self.unit
        s = pop_scale(t, self.start, self.duration) * self.exit_factor(t)
        if s <= 0.01:
            return
        st = TextStyle(font=self.font, size=self.size * u, color=self.fg, outline=None)
        size, lines = fit_size(ctx, self.text, st, self.max_width * u, 2, 18 * u)
        st.size = size
        ctx.select_font_face(self.font)
        ctx.set_font_size(size)
        w = max(ctx.text_extents(ln).x_advance for ln in lines) + 40 * u
        h = size * (1 + (len(lines) - 1) * st.line_spacing) + 26 * u
        if self.anchor is not None:
            lp = ease_out_cubic(progress(t, self.start, self.duration * 1.3))
            pts = partial_polyline([self.pos, self.anchor], lp)
            stroke_doodle(ctx, pts, INK, 4.5 * u, self.exit_factor(t), smooth=False)
            if lp >= 1:
                ctx.arc(self.anchor[0], self.anchor[1], 8 * u, 0, 2 * math.pi)
                ctx.set_source_rgba(*INK, self.exit_factor(t))
                ctx.fill()
        ctx.save()
        ctx.translate(*self.pos)
        ctx.scale(s, s)
        ctx.rotate(math.radians(-2 + 4 * ((self.seed % 3) / 2)))
        rounded_rect(ctx, -w / 2 + 4 * u, -h / 2 + 6 * u, w, h, 18 * u)
        ctx.set_source_rgba(*INK, 0.9)
        ctx.fill()
        rounded_rect(ctx, -w / 2, -h / 2, w, h, 18 * u)
        ctx.set_source_rgb(*self.bg)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(4.5 * u)
        ctx.stroke()
        draw_lines(ctx, lines, 0, -h / 2 + 13 * u, st, "center")
        ctx.restore()


@dataclass
class SpeechBubble(Doodle):
    text: str = ""
    pos: Point = (0, 0)              # bubble centre
    tail_to: Optional[Point] = None
    width: float = 520
    size: float = 44
    bg: RGB = (1, 1, 1)
    fg: RGB = INK
    thought: bool = False
    typewriter: bool = True
    min_height: float = 110

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        u = self.unit
        s = pop_scale(t, self.start, self.duration) * self.exit_factor(t)
        if s <= 0.01:
            return
        st = TextStyle(font=CAPTION_FONT, size=self.size * u, color=self.fg, outline=None)
        size, lines = fit_size(ctx, self.text, st, (self.width - 70) * u, 4, 20 * u) if self.text else (st.size, [])
        st.size = size
        w = self.width * u
        h = max(self.min_height * u, size * (1 + (len(lines) - 1) * st.line_spacing) + 70 * u)
        cx, cy = self.pos
        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(s, s)
        if self.thought:
            self._cloud(ctx, w, h, t)
        else:
            rounded_rect(ctx, -w / 2, -h / 2, w, h, 44 * u)
            if self.tail_to is not None:
                tx, ty = (self.tail_to[0] - cx) / max(s, 0.01), (self.tail_to[1] - cy) / max(s, 0.01)
                base = 0.0 if abs(tx) < w / 2 - 60 * u else (-1 if tx < 0 else 1) * (w / 2 - 90 * u)
                by = h / 2 if ty > 0 else -h / 2
                ctx.move_to(base - 34 * u, by - (8 * u if ty > 0 else -8 * u))
                ctx.line_to(tx * 0.55, by + (ty - by) * 0.55)
                ctx.line_to(base + 34 * u, by - (8 * u if ty > 0 else -8 * u))
                ctx.close_path()
            ctx.set_source_rgb(*self.bg)
            ctx.fill_preserve()
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(6 * u)
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.stroke()
            # repaint bubble body over the tail seam
            rounded_rect(ctx, -w / 2 + 3 * u, -h / 2 + 3 * u, w - 6 * u, h - 6 * u, 42 * u)
            ctx.set_source_rgb(*self.bg)
            ctx.fill()
        if lines:
            shown = lines
            if self.typewriter:
                total = sum(len(x) for x in lines)
                n = int(total * clamp((t - self.start - 0.15) / max(0.4, 0.035 * total)))
                shown, acc = [], 0
                for ln in lines:
                    take = max(0, min(len(ln), n - acc))
                    shown.append(ln[:take])
                    acc += len(ln)
            th = size * (1 + (len(lines) - 1) * st.line_spacing)
            draw_lines(ctx, shown, 0, -th / 2 - size * 0.05, st, "center")
        ctx.restore()

    def _cloud(self, ctx, w, h, t):
        u = self.unit
        bumps = 9
        ctx.new_path()
        for i in range(bumps):
            a = 2 * math.pi * i / bumps
            bx, by = (w / 2 - 34 * u) * math.cos(a), (h / 2 - 26 * u) * math.sin(a)
            ctx.new_sub_path()
            ctx.arc(bx, by, 50 * u + 6 * u * math.sin(t * 2 + i), 0, 2 * math.pi)
        ctx.new_sub_path()
        ctx.save()
        ctx.scale(w / 2, h / 2)
        ctx.arc(0, 0, 1, 0, 2 * math.pi)
        ctx.restore()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(12 * u)
        ctx.stroke_preserve()
        ctx.set_source_rgb(*self.bg)
        ctx.fill()
        if self.tail_to is not None:
            cx, cy = self.pos
            tx, ty = self.tail_to[0] - cx, self.tail_to[1] - cy
            for i, r in enumerate((22, 15, 9)):
                f = 0.55 + 0.17 * i
                ctx.new_sub_path()
                ctx.arc(tx * f, ty * f, r * u, 0, 2 * math.pi)
                ctx.set_source_rgb(*self.bg)
                ctx.fill_preserve()
                ctx.set_source_rgb(*INK)
                ctx.set_line_width(5 * u)
                ctx.stroke()


@dataclass
class PopText(Doodle):
    """Big title text: words pop in one by one with an elastic overshoot."""
    text: str = ""
    center: Point = (0, 0)
    size: float = 110
    max_width: float = 900
    max_lines: int = 3
    font: str = TITLE_FONT
    colors: Tuple[str, ...] = ("white",)
    outline: RGB = INK
    per_word: float = 0.12
    tilt: float = -3.0
    wiggle: bool = True

    def draw(self, ctx, t):
        if not self.visible(t) or not self.text:
            return
        u = self.unit
        st = TextStyle(font=self.font, size=self.size * u, outline=self.outline, shadow=True)
        size, lines = fit_size(ctx, self.text, st, self.max_width * u, self.max_lines, 30 * u)
        st.size = size
        st.outline_width = size * 0.2
        ctx.select_font_face(self.font)
        ctx.set_font_size(size)
        lh = size * st.line_spacing
        top = self.center[1] - (lh * (len(lines) - 1) + size) / 2
        wi = 0
        ex = self.exit_factor(t)
        ctx.save()
        ctx.translate(*self.center)
        ctx.rotate(math.radians(self.tilt + (1.2 * math.sin(t * 2.2) if self.wiggle else 0)))
        ctx.translate(-self.center[0], -self.center[1])
        for li, line in enumerate(lines):
            words = line.split()
            space = ctx.text_extents(" ").x_advance
            widths = [ctx.text_extents(w_).x_advance for w_ in words]
            total = sum(widths) + space * (len(words) - 1)
            x = self.center[0] - total / 2
            for w_, ww in zip(words, widths):
                s = pop_scale(t, self.start + wi * self.per_word, 0.4) * ex
                col = PALETTE.get(self.colors[wi % len(self.colors)], (1, 1, 1))
                if s > 0.01:
                    ctx.save()
                    ctx.translate(x + ww / 2, top + li * lh + size * 0.5)
                    ctx.scale(s, s)
                    st.color = col
                    draw_lines(ctx, [w_], 0, -size * 0.5, st, "center")
                    ctx.restore()
                x += ww + space
                wi += 1
        ctx.restore()


@dataclass
class Counter(Doodle):
    """Animated number counting up (e.g. '90 MINUTES'), with a suffix."""
    value: float = 100
    suffix: str = ""
    prefix: str = ""
    decimals: int = 0
    center: Point = (0, 0)
    size: float = 150
    color: str = "yellow"

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        p = ease_out_cubic(progress(t, self.start, max(0.6, self.duration)))
        is_year = self.decimals == 0 and 1000 <= self.value <= 2100 and not self.suffix and not self.prefix
        v = self.value if is_year else self.value * p     # years pop in; quantities count up
        sep = "," if abs(self.value) >= 10000 else ""      # years like 1953 must not read "1,953"
        txt = f"{self.prefix}{v:{sep}.{self.decimals}f}{self.suffix}"
        s = pop_scale(t, self.start, 0.4) * self.exit_factor(t)
        st = TextStyle(font=TITLE_FONT, size=self.size * self.unit, color=PALETTE[self.color],
                       outline=INK, outline_width=self.size * self.unit * 0.18, shadow=True)
        ctx.save()
        ctx.translate(*self.center)
        ctx.scale(s, s)
        draw_lines(ctx, [txt], 0, -st.size * 0.55, st, "center")
        ctx.restore()


# --------------------------------------------------------------------------- icons
@dataclass
class IconPop(Doodle):
    asset: Optional[SvgAsset] = None
    center: Point = (0, 0)
    height: float = 300
    entrance: str = "pop"          # pop | pop_in | elastic | bounce | draw | fade | slide_up | slide_in | spin | none
    idle: str = "float"            # float | pulse | wiggle | spin | none
    rotation: float = 0.0
    flip: bool = False
    tint: Optional[Tuple[RGB, float]] = None
    move_to: Optional[Point] = None
    move_start: float = 0.0
    move_dur: float = 0.8
    scale_to: Optional[float] = None
    highlight_groups: Optional[Tuple[str, ...]] = None
    highlight_start: float = 0.0
    boil: float = 0.0              # line boil amount (viewBox units, 0 = off), see animation/boil.py
    boil_fps: float = 8.0
    accents: Tuple[float, ...] = ()   # times of a squash-and-stretch bounce (emphasis beats)
    fill_start: float = 0.45       # draw entrance: when fills start fading in
    overshoot: float = 1.1         # pop_in peak scale
    float_amount: float = 0.025    # idle float amplitude (fraction of the height)
    slide_from: float = -1.0       # slide_in: -1 from the left, 1 from the right

    def current_center(self, t: float) -> Point:
        cx, cy = self.center
        if self.move_to is not None and t > self.move_start:
            f = ease_in_out_sine(clamp((t - self.move_start) / self.move_dur))
            cx, cy = cx + (self.move_to[0] - cx) * f, cy + (self.move_to[1] - cy) * f
        return cx, cy

    def current_height(self, t: float) -> float:
        h = self.height
        if self.scale_to is not None and t > self.move_start:
            f = ease_in_out_sine(clamp((t - self.move_start) / self.move_dur))
            h = h + (self.scale_to - h) * f
        return h

    def draw(self, ctx, t):
        if not self.visible(t) or self.asset is None:
            return
        lt = t - self.start
        cx, cy = self.current_center(t)
        h = self.current_height(t)
        alpha, scale, rot, dp = 1.0, 1.0, self.rotation, 1.0
        e = self.entrance
        if e in ("pop", "elastic", "bounce"):
            scale = pop_scale(t, self.start, self.duration, "back" if e == "pop" else e)
        elif e == "pop_in":
            scale = ease_pop(clamp(lt / self.duration), self.overshoot)
        elif e == "slide_in":
            f = ease_out_back(clamp(lt / self.duration), 1.6)
            cx += (1 - f) * self.slide_from * h * 1.6
            alpha = clamp(lt / (self.duration * 0.35))
        elif e == "draw":
            dp = clamp(lt / max(0.3, self.duration))
        elif e == "fade":
            alpha = ease_out_cubic(clamp(lt / self.duration))
        elif e == "slide_up":
            f = ease_out_back(clamp(lt / self.duration), 1.4)
            cy += (1 - f) * h * 0.8
            alpha = clamp(lt / (self.duration * 0.5))
        elif e == "spin":
            f = ease_out_back(clamp(lt / self.duration))
            scale, rot = f, rot + (1 - f) * -180
        idle = self.idle
        if idle == "float":
            cy += math.sin(lt * 2.0 + self.seed) * h * self.float_amount
            rot += math.sin(lt * 1.3 + self.seed) * 2.0
        elif idle == "pulse":
            scale *= 1 + 0.045 * math.sin(lt * 5.0)
        elif idle == "wiggle":
            rot += math.sin(lt * 7.0) * 5
        elif idle == "spin":
            rot += lt * 40
        ex = self.exit_factor(t)
        scale *= ex
        if scale <= 0.01 or alpha <= 0.01:
            return
        asset = self.asset
        if self.boil > 0:
            asset = boiled(asset, boil_variant(t, self.boil_fps, self.seed), self.boil)
        sx = sy = 1.0
        for at in self.accents:
            if 0 <= t - at <= 0.7:
                sx, sy = squash(t - at)
                break
        if (sx, sy) != (1.0, 1.0):
            base = cy + h * scale * 0.5                  # squash from the bottom edge
            ctx.save()
            ctx.translate(cx, base)
            ctx.scale(sx, sy)
            ctx.translate(-cx, -base)
        asset.draw(ctx, cx, cy, h * scale, rotation=rot, alpha=alpha, flip=self.flip,
                   draw_progress=dp, tint=self.tint, fill_start=self.fill_start)
        if self.highlight_groups and t >= self.highlight_start:
            k = 0.5 + 0.5 * math.sin((t - self.highlight_start) * 6)
            asset.draw(ctx, cx, cy, h * scale, rotation=rot, alpha=0.55 * k, flip=self.flip,
                       only_groups=self.highlight_groups, tint=(PALETTE["yellow"], 0.85))
        if (sx, sy) != (1.0, 1.0):
            ctx.restore()

    def anchor_at(self, name: str, t: float) -> Point:
        cx, cy = self.current_center(t)
        if self.asset is None:
            return cx, cy
        try:
            return self.asset.anchor(name, cx, cy, self.current_height(t), self.rotation, self.flip)
        except KeyError:
            return cx, cy


# --------------------------------------------------------------------------- particles
@dataclass
class Particles(Doodle):
    """kind: burst | confetti | float_up | twinkle | zzz | bubbles | snow"""
    kind: str = "burst"
    center: Point = (0, 0)
    area: Tuple[float, float, float, float] = (0, 0, 1080, 1920)   # x, y, w, h for field kinds
    count: int = 24
    colors: Tuple[str, ...] = ("yellow", "coral", "teal", "purple", "orange")
    size: float = 14

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        lt = t - self.start
        rnd = random.Random(self.seed * 7919 + 13)
        u = self.unit
        ex = self.exit_factor(t)
        for i in range(self.count):
            col = PALETTE[self.colors[i % len(self.colors)]]
            r0 = rnd.random()
            r1 = rnd.random()
            r2 = rnd.random()
            if self.kind in ("burst", "confetti"):
                life = 1.1 + r2 * 0.6
                if lt > life:
                    continue
                f = lt / life
                ang = r0 * 2 * math.pi
                spd = (220 + 420 * r1) * u
                x = self.center[0] + math.cos(ang) * spd * ease_out_cubic(f)
                y = self.center[1] + math.sin(ang) * spd * ease_out_cubic(f) + (380 * u * f * f if self.kind == "confetti" else 0)
                a = (1 - f) * ex
                sz = self.size * u * (0.6 + r2)
                ctx.save()
                ctx.translate(x, y)
                ctx.rotate(lt * 8 * (r1 - 0.5))
                if self.kind == "confetti":
                    ctx.rectangle(-sz, -sz * 0.45, sz * 2, sz * 0.9)
                    ctx.set_source_rgba(*col, a)
                    ctx.fill()
                else:
                    fill_poly(ctx, star_points(0, 0, sz, 4 if i % 2 else 5, 0.45), col, a, None)
                ctx.restore()
            elif self.kind in ("float_up", "bubbles", "zzz", "snow"):
                ax, ay, aw, ah = self.area
                speed = (60 + 90 * r1) * u * (-1 if self.kind != "snow" else 1)
                period = ah / abs(speed)
                y = ay + ((r0 * ah + speed * lt) % ah)
                x = ax + r2 * aw + math.sin(lt * 1.5 + i) * 18 * u
                edge = min((y - ay) / (ah * 0.2), (ay + ah - y) / (ah * 0.2), 1.0)
                a = clamp(edge) * ex * clamp(lt / 0.6)
                sz = self.size * u * (0.6 + r1 * 0.9)
                if self.kind == "bubbles":
                    ctx.arc(x, y, sz, 0, 2 * math.pi)
                    ctx.set_source_rgba(*lighten(col, 0.5), 0.5 * a)
                    ctx.fill_preserve()
                    ctx.set_source_rgba(*INK, 0.6 * a)
                    ctx.set_line_width(2.5 * u)
                    ctx.stroke()
                elif self.kind == "zzz":
                    self._z(ctx, x, y, sz * 2.2, a, col)
                elif self.kind == "snow":
                    ctx.arc(x, y, sz * 0.5, 0, 2 * math.pi)
                    ctx.set_source_rgba(1, 1, 1, 0.85 * a)
                    ctx.fill()
                else:
                    fill_poly(ctx, star_points(x, y, sz, 4, 0.35, lt * 30), col, a, None)
                _ = period
            elif self.kind == "twinkle":
                ax, ay, aw, ah = self.area
                x, y = ax + r0 * aw, ay + r1 * ah
                k = 0.5 + 0.5 * math.sin(lt * (1.5 + r2 * 2.5) + i)
                sz = self.size * u * (0.35 + 0.65 * r2) * (0.5 + 0.5 * k)
                a = ex * clamp(lt / 0.8) * (0.4 + 0.6 * k)
                fill_poly(ctx, star_points(x, y, sz, 4, 0.3), (1, 1, 1) if i % 3 else PALETTE["yellow_light"], a, None)

    def _z(self, ctx, x, y, s, a, col):
        pts = [(x - s / 2, y - s / 2), (x + s / 2, y - s / 2), (x - s / 2, y + s / 2), (x + s / 2, y + s / 2)]
        stroke_doodle(ctx, pts, (1, 1, 1), s * 0.18, a, INK, smooth=False)


@dataclass
class Pathway(Doodle):
    """Animated connection through points with travelling pulses (signals / flow)."""
    points: List[Point] = field(default_factory=list)
    color: RGB = PALETTE["purple"]
    pulse_color: RGB = PALETTE["yellow"]
    width: float = 10
    pulses: int = 3
    speed: float = 0.6               # path lengths per second
    curvy: bool = True

    def draw(self, ctx, t):
        if not self.visible(t) or len(self.points) < 2:
            return
        u = self.unit
        p = ease_out_cubic(self.build(t))
        ex = self.exit_factor(t)
        pts = jitter_points(self.points, 1.0 * u, self.seed + boil(t))
        if self.curvy and len(pts) > 2:
            # densify with Catmull-Rom so pulses follow the curve
            dense = []
            for i in range(len(pts) - 1):
                p0 = pts[i - 1] if i > 0 else pts[i]
                p1, p2 = pts[i], pts[i + 1]
                p3 = pts[i + 2] if i + 2 < len(pts) else p2
                for k in range(12):
                    s = k / 12
                    s2, s3 = s * s, s * s * s
                    dense.append(tuple(0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * s + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * s2
                                              + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * s3) for j in range(2)))
            dense.append(pts[-1])
            pts = dense
        part = partial_polyline(pts, p)
        stroke_doodle(ctx, part, self.color, self.width * u, ex, INK, smooth=not self.curvy)
        if p < 1:
            return
        L = polyline_len(pts)
        for k in range(self.pulses):
            f = ((t - self.start - self.duration) * self.speed + k / self.pulses) % 1.0
            seg = partial_polyline(pts, f)
            x, y = seg[-1]
            glow = 0.6 + 0.4 * math.sin(t * 9 + k)
            ctx.arc(x, y, self.width * u * 1.6, 0, 2 * math.pi)
            ctx.set_source_rgba(*self.pulse_color, 0.35 * ex * glow)
            ctx.fill()
            ctx.arc(x, y, self.width * u * 0.85, 0, 2 * math.pi)
            ctx.set_source_rgba(*self.pulse_color, ex)
            ctx.fill_preserve()
            ctx.set_source_rgba(*INK, ex)
            ctx.set_line_width(3 * u)
            ctx.stroke()
        _ = L


# --------------------------------------------------------------------------- charts
@dataclass
class BarChart(Doodle):
    """Hand-drawn bar chart. values in data units; bars grow one after another."""
    values: Sequence[float] = ()
    labels: Sequence[str] = ()
    box: Tuple[float, float, float, float] = (0, 0, 600, 400)   # x, y, w, h
    colors: Tuple[str, ...] = ("teal", "orange", "purple", "coral", "blue", "green")
    value_suffix: str = ""
    show_values: bool = True

    def draw(self, ctx, t):
        if not self.visible(t) or not self.values:
            return
        u = self.unit
        x, y, w, h = self.box
        ex = self.exit_factor(t)
        stroke_doodle(ctx, [(x, y), (x, y + h), (x + w, y + h)], INK, 6 * u, ex, smooth=False)
        n = len(self.values)
        vmax = max(self.values) or 1
        gap = w / n
        bw = gap * 0.6
        for i, v in enumerate(self.values):
            f = ease_out_back(progress(t, self.start + 0.25 * i, 0.6), 1.3)
            bh = (h - 70 * u) * v / vmax * f
            bx = x + gap * i + (gap - bw) / 2
            if bh > 1:
                rounded_rect(ctx, bx, y + h - bh, bw, bh, 12 * u)
                ctx.set_source_rgba(*PALETTE[self.colors[i % len(self.colors)]], ex)
                ctx.fill_preserve()
                ctx.set_source_rgba(*INK, ex)
                ctx.set_line_width(5 * u)
                ctx.stroke()
            st = TextStyle(font=CAPTION_FONT, size=34 * u, color=INK, outline=None)
            if i < len(self.labels):
                lines = wrap_text(ctx, self.labels[i], st, gap * 0.95)
                draw_lines(ctx, lines[:2], bx + bw / 2, y + h + 12 * u, st, "center", ex)
            if self.show_values and f > 0.6:
                st2 = TextStyle(font=CAPTION_FONT, size=36 * u, color=INK, outline=(1, 1, 1), outline_width=6 * u)
                val = f"{v:g}{self.value_suffix}"
                draw_lines(ctx, [val], bx + bw / 2, y + h - bh - 48 * u, st2, "center", ex * clamp((f - 0.6) / 0.3))


@dataclass
class LineChart(Doodle):
    """Line / step chart drawn on progressively (e.g. a sleep-stage hypnogram).

    `points` are (x, y) in [0,1] data space (y=0 bottom). `y_labels` are drawn on the
    left at evenly spaced levels; `step` draws a hypnogram-style step line.
    """
    points: Sequence[Point] = ()
    box: Tuple[float, float, float, float] = (0, 0, 800, 400)
    color: RGB = PALETTE["purple"]
    y_labels: Sequence[str] = ()
    x_labels: Sequence[str] = ()
    step: bool = False
    highlight_level: Optional[int] = None
    width: float = 9

    def _xy(self, p: Point) -> Point:
        x, y, w, h = self.box
        return x + p[0] * w, y + h - p[1] * h

    def draw(self, ctx, t):
        if not self.visible(t) or len(self.points) < 2:
            return
        u = self.unit
        x, y, w, h = self.box
        ex = self.exit_factor(t)
        # card
        rounded_rect(ctx, x - 40 * u, y - 40 * u, w + 80 * u, h + 110 * u, 28 * u)
        ctx.set_source_rgba(1, 1, 1, 0.92 * ex)
        ctx.fill_preserve()
        ctx.set_source_rgba(*INK, ex)
        ctx.set_line_width(5 * u)
        ctx.stroke()
        st = TextStyle(font=CAPTION_FONT, size=30 * u, color=PALETTE["ink_soft"], outline=None)
        n = len(self.y_labels)
        for i, lab in enumerate(self.y_labels):
            ly = y + h - (i / max(1, n - 1)) * h
            ctx.set_dash([8 * u, 10 * u])
            ctx.move_to(x, ly)
            ctx.line_to(x + w, ly)
            ctx.set_source_rgba(*PALETTE["grey"], 0.8 * ex)
            ctx.set_line_width(2.5 * u)
            ctx.stroke()
            ctx.set_dash([])
            if self.highlight_level == i:
                ctx.rectangle(x, ly - h / max(1, n - 1) * 0.35, w, h / max(1, n - 1) * 0.7)
                ctx.set_source_rgba(*PALETTE["yellow"], 0.25 * ex)
                ctx.fill()
            draw_lines(ctx, [lab], x + 10 * u, ly - 36 * u, st, "left", ex)
        for i, lab in enumerate(self.x_labels):
            lx = x + (i / max(1, len(self.x_labels) - 1)) * w
            draw_lines(ctx, [lab], lx, y + h + 14 * u, st, "center", ex)
        pts = [self._xy(p) for p in self.points]
        if self.step:
            sp = []
            for i in range(len(pts) - 1):
                sp += [pts[i], (pts[i + 1][0], pts[i][1])]
            sp.append(pts[-1])
            pts = sp
        part = partial_polyline(pts, ease_in_out_sine(self.build(t)))
        stroke_doodle(ctx, part, self.color, self.width * u, ex, INK, smooth=False)
        if part:
            hx, hy = part[-1]
            ctx.arc(hx, hy, 12 * u, 0, 2 * math.pi)
            ctx.set_source_rgba(*PALETTE["yellow"], ex)
            ctx.fill_preserve()
            ctx.set_source_rgba(*INK, ex)
            ctx.set_line_width(4 * u)
            ctx.stroke()


@dataclass
class WaveLine(Doodle):
    """Scrolling wave (brain waves, sound, heartbeat). kind: sine | brain | heartbeat | slow"""
    box: Tuple[float, float, float, float] = (0, 0, 800, 200)
    kind: str = "brain"
    color: RGB = PALETTE["teal"]
    width: float = 8
    speed: float = 1.0

    def _y(self, xf: float, t: float) -> float:
        ph = xf * 12 - t * 4 * self.speed
        if self.kind == "sine":
            return math.sin(ph)
        if self.kind == "slow":
            return math.sin(ph * 0.35) * 0.9
        if self.kind == "heartbeat":
            k = (ph / (2 * math.pi)) % 1
            return -1.0 if 0.48 < k < 0.52 else (0.6 if 0.52 <= k < 0.56 else 0.05 * math.sin(ph * 3))
        return 0.55 * math.sin(ph) + 0.3 * math.sin(ph * 2.7 + 1) + 0.2 * math.sin(ph * 6.1)

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        x, y, w, h = self.box
        p = ease_out_cubic(self.build(t))
        n = 140
        pts = [(x + w * i / n, y + h / 2 - self._y(i / n, t) * h / 2 * 0.9) for i in range(int(n * p) + 1)]
        stroke_doodle(ctx, pts, self.color, self.width * self.unit, self.exit_factor(t), INK, smooth=False)


DOODLE_TYPES = {
    "draw_path": DrawPath, "arrow": Arrow, "circle": CircleHighlight, "marker": MarkerHighlight,
    "star": StarDoodle, "sparkle": Sparkle, "burst": Burst, "morph": MorphShape, "label": Label,
    "speech_bubble": SpeechBubble, "pop_text": PopText, "counter": Counter, "icon": IconPop,
    "particles": Particles, "pathway": Pathway, "bar_chart": BarChart, "line_chart": LineChart,
    "wave": WaveLine,
}

_ = (HAND_FONT,)
