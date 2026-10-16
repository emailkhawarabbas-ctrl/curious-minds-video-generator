"""Animated explanatory diagrams ("demonstrations") for the ``demonstration`` layout.

A scientific claim deserves a visual explanation, not a sentence on screen. Each demo is a
self-contained, deterministic animation drawn inside a box, revealed in *stages* that the
scene layout synchronises to the narration (stage k starts when its cue word is spoken).

Every demo exposes:
  * ``draw(ctx, t)``            — render at scene time t
  * ``focus(t)``                — where the camera should look at time t (follows the action)
  * ``label_points``            — named points for leader-line labels (filled after construction)

Kinds (see ``DEMO_KINDS``):
  heart_pump, circulation_loop, ecg_heartbeat           — Human Body
  light_scattering, wavelength_compare, sunset_path      — Science
  thought_loop, decision_tree, neural_signal, alarm_response — Psychology
Scientific simplifications are deliberate but never wrong (e.g. blue light is scattered
more than red by air molecules; the right heart pumps oxygen-poor blood to the lungs).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import cairo

from src.animation.doodle_engine import (Doodle, fill_poly, partial_polyline, polyline_len, rounded_rect, star_points,
                                         stroke_doodle)
from src.animation.easing import clamp, ease_in_out_sine, ease_out_back, ease_out_cubic
from src.animation.palette import PALETTE, lighten, mix

Point = Tuple[float, float]
INK = PALETTE["ink"]

DEMO_KINDS = {
    "heart_pump": "Four-chamber heart beating; blue blood enters the right side and leaves for the lungs, red blood "
                  "returns to the left side and is pumped to the body. Stages: heart, right side flow, left side "
                  "flow, full rhythm.",
    "circulation_loop": "Two loops: heart -> lungs -> heart (blood picks up oxygen, turns red) and heart -> body -> "
                        "heart (delivers oxygen, turns blue). Stages: heart, lung loop, body loop, continuous flow.",
    "ecg_heartbeat": "Beating heart synced with an ECG trace that draws itself. Stages: heart, trace, faster rhythm.",
    "light_scattering": "Sunlight (all colours) enters the atmosphere; air molecules scatter blue light in every "
                        "direction while red/yellow travel straight; the sky glows blue for the observer. Stages: "
                        "sunlight, enters air, blue scatters, sky turns blue.",
    "wavelength_compare": "Short blue wave vs long red wave hitting tiny air molecules: blue bounces off, red passes. "
                          "Stages: two waves, molecules, blue scatters.",
    "sunset_path": "Low sun: light crosses much more air, blue is scattered away before it arrives, red/orange "
                   "reach the observer. Stages: noon path, sunset path, red sky.",
    "thought_loop": "A head with worry bubbles circling on a loop that speeds up; then the loop calms. Stages: one "
                    "thought, loop, faster loop, calm.",
    "decision_tree": "One choice branches into what-ifs that multiply; then one path is chosen and the rest fade. "
                     "Stages: choice, branches, more branches, decide.",
    "neural_signal": "A signal travels neuron to neuron across synapses, strengthening the path (memory/learning). "
                     "Stages: neurons, first signal, repeated signals, strong path.",
    "alarm_response": "The brain's alarm (amygdala) fires: heart-rate trace speeds up and the body tenses, then "
                      "calms. Stages: brain, alarm, heart races, calm down.",
}


def _arrow_head(ctx: cairo.Context, p: Point, ang: float, size: float, color, u: float, alpha: float = 1.0) -> None:
    pts = [(p[0] + math.cos(ang) * size, p[1] + math.sin(ang) * size),
           (p[0] + math.cos(ang + 2.5) * size * 0.8, p[1] + math.sin(ang + 2.5) * size * 0.8),
           (p[0] + math.cos(ang - 2.5) * size * 0.8, p[1] + math.sin(ang - 2.5) * size * 0.8)]
    fill_poly(ctx, pts, color, alpha, INK, 3 * u)


def _path_point(pts: Sequence[Point], f: float) -> Tuple[Point, float]:
    """Point and heading at fraction f along a polyline."""
    seg = partial_polyline(pts, clamp(f))
    if len(seg) < 2:
        return pts[0], 0.0
    a, b = seg[-2], seg[-1]
    return b, math.atan2(b[1] - a[1], b[0] - a[0])


def _catmull(pts: Sequence[Point], n: int = 14, closed: bool = False) -> List[Point]:
    P = list(pts) + ([pts[0], pts[1], pts[2]] if closed else [])
    out: List[Point] = []
    rng = range(len(pts)) if closed else range(len(pts) - 1)
    for i in rng:
        p0 = P[i - 1] if (i > 0 or closed) else P[i]
        p1, p2 = P[i], P[i + 1]
        p3 = P[i + 2] if i + 2 < len(P) else p2
        for k in range(n):
            s = k / n
            s2, s3 = s * s, s * s * s
            out.append(tuple(0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * s + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * s2
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * s3) for j in range(2)))
    out.append(P[len(pts)] if closed else pts[-1])
    return out


def _cell(ctx, x, y, r, color, u, alpha=1.0):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(1, 0.7)
    ctx.arc(0, 0, r, 0, 2 * math.pi)
    ctx.restore()
    ctx.set_source_rgba(*color, alpha)
    ctx.fill_preserve()
    ctx.set_source_rgba(*INK, alpha)
    ctx.set_line_width(max(1.0, 2.5 * u))
    ctx.stroke()


def _bubble(ctx, x, y, r, fill, u, alpha=1.0, thought=True):
    ctx.new_path()
    for k in range(7 if thought else 1):
        a = k * 2 * math.pi / 7
        ctx.new_sub_path()
        ctx.arc(x + math.cos(a) * r * 0.55, y + math.sin(a) * r * 0.42, r * 0.5, 0, 2 * math.pi)
    if not thought:
        ctx.arc(x, y, r, 0, 2 * math.pi)
    ctx.set_source_rgba(*INK, alpha)
    ctx.set_line_width(5 * u)
    ctx.stroke_preserve()
    ctx.set_source_rgba(*fill, alpha)
    ctx.fill()


@dataclass
class Demo(Doodle):
    box: Tuple[float, float, float, float] = (0, 0, 100, 100)
    stages: List[float] = field(default_factory=list)     # absolute scene times of stage starts
    assets: Optional[object] = None                       # AssetManager (for asset-based demos)
    label_points: Dict[str, Point] = field(default_factory=dict)

    # ----------------------------------------------------------------- helpers
    def st(self, k: int) -> float:
        if not self.stages:
            return self.start + 1.2 * k
        return self.stages[min(k, len(self.stages) - 1)] + (0.0 if k < len(self.stages) else 1.5 * (k - len(self.stages) + 1))

    def prog(self, t: float, k: int, dur: float = 0.8) -> float:
        return clamp((t - self.st(k)) / dur)

    @property
    def cx(self) -> float:
        return self.box[0] + self.box[2] / 2

    @property
    def cy(self) -> float:
        return self.box[1] + self.box[3] / 2

    def bx(self, f: float) -> float:
        return self.box[0] + self.box[2] * f

    def by(self, f: float) -> float:
        return self.box[1] + self.box[3] * f

    @property
    def s(self) -> float:
        return min(self.box[2], self.box[3])

    def focus(self, t: float) -> Point:
        return self.cx, self.cy

    # ----------------------------------------------------------------- diagram card
    card_fill: Tuple[float, float, float] = (1.0, 0.985, 0.95)

    def card(self, ctx: cairo.Context, t: float) -> float:
        """Draw the card background (drop shadow + fill); returns the entrance progress 0..1."""
        k = ease_out_back(clamp((t - self.start + 0.15) / 0.5), 1.3)
        if k <= 0.01:
            return 0.0
        u = self.unit
        x, y, w, h = self.box
        r = 34 * u
        ctx.save()
        ctx.translate(self.cx, self.cy)
        ctx.scale(k, k)
        ctx.translate(-self.cx, -self.cy)
        rounded_rect(ctx, x + 8 * u, y + 12 * u, w, h, r)
        ctx.set_source_rgba(*INK, 0.35)
        ctx.fill()
        rounded_rect(ctx, x, y, w, h, r)
        ctx.set_source_rgba(*self.card_fill, 0.96)
        ctx.fill()
        ctx.restore()
        return k

    def clip(self, ctx: cairo.Context) -> None:
        x, y, w, h = self.box
        rounded_rect(ctx, x, y, w, h, 34 * self.unit)
        ctx.clip()

    def card_outline(self, ctx: cairo.Context, k: float = 1.0) -> None:
        u = self.unit
        x, y, w, h = self.box
        ctx.save()
        ctx.translate(self.cx, self.cy)
        ctx.scale(k, k)
        ctx.translate(-self.cx, -self.cy)
        rounded_rect(ctx, x, y, w, h, 34 * u)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(7 * u)
        ctx.stroke()
        ctx.restore()

    def content(self, ctx: cairo.Context, t: float) -> None:  # pragma: no cover - implemented by subclasses
        raise NotImplementedError

    def draw(self, ctx: cairo.Context, t: float) -> None:
        """Card + clipped diagram content + outline (subclasses implement ``content``)."""
        if not self.visible(t) or self.assets is None:
            return
        k = self.card(ctx, t)
        if k <= 0.01:
            return
        ctx.save()
        self.clip(ctx)
        self.content(ctx, t)
        ctx.restore()
        self.card_outline(ctx, k)


# =========================================================================== HUMAN BODY

@dataclass
class HeartPump(Demo):
    bpm: float = 72

    def __post_init__(self):
        s = self.s
        h = s * 0.82
        self._h = h
        x0, y0 = self.cx - h / 2, self.cy - h / 2
        P = lambda fx, fy: (x0 + fx * h, y0 + fy * h)      # noqa: E731  (heart_cutaway viewBox 400)
        # blue: vena cava -> right atrium -> right ventricle -> pulmonary artery (to lungs)
        self.blue_path = _catmull([P(0.31, -0.08), P(0.31, 0.3), P(0.33, 0.5), P(0.38, 0.7), P(0.47, 0.62),
                                   P(0.46, 0.36), P(0.52, 0.27), P(0.62, 0.22), P(0.8, 0.12)])
        # red: lungs -> left atrium -> left ventricle -> aorta (to body)
        self.red_path = _catmull([P(1.08, 0.38), P(0.78, 0.48), P(0.68, 0.6), P(0.66, 0.74), P(0.57, 0.62),
                                  P(0.6, 0.36), P(0.62, 0.18), P(0.68, 0.1), P(0.76, 0.16), P(0.79, 0.4)])
        self.label_points = {"right_atrium": P(0.34, 0.49), "left_atrium": P(0.69, 0.5),
                             "right_ventricle": P(0.36, 0.7), "left_ventricle": P(0.67, 0.71),
                             "aorta": P(0.75, 0.3), "to_lungs": P(0.8, 0.12), "valves": P(0.69, 0.58)}

    def beat(self, t: float) -> float:
        period = 60.0 / self.bpm
        ph = ((t - self.st(0)) % period) / period
        return (math.sin(ph * math.pi / 0.3) if ph < 0.3 else 0.0)

    def content(self, ctx, t):
        if not self.visible(t) or self.assets is None:
            return
        u = self.unit
        appear = ease_out_back(self.prog(t, 0, 0.6), 1.5)
        if appear <= 0.01:
            return
        beating = t >= self.st(3) or t >= self.st(1)
        squeeze = 1 - 0.06 * self.beat(t) if beating else 1.0
        a = self.assets.get("heart_cutaway")
        ctx.save()
        ctx.translate(self.cx, self.cy)
        ctx.scale(appear * squeeze, appear * (2 - squeeze))
        ctx.translate(-self.cx, -self.cy)
        a.draw(ctx, self.cx, self.cy, self._h)
        ctx.restore()
        for k, (path, col) in enumerate(((self.blue_path, PALETTE["blue"]), (self.red_path, PALETTE["red"]))):
            p = self.prog(t, 1 + k, 1.2)
            if p <= 0:
                continue
            part = partial_polyline(path, ease_out_cubic(p))
            stroke_doodle(ctx, part, lighten(col, 0.25), 9 * u, 0.85, INK, smooth=False)
            if p >= 1:
                speed = 0.32 * (1.6 if t > self.st(3) else 1.0)
                for i in range(7):
                    f = ((t - self.st(1 + k)) * speed + i / 7) % 1.0
                    (x, y), _ = _path_point(path, f)
                    _cell(ctx, x, y, 15 * u, col, u)
                end, ang = _path_point(path, 1.0)
                _arrow_head(ctx, end, ang, 22 * u, lighten(col, 0.25), u)


@dataclass
class CirculationLoop(Demo):
    def __post_init__(self):
        x, y, w, h = self.box
        self.heart = (self.cx, self.by(0.5))
        self.lungs = (self.cx, self.by(0.1))
        self.body = (self.cx, self.by(0.9))
        r = min(w * 0.38, h * 0.3)
        self.lung_loop = _catmull([self.heart, (self.cx + r * 0.9, self.by(0.32)), (self.lungs[0] + r * 0.4, self.lungs[1]),
                                   (self.lungs[0] - r * 0.4, self.lungs[1]), (self.cx - r * 0.9, self.by(0.32)), self.heart], 16)
        self.body_loop = _catmull([self.heart, (self.cx + r * 1.05, self.by(0.68)), (self.body[0] + r * 0.4, self.body[1]),
                                   (self.body[0] - r * 0.4, self.body[1]), (self.cx - r * 1.05, self.by(0.68)), self.heart], 16)
        self.label_points = {"heart": self.heart, "lungs": self.lungs, "body": self.body,
                             "oxygen_rich": (self.cx + r * 1.05, self.by(0.68)),
                             "oxygen_poor": (self.cx - r * 1.05, self.by(0.68))}

    def focus(self, t):
        if t < self.st(1):
            return self.heart
        if t < self.st(2):
            return (self.cx, self.by(0.3))
        if t < self.st(3):
            return (self.cx, self.by(0.7))
        return self.cx, self.cy

    def _loop(self, ctx, t, path, k, pickup: bool):
        u = self.unit
        p = self.prog(t, k, 1.3)
        if p <= 0:
            return
        n = len(path)
        half = n // 2
        # first half of the lung loop is blue (to lungs), second red; body loop: first red, then blue
        c_first, c_second = (PALETTE["blue"], PALETTE["red"]) if pickup else (PALETTE["red"], PALETTE["blue"])
        part = partial_polyline(path, ease_out_cubic(p))
        stroke_doodle(ctx, part[:half + 1], lighten(c_first, 0.3), 11 * u, 0.9, INK, smooth=False)
        if len(part) > half:
            stroke_doodle(ctx, part[half:], lighten(c_second, 0.3), 11 * u, 0.9, INK, smooth=False)
        if p < 1:
            return
        for i in range(8):
            f = ((t - self.st(k)) * 0.16 + i / 8) % 1.0
            (x, y), ang = _path_point(path, f)
            col = c_first if f < 0.5 else c_second
            _cell(ctx, x, y, 16 * u, col, u)
            if 0.44 < f < 0.56:                       # oxygen exchange at the far end of the loop
                ox = x + (24 * u if pickup else -24 * u) * (1 - abs(f - 0.5) * 8)
                oy = y - 26 * u * (0.5 - abs(f - 0.5) * 4) * (1 if pickup else -1)
                ctx.arc(ox, oy, 8 * u, 0, 2 * math.pi)
                ctx.set_source_rgb(*PALETTE["sky_light"])
                ctx.fill_preserve()
                ctx.set_source_rgb(*INK)
                ctx.set_line_width(2.5 * u)
                ctx.stroke()
        for f in (0.25, 0.75):
            (x, y), ang = _path_point(path, f)
            _arrow_head(ctx, (x, y), ang, 20 * u, (1, 1, 1), u)

    def content(self, ctx, t):
        if not self.visible(t) or self.assets is None:
            return
        u = self.unit
        s = self.s
        p0 = ease_out_back(self.prog(t, 0, 0.6), 1.5)
        if p0 <= 0.01:
            return
        lung_a = self.prog(t, 1, 0.6)
        body_a = self.prog(t, 2, 0.6)
        if lung_a > 0:
            self.assets.get("lungs").draw(ctx, self.lungs[0], self.lungs[1], s * 0.24 * ease_out_back(lung_a, 1.4))
        if body_a > 0:
            self.assets.get("muscle").draw(ctx, self.body[0], self.body[1], s * 0.2 * ease_out_back(body_a, 1.4))
        self._loop(ctx, t, self.lung_loop, 1, pickup=True)
        self._loop(ctx, t, self.body_loop, 2, pickup=False)
        beat = 1 + 0.07 * max(0.0, math.sin((t - self.st(0)) * 2 * math.pi * 1.2)) ** 6
        self.assets.get("heart").draw(ctx, self.heart[0], self.heart[1], s * 0.26 * p0 * beat)


@dataclass
class EcgHeartbeat(Demo):
    def content(self, ctx, t):
        if not self.visible(t) or self.assets is None:
            return
        u = self.unit
        x, y, w, h = self.box
        p0 = ease_out_back(self.prog(t, 0, 0.6), 1.5)
        bpm = 70 if t < self.st(2) else 110
        period = 60 / bpm
        ph = ((t - self.st(0)) % period) / period
        beat = 1 + 0.12 * (math.sin(ph * math.pi / 0.25) if ph < 0.25 else 0)
        self.assets.get("heart").draw(ctx, self.cx, self.by(0.3), self.s * 0.42 * p0 * beat)
        p = self.prog(t, 1, 0.5)
        if p <= 0:
            return
        mx, my, mw, mh = x + w * 0.04, self.by(0.62), w * 0.92, h * 0.32
        rounded_rect(ctx, mx, my, mw, mh, 22 * u)
        ctx.set_source_rgb(*PALETTE["night"])
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(6 * u)
        ctx.stroke()
        ctx.save()
        rounded_rect(ctx, mx, my, mw, mh, 22 * u)
        ctx.clip()
        speed = 0.55 if t < self.st(2) else 0.9
        drawn = clamp((t - self.st(1)) / 2.5)
        pts = []
        for k in range(160):
            fx = k / 159
            if fx > drawn:
                break
            phase = (fx * 3.2 - (t - self.st(1)) * speed * (bpm / 70)) % 1.0
            v = 0.0
            if 0.40 < phase < 0.43:
                v = -0.12
            elif 0.45 < phase < 0.48:
                v = 0.85
            elif 0.48 <= phase < 0.51:
                v = -0.35
            elif 0.62 < phase < 0.7:
                v = 0.18 * math.sin((phase - 0.62) / 0.08 * math.pi)
            pts.append((mx + fx * mw, my + mh * 0.6 - v * mh * 0.45))
        if len(pts) > 1:
            ctx.move_to(*pts[0])
            for q in pts[1:]:
                ctx.line_to(*q)
            ctx.set_source_rgb(*PALETTE["green"])
            ctx.set_line_width(6 * u)
            ctx.stroke()
        ctx.restore()
        self.label_points = {"heart": (self.cx, self.by(0.3)), "trace": (mx + mw * 0.5, my + mh * 0.3)}


# =========================================================================== SCIENCE
def _sky_panel(ctx, demo, t, sky_tint: float, red_tint: float = 0.0):
    """Space band, atmosphere and ground inside the demo card (shared by the sky demos)."""
    x, y, w, h = demo.box
    u = demo.unit
    space_h, ground_y = h * 0.17, y + h * 0.86
    ctx.rectangle(x, y, w, space_h)
    ctx.set_source_rgb(*PALETTE["night"])
    ctx.fill()
    rnd = random.Random(7)
    for _ in range(14):
        ctx.arc(x + rnd.random() * w, y + rnd.random() * space_h, (1.5 + 2 * rnd.random()) * u, 0, 2 * math.pi)
        ctx.set_source_rgba(1, 1, 1, 0.8)
        ctx.fill()
    g = cairo.LinearGradient(0, y + space_h, 0, ground_y)
    top = mix(mix(PALETTE["sky_light"], PALETTE["sky"], sky_tint), PALETTE["orange"], red_tint)
    bot = mix(mix((0.93, 0.97, 1.0), PALETTE["sky_light"], sky_tint), PALETTE["coral"], red_tint)
    g.add_color_stop_rgb(0, *top)
    g.add_color_stop_rgb(1, *bot)
    ctx.rectangle(x, y + space_h, w, ground_y - y - space_h)
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(x, ground_y, w, y + h - ground_y)
    ctx.set_source_rgb(*PALETTE["leaf"])
    ctx.fill()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(4 * u)
    ctx.move_to(x, ground_y)
    ctx.line_to(x + w, ground_y)
    ctx.stroke()
    return space_h, ground_y


@dataclass
class LightScattering(Demo):
    def __post_init__(self):
        x, y, w, h = self.box
        self.sun = (self.bx(0.15), self.by(0.085))
        self.hit = (self.bx(0.42), self.by(0.4))
        self.ground = self.by(0.86)
        self.observer = (self.bx(0.66), self.ground)
        rnd = random.Random(5)
        self.molecules = [(self.bx(0.05 + 0.9 * rnd.random()), self.by(0.2 + 0.62 * rnd.random()), rnd.random() < 0.78)
                          for _ in range(26)]
        # molecules that sit on the beam scatter blue light
        self.scatterers = [(self.sun[0] + (self.hit[0] - self.sun[0]) * f, self.sun[1] + (self.hit[1] - self.sun[1]) * f)
                           for f in (0.62, 0.82)] + [self.hit]
        self.sky_points = [(self.bx(0.12), self.by(0.3)), (self.bx(0.3), self.by(0.24)), (self.bx(0.86), self.by(0.28)),
                           (self.bx(0.92), self.by(0.55)), (self.bx(0.2), self.by(0.6))]
        self.label_points = {"sun": self.sun, "air": self.molecules[3][:2], "blue": (self.hit[0] + 60 * self.unit,
                                                                                     self.hit[1] - 50 * self.unit),
                             "observer": (self.observer[0], self.observer[1] - self.s * 0.2),
                             "red": (self.bx(0.8), self.by(0.75))}

    def focus(self, t):
        if t < self.st(1):
            return (self.bx(0.32), self.by(0.3))
        if t < self.st(3):
            return self.hit
        return self.cx, self.by(0.55)

    def draw(self, ctx, t):
        if not self.visible(t) or self.assets is None:
            return
        u = self.unit
        x, y, w, h = self.box
        k_in = self.card(ctx, t)
        if k_in <= 0.01:
            return
        ctx.save()
        self.clip(ctx)
        sky = self.prog(t, 3, 2.0)
        _sky_panel(ctx, self, t, sky)
        # air molecules (N2 blue pairs, O2 red pairs)
        mol = self.prog(t, 1, 0.8)
        for i, (mx, my, is_n) in enumerate(self.molecules):
            k = clamp(mol * 1.8 - i / len(self.molecules) * 0.8)
            if k <= 0:
                continue
            col = PALETTE["blue"] if is_n else PALETTE["coral"]
            for dx in (-6, 6):
                ctx.arc(mx + dx * u * k, my + math.sin(t * 2 + i) * 3 * u, 8 * u * k, 0, 2 * math.pi)
                ctx.set_source_rgb(*col)
                ctx.fill_preserve()
                ctx.set_source_rgb(*INK)
                ctx.set_line_width(2.5 * u)
                ctx.stroke()
        # sun
        ps = ease_out_back(self.prog(t, 0, 0.6), 1.5)
        if ps > 0.01:
            self.assets.get("sun").draw(ctx, self.sun[0], self.sun[1], self.s * 0.2 * ps, rotation=t * 8)
        # white beam = all colours bundled together
        pb = clamp((t - self.st(0) - 0.3) / 1.0)
        cols = ("red", "orange", "yellow", "green", "blue", "purple")
        if pb > 0:
            end = (self.sun[0] + (self.hit[0] - self.sun[0]) * ease_out_cubic(pb),
                   self.sun[1] + (self.hit[1] - self.sun[1]) * ease_out_cubic(pb))
            for i, c in enumerate(cols):
                off = (i - 2.5) * 5 * u
                stroke_doodle(ctx, [(self.sun[0] + off, self.sun[1] - off * 0.5), (end[0] + off, end[1] - off * 0.5)],
                              PALETTE[c], 6 * u, 1.0, None, smooth=False)
        pr = self.prog(t, 2, 1.0)
        if pr > 0:
            # red / orange / yellow carry on almost straight to the ground
            far = (self.bx(0.9), self.ground - 6 * u)
            end = (self.hit[0] + (far[0] - self.hit[0]) * ease_out_cubic(pr), self.hit[1] + (far[1] - self.hit[1]) * ease_out_cubic(pr))
            for i, c in enumerate(("red", "orange", "yellow")):
                off = (i - 1) * 6 * u
                stroke_doodle(ctx, [(self.hit[0] + off, self.hit[1]), (end[0] + off, end[1])], PALETTE[c], 7 * u, 1.0,
                              None, smooth=False)
            if pr >= 1:
                _arrow_head(ctx, far, math.atan2(far[1] - self.hit[1], far[0] - self.hit[0]), 18 * u, PALETTE["orange"], u)
            # blue is scattered in every direction from the molecules on the beam
            reach = self.s * 0.22
            for si, (sx, sy) in enumerate(self.scatterers):
                ctx.arc(sx, sy, 14 * u * (1 + 0.2 * math.sin(t * 7 + si)), 0, 2 * math.pi)
                ctx.set_source_rgba(1, 1, 1, 0.75 * pr)
                ctx.fill()
                for j in range(8):
                    ang = j * math.pi / 4 + si * 0.4
                    for wave in range(2):
                        f = (((t - self.st(2)) * 0.7 + wave * 0.5 + j * 0.03) % 1.0) * min(1.0, pr * 1.5)
                        r0 = 18 * u + reach * f
                        a = (1 - f) * pr
                        p0 = (sx + math.cos(ang) * r0, sy + math.sin(ang) * r0)
                        p1 = (sx + math.cos(ang) * (r0 + 26 * u), sy + math.sin(ang) * (r0 + 26 * u))
                        stroke_doodle(ctx, [p0, p1], PALETTE["blue"], 8 * u, min(1.0, a * 1.3), INK, smooth=False)
        # the observer sees blue arriving from every part of the sky
        po = ease_out_back(self.prog(t, 2, 0.6), 1.5)
        if po > 0.01:
            self.assets.get("observer_kid").draw(ctx, self.observer[0], self.observer[1] - self.s * 0.1,
                                                 self.s * 0.2 * po)
        if sky > 0:
            eye = (self.observer[0] + 2 * u, self.observer[1] - self.s * 0.155)
            for i, p in enumerate(self.sky_points):
                f = clamp(sky * 1.6 - i * 0.12)
                if f <= 0:
                    continue
                q = (p[0] + (eye[0] - p[0]) * f, p[1] + (eye[1] - p[1]) * f)
                ctx.save()
                ctx.set_dash([14 * u, 10 * u], -(t * 60 * u))
                ctx.move_to(*p)
                ctx.line_to(*q)
                ctx.set_source_rgba(*PALETTE["blue"], 0.85)
                ctx.set_line_width(5 * u)
                ctx.stroke()
                ctx.restore()
                if f >= 1:
                    _arrow_head(ctx, eye, math.atan2(eye[1] - p[1], eye[0] - p[0]), 14 * u, PALETTE["blue"], u)
        ctx.restore()
        self.card_outline(ctx, k_in)


@dataclass
class WavelengthCompare(Demo):
    def draw(self, ctx, t):
        if not self.visible(t):
            return
        u = self.unit
        x, y, w, h = self.box
        k_in = self.card(ctx, t)
        if k_in <= 0.01:
            return
        ctx.save()
        self.clip(ctx)
        rows = ((self.by(0.3), PALETTE["blue"], 0.07, True), (self.by(0.72), PALETTE["red"], 0.2, False))
        mol_x = self.bx(0.62)
        pm = ease_out_back(self.prog(t, 1, 0.5), 1.6)
        for k, (yy, col, lam, scatters) in enumerate(rows):
            p = self.prog(t, 0, 1.2 + 0.2 * k)
            if p <= 0:
                continue
            reach = x + w * 0.05 + (w * 0.9) * ease_out_cubic(p)
            stop = mol_x if (scatters and t >= self.st(2)) else reach
            pts = []
            xx = x + w * 0.05
            while xx < min(reach, stop):
                ph = (xx - x) / (w * lam) * 2 * math.pi - t * 6
                pts.append((xx, yy + math.sin(ph) * h * 0.08))
                xx += 4 * u
            if len(pts) > 1:
                stroke_doodle(ctx, pts, col, 8 * u, 1.0, INK, smooth=False)
            if pm > 0.01:
                for dx in (-10, 10):
                    ctx.arc(mol_x + dx * u * pm, yy, 14 * u * pm, 0, 2 * math.pi)
                    ctx.set_source_rgb(*PALETTE["sky"])
                    ctx.fill_preserve()
                    ctx.set_source_rgb(*INK)
                    ctx.set_line_width(3 * u)
                    ctx.stroke()
            if scatters and t >= self.st(2):
                ps = clamp((t - self.st(2)) / 0.9)
                for j in range(6):
                    ang = -math.pi / 2 + j * math.pi / 2.5 + 0.3
                    r0, r1 = 28 * u, (28 + 130 * ease_out_cubic(ps)) * u
                    seg = [(mol_x + math.cos(ang) * r0, yy + math.sin(ang) * r0),
                           (mol_x + math.cos(ang) * r1, yy + math.sin(ang) * r1)]
                    stroke_doodle(ctx, seg, lighten(col, 0.2), 6 * u, 0.95, INK, smooth=False)
                    _arrow_head(ctx, seg[1], ang, 14 * u, lighten(col, 0.2), u)
        ctx.restore()
        self.card_outline(ctx, k_in)
        self.label_points = {"blue": (self.bx(0.2), self.by(0.2)), "red": (self.bx(0.2), self.by(0.62)),
                             "molecule": (mol_x, self.by(0.5))}


@dataclass
class SunsetPath(Demo):
    """Curved Earth + atmosphere: overhead sun = short path through air; low sun = long path, blue peeled away."""

    def __post_init__(self):
        x, y, w, h = self.box
        self.R = h * 2.6
        self.atm = h * 0.36
        self.c = (self.cx, y + h * 0.8 + self.R)
        self.obs = (self.cx, y + h * 0.8)
        self.label_points = {"sun": (self.bx(0.12), self.by(0.62)), "observer": (self.obs[0], self.obs[1] - self.s * 0.14),
                             "path": (self.bx(0.32), self.by(0.6))}

    def _sun(self, t):
        f = ease_in_out_sine(self.prog(t, 1, 1.6))
        noon = (self.cx, self.by(0.13))
        low = (self.bx(0.1), self.by(0.6))
        return (noon[0] + (low[0] - noon[0]) * f, noon[1] + (low[1] - noon[1]) * f), f

    def focus(self, t):
        sun, f = self._sun(t)
        return ((sun[0] + self.obs[0]) / 2, (sun[1] + self.obs[1]) / 2 + self.box[3] * 0.08)

    def _in_air(self, p) -> bool:
        return math.hypot(p[0] - self.c[0], p[1] - self.c[1]) < self.R + self.atm

    def draw(self, ctx, t):
        if not self.visible(t) or self.assets is None:
            return
        u = self.unit
        x, y, w, h = self.box
        k_in = self.card(ctx, t)
        if k_in <= 0.01:
            return
        ctx.save()
        self.clip(ctx)
        sun, f = self._sun(t)
        redden = self.prog(t, 2, 1.6)
        ctx.rectangle(x, y, w, h)
        ctx.set_source_rgb(*mix(PALETTE["night"], PALETTE["purple_dark"], 0.4 * f))
        ctx.fill()
        # atmosphere shell (blue by day, warm near the horizon at sunset)
        ctx.arc(self.c[0], self.c[1], self.R + self.atm, 0, 2 * math.pi)
        ctx.set_source_rgb(*mix(PALETTE["sky"], PALETTE["orange"], 0.85 * redden))
        ctx.fill()
        ctx.arc(self.c[0], self.c[1], self.R + self.atm * 0.45, 0, 2 * math.pi)
        ctx.set_source_rgb(*mix(PALETTE["sky_light"], PALETTE["coral"], 0.8 * redden))
        ctx.fill()
        ctx.arc(self.c[0], self.c[1], self.R, 0, 2 * math.pi)
        ctx.set_source_rgb(*PALETTE["green"])
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(5 * u)
        ctx.stroke()
        self.assets.get("observer_kid").draw(ctx, self.obs[0], self.obs[1] - self.s * 0.11, self.s * 0.22)
        self.assets.get("sun").draw(ctx, sun[0], sun[1], self.s * 0.22, rotation=t * 6)
        p = self.prog(t, 0, 0.8)
        if p > 0:
            eye = (self.obs[0], self.obs[1] - self.s * 0.17)
            end = (sun[0] + (eye[0] - sun[0]) * ease_out_cubic(p), sun[1] + (eye[1] - sun[1]) * ease_out_cubic(p))
            n = 24
            pts = [(sun[0] + (end[0] - sun[0]) * i / n, sun[1] + (end[1] - sun[1]) * i / n) for i in range(n + 1)]
            in_air = [q for q in pts if self._in_air(q)]
            air_len = len(in_air) / n
            # the beam warms as blue is removed along the in-air part of the path
            for i in range(n):
                a, b = pts[i], pts[i + 1]
                depth = sum(1 for q in pts[:i + 1] if self._in_air(q)) / n
                col = mix(PALETTE["yellow_light"], PALETTE["red"], clamp(depth * 1.6 * f + 0.0))
                stroke_doodle(ctx, [a, b], col, 11 * u, 1.0, None, smooth=False)
            # blue peeled off sideways along the air path
            for i, q in enumerate(in_air[::2]):
                side = 1 if i % 2 else -1
                ang = math.atan2(eye[1] - sun[1], eye[0] - sun[0]) + side * math.pi / 2
                L = (24 + 10 * math.sin(t * 5 + i)) * u * min(1.0, 0.4 + air_len * 2)
                stroke_doodle(ctx, [q, (q[0] + math.cos(ang) * L, q[1] + math.sin(ang) * L)], PALETTE["blue"], 5 * u,
                              0.95, None, smooth=False)
        ctx.restore()
        self.card_outline(ctx, k_in)
        self.label_points = {"sun": (sun[0], sun[1]), "observer": (self.obs[0], self.obs[1] - self.s * 0.14),
                             "path": ((sun[0] + self.obs[0]) / 2, (sun[1] + self.obs[1]) / 2)}


# =========================================================================== PSYCHOLOGY
@dataclass
class ThoughtLoop(Demo):
    def __post_init__(self):
        self.head = (self.bx(0.5), self.by(0.62))
        self.label_points = {"head": self.head, "loop": (self.bx(0.5), self.by(0.2)), "thought": (self.bx(0.82), self.by(0.3))}

    def content(self, ctx, t):
        if not self.visible(t) or self.assets is None:
            return
        u = self.unit
        s = self.s
        p0 = ease_out_back(self.prog(t, 0, 0.6), 1.5)
        calm = self.prog(t, 3, 1.5)
        shake = (0.0 if calm >= 1 else (1 - calm) * (2.5 * u * math.sin(t * 40)) * (1 if t > self.st(2) else 0))
        self.assets.get("overthinking_head").draw(ctx, self.head[0] + shake, self.head[1], s * 0.5 * p0)
        loop_p = self.prog(t, 1, 0.9)
        if loop_p <= 0:
            if t > self.st(0) + 0.4:
                _bubble(ctx, self.bx(0.78), self.by(0.3), s * 0.09, (1, 1, 1), u, p0)
                self.assets.get("question_mark").draw(ctx, self.bx(0.78), self.by(0.3), s * 0.1 * p0)
            return
        c = (self.bx(0.5), self.by(0.32))
        rx, ry = s * 0.42, s * 0.2
        ctx.save()
        ctx.translate(*c)
        ctx.scale(1, ry / rx)
        ctx.arc(0, 0, rx, 0, 2 * math.pi * ease_out_cubic(loop_p))
        ctx.restore()
        ctx.set_source_rgba(*PALETTE["lavender"], 0.9 * (1 - calm * 0.8))
        ctx.set_line_width(10 * u)
        ctx.stroke()
        speed = 0.18 + 0.32 * self.prog(t, 2, 1.2)
        speed *= (1 - 0.85 * calm)
        icons = ("question_mark", "worried_face", "clock", "chat_bubbles", "question_mark")
        n = len(icons)
        base = getattr(self, "_phase", 0.0)
        for i, name in enumerate(icons):
            f = ((t - self.st(1)) * speed + i / n) % 1.0
            a = f * 2 * math.pi
            bx, by = c[0] + math.cos(a) * rx, c[1] + math.sin(a) * ry
            k = clamp(loop_p * 2 - i * 0.2) * (1 - 0.6 * calm)
            if k <= 0:
                continue
            _bubble(ctx, bx, by, s * 0.075 * k, (1, 1, 1), u, k)
            self.assets.get(name).draw(ctx, bx, by, s * 0.08 * k)
        _ = base
        for f in (0.0, 0.5):
            a = ((t - self.st(1)) * speed + f) * 2 * math.pi + 0.35
            p = (c[0] + math.cos(a) * rx, c[1] + math.sin(a) * ry)
            _arrow_head(ctx, p, a + math.pi / 2, 20 * u, PALETTE["purple"], u, 1 - calm)


@dataclass
class DecisionTree(Demo):
    depth: int = 3

    def __post_init__(self):
        x, y, w, h = self.box
        self.root = (self.bx(0.5), self.by(0.12))
        self.nodes: List[Tuple[int, Point, Optional[int]]] = [(0, self.root, None)]
        level = [0]
        for d in range(1, self.depth + 1):
            nxt = []
            count = 2 ** d
            for j in range(count):
                parent = level[j // 2]
                p = (self.bx((j + 0.5) / count), self.by(0.12 + 0.8 * d / self.depth))
                self.nodes.append((d, p, parent))
                nxt.append(len(self.nodes) - 1)
            level = nxt
        # the chosen path: always the first child that leads to the 2nd leaf
        self.chosen = {0}
        cur = 0
        for d in range(1, self.depth + 1):
            kids = [i for i, (dd, _, par) in enumerate(self.nodes) if par == cur]
            cur = kids[1 if d % 2 else 0]
            self.chosen.add(cur)
        self.label_points = {"choice": self.root, "what_ifs": self.nodes[-3][1], "decision": self.nodes[max(self.chosen)][1]}

    def content(self, ctx, t):
        if not self.visible(t):
            return
        u = self.unit
        decide = self.prog(t, 3, 1.2)
        for i, (d, p, par) in enumerate(self.nodes):
            stage = 0 if d == 0 else (1 if d == 1 else 2)
            k = self.prog(t, stage, 0.6) if d < 3 else self.prog(t, 2, 0.6) * clamp((t - self.st(2) - 0.5) / 0.6)
            if k <= 0:
                continue
            fade = 1.0 if (i in self.chosen or decide <= 0) else 1 - 0.75 * decide
            if par is not None:
                q = self.nodes[par][1]
                end = (q[0] + (p[0] - q[0]) * ease_out_cubic(k), q[1] + (p[1] - q[1]) * ease_out_cubic(k))
                col = PALETTE["green"] if (i in self.chosen and decide > 0) else PALETTE["lavender"]
                stroke_doodle(ctx, [q, end], col, (10 if i in self.chosen and decide > 0 else 7) * u, fade, INK,
                              smooth=False)
            r = (34 if d == 0 else 26 - 3 * d) * u * ease_out_back(k, 1.6)
            fill = PALETTE["yellow"] if d == 0 else (PALETTE["green"] if (i in self.chosen and decide > 0)
                                                     else PALETTE[("teal_light", "pink_light", "lavender")[d % 3]])
            if d == 0:
                ctx.arc(p[0], p[1], r, 0, 2 * math.pi)
                ctx.set_source_rgba(*fill, fade)
                ctx.fill_preserve()
                ctx.set_source_rgba(*INK, fade)
                ctx.set_line_width(5 * u)
                ctx.stroke()
            else:
                _bubble(ctx, p[0], p[1], r * 1.3, fill, u, fade)
                if d == self.depth and decide <= 0:
                    st = (t - self.st(2)) * 3 + i
                    ctx.set_source_rgba(*INK, 0.8 * fade)
                    ctx.select_font_face("sans-serif", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
                    ctx.set_font_size(r * 1.1)
                    ctx.move_to(p[0] - r * 0.3, p[1] + r * 0.38 + math.sin(st) * 2 * u)
                    ctx.show_text("?")


@dataclass
class NeuralSignal(Demo):
    n: int = 4

    def __post_init__(self):
        self.pts = [(self.bx(0.1 + 0.8 * i / (self.n - 1)), self.by(0.5 + (0.12 if i % 2 else -0.12))) for i in range(self.n)]
        self.label_points = {"neuron": self.pts[0], "synapse": ((self.pts[1][0] + self.pts[2][0]) / 2, self.by(0.5)),
                             "signal": self.pts[-1]}

    def content(self, ctx, t):
        if not self.visible(t) or self.assets is None:
            return
        u = self.unit
        s = self.s
        strength = self.prog(t, 3, 1.0)
        for i in range(self.n - 1):
            a, b = self.pts[i], self.pts[i + 1]
            k = self.prog(t, 0, 0.6 + 0.2 * i)
            if k > 0:
                end = (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k)
                stroke_doodle(ctx, [a, end], mix(PALETTE["lavender"], PALETTE["yellow"], strength),
                              (6 + 8 * strength) * u, 0.9, INK, smooth=False)
        for i, p in enumerate(self.pts):
            k = ease_out_back(self.prog(t, 0, 0.5 + 0.15 * i), 1.5)
            if k > 0.01:
                self.assets.get("neuron").draw(ctx, p[0], p[1], s * 0.24 * k, rotation=-15 + 30 * (i % 2))
        if t >= self.st(1):
            # stage 1: the first signal lights the pathway behind it; stage 2: repeated firing makes neurons glow;
            # stage 3: the well-used path is strong and bright (a "memory trace")
            trail = clamp((t - self.st(1)) / 1.2)
            seg = partial_polyline(self.pts, trail)
            if len(seg) > 1:
                stroke_doodle(ctx, seg, PALETTE["yellow"], (16 + 14 * strength) * u, 0.35 + 0.4 * strength, None,
                              smooth=False)
            reps = 1 if t < self.st(2) else 3
            fire = self.prog(t, 2, 0.6)
            for i, p in enumerate(self.pts):
                if fire > 0:
                    ctx.arc(p[0], p[1], s * 0.11 * (1 + 0.12 * math.sin(t * 6 + i)), 0, 2 * math.pi)
                    ctx.set_source_rgba(*PALETTE["yellow_light"], 0.45 * fire)
                    ctx.fill()
            for r in range(reps):
                f = ((t - self.st(1)) * (0.45 + 0.25 * strength) + r / reps) % 1.0
                (x, y), _ = _path_point(self.pts, f)
                glow = 30 * u * (1 + strength)
                ctx.arc(x, y, glow, 0, 2 * math.pi)
                ctx.set_source_rgba(*PALETTE["yellow"], 0.4)
                ctx.fill()
                fill_poly(ctx, star_points(x, y, 22 * u, 5, 0.45, t * 120), PALETTE["yellow"], 1.0, INK, 3 * u)


@dataclass
class AlarmResponse(Demo):
    def content(self, ctx, t):
        if not self.visible(t) or self.assets is None:
            return
        u = self.unit
        s = self.s
        alarm = self.prog(t, 1, 0.4)
        race = self.prog(t, 2, 0.6)
        calm = self.prog(t, 3, 1.5)
        p0 = ease_out_back(self.prog(t, 0, 0.6), 1.5)
        name = "amygdala_alarm" if alarm > 0 and calm < 1 else "brain"
        wob = (1 + 0.06 * math.sin(t * 18) * alarm * (1 - calm))
        self.assets.get(name).draw(ctx, self.bx(0.3), self.by(0.32), s * 0.4 * p0 * wob)
        bpm = 70 + 60 * race * (1 - calm)
        ph = (t * bpm / 60) % 1.0
        beat = 1 + 0.12 * (math.sin(ph * math.pi / 0.25) if ph < 0.25 else 0)
        if race > 0:
            self.assets.get("heart").draw(ctx, self.bx(0.74), self.by(0.3), s * 0.3 * ease_out_back(race, 1.4) * beat)
            mx, my, mw, mh = self.bx(0.06), self.by(0.64), self.box[2] * 0.88, self.box[3] * 0.28
            rounded_rect(ctx, mx, my, mw, mh, 20 * u)
            ctx.set_source_rgb(*PALETTE["night"])
            ctx.fill_preserve()
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(6 * u)
            ctx.stroke()
            pts = []
            for k in range(140):
                fx = k / 139
                phase = (fx * (2 + 3 * race * (1 - calm)) - t * bpm / 60) % 1.0
                v = 0.8 if 0.46 < phase < 0.49 else (-0.3 if 0.49 <= phase < 0.52 else 0)
                pts.append((mx + 14 * u + fx * (mw - 28 * u), my + mh * 0.6 - v * mh * 0.45))
            ctx.move_to(*pts[0])
            for q in pts[1:]:
                ctx.line_to(*q)
            ctx.set_source_rgb(*mix(PALETTE["green"], PALETTE["coral"], race * (1 - calm)))
            ctx.set_line_width(5 * u)
            ctx.stroke()
        if alarm > 0 and calm < 1:
            for i in range(3):
                r = (s * 0.22 + ((t * 120 * u + i * 40 * u) % (90 * u)))
                ctx.arc(self.bx(0.3), self.by(0.32), r, -0.8, 0.8)
                ctx.set_source_rgba(*PALETTE["coral"], 0.6 * (1 - calm))
                ctx.set_line_width(6 * u)
                ctx.stroke()
        self.label_points = {"alarm": (self.bx(0.3), self.by(0.32)), "heart": (self.bx(0.74), self.by(0.3)),
                             "heart_rate": (self.bx(0.5), self.by(0.7))}


DEMO_CLASSES = {
    "heart_pump": HeartPump, "circulation_loop": CirculationLoop, "ecg_heartbeat": EcgHeartbeat,
    "light_scattering": LightScattering, "wavelength_compare": WavelengthCompare, "sunset_path": SunsetPath,
    "thought_loop": ThoughtLoop, "decision_tree": DecisionTree, "neural_signal": NeuralSignal,
    "alarm_response": AlarmResponse,
}
STAGE_COUNT = {"heart_pump": 4, "circulation_loop": 4, "ecg_heartbeat": 3, "light_scattering": 4,
               "wavelength_compare": 3, "sunset_path": 3, "thought_loop": 4, "decision_tree": 4,
               "neural_signal": 4, "alarm_response": 4}


def make_demo(kind: str, box, stages: Sequence[float], assets, unit: float, seed: int = 0) -> Demo:
    cls = DEMO_CLASSES[kind]
    d = cls(box=tuple(box), stages=list(stages), assets=assets, start=stages[0] if stages else 0.2,
            duration=0.6, z=3)
    d.unit = unit
    d.seed = seed
    if hasattr(d, "__post_init__"):
        d.__post_init__()           # recompute geometry with the final unit/seed
    return d
