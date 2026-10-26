"""Whiteboard drawing: things are traced stroke by stroke by a pen that a visible hand holds.

* ``stroke_order`` plans how an SVG is drawn: big shapes first, details after, each tier in
  nearest-neighbour order so the pen does not jump around; fill-only shapes get an outline
  traced around them (``outline_asset``) so every part is drawn, not popped in.
* ``PenDrawing`` subclasses (``DrawnSvg``, ``HandText``, ``PenPath``) know where the pen is at
  any time (``pen(t)``) and draw their partial strokes; colour fills fade in at the end.
* ``DrawingHand`` follows the pen of a list of drawings, lifts between strokes, travels
  between drawings and leaves the frame when it has nothing to draw for a while.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cairo

from src.animation.boil import boil_variant, boiled
from src.animation.doodle_engine import Doodle
from src.animation.easing import clamp, ease_in_out_sine, ease_out_cubic
from src.animation.svg_loader import Shape, SvgAsset, load_svg
from src.config.settings import PROJECT_ROOT

Point = Tuple[float, float]
RGB = Tuple[float, float, float]
HAND_SVG = PROJECT_ROOT / "assets" / "hands" / "marker_hand.svg"
INK = (0x2B / 255, 0x2D / 255, 0x42 / 255)


# --------------------------------------------------------------------------- SVG analysis
def _bbox(polys: Sequence[Sequence[Point]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for poly in polys for p in poly] or [0.0]
    ys = [p[1] for poly in polys for p in poly] or [0.0]
    return min(xs), min(ys), max(xs), max(ys)


def _area(sh: Shape) -> float:
    x0, y0, x1, y1 = _bbox(sh.polylines)
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def decorative(sh: Shape) -> bool:
    """A fill-only shine or shadow (light or translucent): it just fades in with the colours."""
    if sh.stroke is not None or sh.fill is None:
        return False
    r, g, b, a = sh.fill
    return a < 0.85 or 0.299 * r + 0.587 * g + 0.114 * b > 0.92


def outline_eligible(sh: Shape, asset: SvgAsset) -> bool:
    """A fill-only shape that should get a traced outline (not shines, shadows or tiny dots)."""
    if sh.stroke is not None or sh.fill is None or decorative(sh):
        return False
    return _area(sh) >= 0.002 * asset.view_w * asset.view_h


def typical_stroke_width(asset: SvgAsset) -> float:
    ws = sorted(sh.stroke_width for sh in asset.shapes if sh.stroke is not None)
    return ws[len(ws) // 2] if ws else 6.0 * asset.view_h / 400


_OUTLINED: Dict[int, SvgAsset] = {}


def outline_asset(asset: SvgAsset) -> SvgAsset:
    """The asset with an ink outline added to every eligible fill-only shape (cached)."""
    hit = _OUTLINED.get(id(asset))
    if hit is None:
        w = typical_stroke_width(asset) * 0.8
        shapes = [replace(sh, stroke=(*INK, 1.0), stroke_width=w) if outline_eligible(sh, asset) else sh
                  for sh in asset.shapes]
        hit = replace(asset, shapes=shapes)
        _OUTLINED[id(asset)] = hit
    return hit


def classify_asset(asset: SvgAsset) -> Dict:
    """How well an SVG suits stroke-by-stroke drawing (used by scripts/audit_assets.py)."""
    stroked = [sh for sh in asset.shapes if sh.stroke is not None]
    fill_only = [sh for sh in asset.shapes if sh.stroke is None and sh.fill is not None and not decorative(sh)]
    outlined = [sh for sh in fill_only if outline_eligible(sh, asset)]
    solid = [sh for sh in asset.shapes if sh.fill is not None and not decorative(sh)]
    area_all = sum(_area(sh) for sh in solid)
    area_lined = sum(_area(sh) for sh in solid if sh.stroke is not None or outline_eligible(sh, asset))
    coverage = area_lined / area_all if area_all else 1.0          # no colour areas: pure line art
    if not fill_only:
        kind = "line_art"
    elif not stroked:
        kind = "fill_only"
    else:
        kind = "mixed"
    return {"kind": kind, "shapes": len(asset.shapes), "stroked": len(stroked), "fill_only": len(fill_only),
            "auto_outlined": len(outlined), "line_coverage": round(coverage, 2),
            "needs_redraw": coverage < 0.6 or (kind == "fill_only" and len(asset.shapes) > 25)}


@dataclass(frozen=True)
class StrokeRef:
    shape: int
    poly: int
    reverse: bool


_ORDER: Dict[int, List[StrokeRef]] = {}


def stroke_order(asset: SvgAsset) -> List[StrokeRef]:
    """Draw order for an (outlined) asset: big shapes -> medium -> details, nearest neighbour within a tier."""
    hit = _ORDER.get(id(asset))
    if hit is not None:
        return hit
    areas = {i: _area(sh) for i, sh in enumerate(asset.shapes) if sh.stroke is not None}
    biggest = max(areas.values(), default=1.0) or 1.0
    tiers: List[List[Tuple[int, int]]] = [[], [], []]
    for i, a in areas.items():
        tier = 0 if a >= 0.2 * biggest else (1 if a >= 0.03 * biggest else 2)
        for j, poly in enumerate(asset.shapes[i].polylines):
            if len(poly) >= 2:
                tiers[tier].append((i, j))
    out: List[StrokeRef] = []
    pos: Optional[Point] = None
    for tier in tiers:
        left = list(tier)
        if pos is None and left:               # start with the biggest outline, at its top-left-most point
            first = max(left, key=lambda k: areas[k[0]])
            poly = asset.shapes[first[0]].polylines[first[1]]
            rev = (poly[-1][0] + poly[-1][1]) < (poly[0][0] + poly[0][1])
            out.append(StrokeRef(first[0], first[1], rev))
            pos = poly[0] if rev else poly[-1]
            left.remove(first)
        while left:
            best, best_d, best_rev = None, 1e18, False
            for k in left:
                poly = asset.shapes[k[0]].polylines[k[1]]
                d0 = (poly[0][0] - pos[0]) ** 2 + (poly[0][1] - pos[1]) ** 2
                d1 = (poly[-1][0] - pos[0]) ** 2 + (poly[-1][1] - pos[1]) ** 2
                if d0 < best_d:
                    best, best_d, best_rev = k, d0, False
                if d1 < best_d:
                    best, best_d, best_rev = k, d1, True
            poly = asset.shapes[best[0]].polylines[best[1]]
            out.append(StrokeRef(best[0], best[1], best_rev))
            pos = poly[0] if best_rev else poly[-1]
            left.remove(best)
    _ORDER[id(asset)] = out
    return out


# --------------------------------------------------------------------------- pen timing
@dataclass
class PenStroke:
    pts: List[Point]                 # world px, in drawing order
    color: RGB = INK
    width: float = 6.0               # world px
    alpha: float = 1.0
    group: int = -1                  # HandText: glyph index (filled once its contours are done)
    t0: float = 0.0
    t1: float = 0.0
    lengths: List[float] = field(default_factory=list)

    @property
    def length(self) -> float:
        return self.lengths[-1] if self.lengths else 0.0

    def prepare(self) -> None:
        acc, out = 0.0, [0.0]
        for (x0, y0), (x1, y1) in zip(self.pts, self.pts[1:]):
            acc += math.hypot(x1 - x0, y1 - y0)
            out.append(acc)
        self.lengths = out

    def frac(self, t: float) -> float:
        if t <= self.t0:
            return 0.0
        if t >= self.t1:
            return 1.0
        x = (t - self.t0) / max(1e-4, self.t1 - self.t0)
        return 0.7 * x + 0.3 * ease_in_out_sine(x)      # a hand speeds up and slows down a little

    def point_at(self, f: float) -> Point:
        if not self.pts:
            return (0.0, 0.0)
        target = f * self.length
        for i in range(1, len(self.lengths)):
            if self.lengths[i] >= target:
                seg = self.lengths[i] - self.lengths[i - 1]
                k = (target - self.lengths[i - 1]) / seg if seg else 0.0
                (x0, y0), (x1, y1) = self.pts[i - 1], self.pts[i]
                return (x0 + (x1 - x0) * k, y0 + (y1 - y0) * k)
        return self.pts[-1]

    def partial(self, f: float) -> List[Point]:
        if f >= 1.0:
            return self.pts
        target = f * self.length
        out = [self.pts[0]]
        for i in range(1, len(self.lengths)):
            if self.lengths[i] >= target:
                out.append(self.point_at(f))
                break
            out.append(self.pts[i])
        return out


def time_strokes(strokes: List[PenStroke], start: float, duration: float, lift_s: float) -> float:
    """Spread ``duration`` over the strokes (longer strokes take longer) with short pen lifts between them.

    Returns the time the last stroke ends."""
    for s in strokes:
        s.prepare()
    n = len(strokes)
    if not n:
        return start
    mean = sum(s.length for s in strokes) / n
    lifts = [lift_s + math.hypot(b.pts[0][0] - a.pts[-1][0], b.pts[0][1] - a.pts[-1][1]) / 9000
             for a, b in zip(strokes, strokes[1:])]
    lift_total = sum(lifts)
    if lift_total > 0.3 * duration:                     # many tiny details: compress the lifts
        k = 0.3 * duration / lift_total
        lifts = [x * k for x in lifts]
        lift_total *= k
    weights = [s.length + 0.25 * mean + 1.0 for s in strokes]
    per = (duration - lift_total) / sum(weights)
    t = start
    for i, s in enumerate(strokes):
        s.t0, s.t1 = t, t + weights[i] * per
        t = s.t1 + (lifts[i] if i < len(lifts) else 0.0)
    return strokes[-1].t1


def _stroke_poly(ctx: cairo.Context, pts: Sequence[Point]) -> None:
    ctx.move_to(*pts[0])
    if len(pts) == 1:
        ctx.line_to(pts[0][0] + 0.01, pts[0][1])
    for p in pts[1:]:
        ctx.line_to(*p)


# --------------------------------------------------------------------------- drawings
@dataclass
class PenDrawing(Doodle):
    """Base: a list of world-space pen strokes drawn one after the other."""
    strokes: List[PenStroke] = field(default_factory=list)
    lift_s: float = 0.07
    fill_s: float = 0.5
    by_host: bool = False            # drawn by the host character instead of the hand
    lines_end: float = 0.0

    def plan(self, start: float, duration: float) -> "PenDrawing":
        """Time the strokes so the lines take ``duration`` from ``start``; fills follow."""
        self.start = start
        self.lines_end = time_strokes(self.strokes, start, duration, self.lift_s)
        return self

    @property
    def t_first(self) -> float:
        return self.strokes[0].t0 if self.strokes else self.start

    @property
    def t_last(self) -> float:
        return self.lines_end

    @property
    def done_at(self) -> float:
        return self.lines_end + self.fill_s

    def pen(self, t: float) -> Optional[Tuple[Point, float]]:
        """(world pen point, lift 0..1) while lines are being drawn, else None."""
        if not self.strokes or t < self.t_first or t > self.t_last:
            return None
        for i, s in enumerate(self.strokes):
            if t <= s.t1:
                if t >= s.t0:
                    return s.point_at(s.frac(t)), 0.0
                prev = self.strokes[i - 1]                     # lifting between prev and s
                f = clamp((t - prev.t1) / max(1e-4, s.t0 - prev.t1))
                a, b = prev.pts[-1], s.pts[0]
                e = ease_in_out_sine(f)
                return (a[0] + (b[0] - a[0]) * e, a[1] + (b[1] - a[1]) * e), math.sin(math.pi * f)
        return self.strokes[-1].pts[-1], 0.0

    def end_point(self) -> Point:
        return self.strokes[-1].pts[-1] if self.strokes else (0.0, 0.0)

    def start_point(self) -> Point:
        return self.strokes[0].pts[0] if self.strokes else (0.0, 0.0)

    def draw_lines(self, ctx: cairo.Context, t: float) -> None:
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        for s in self.strokes:
            if t < s.t0:
                break
            f = s.frac(t)
            if f <= 0:
                continue
            _stroke_poly(ctx, s.partial(f))
            ctx.set_source_rgba(*s.color, s.alpha)
            ctx.set_line_width(s.width)
            ctx.stroke()

    def draw(self, ctx, t):
        if t < self.t_first:
            return
        self.draw_lines(ctx, t)


@dataclass
class PenPath(PenDrawing):
    """Free pen strokes: arrows, circles, underlines."""


@dataclass
class DrawnSvg(PenDrawing):
    """An SVG drawn line by line, then its colours fade in; afterwards it keeps a gentle line boil."""
    asset: Optional[SvgAsset] = None
    center: Point = (0, 0)
    height: float = 300
    outline_fills: bool = True
    boil: float = 0.0
    boil_fps: float = 6.0
    accents: Tuple[float, ...] = ()        # emphasis: a small squash-and-stretch at these times
    art: Optional[SvgAsset] = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.asset is None:
            return
        self.art = outline_asset(self.asset) if self.outline_fills else self.asset
        s, ox, oy = self.art.placement(*self.center, self.height)
        self._xf = (s, ox, oy)
        strokes = []
        for ref in stroke_order(self.art):
            sh = self.art.shapes[ref.shape]
            pts = [(ox + x * s, oy + y * s) for x, y in sh.polylines[ref.poly]]
            if ref.reverse:
                pts.reverse()
            strokes.append(PenStroke(pts=pts, color=sh.stroke[:3], alpha=sh.stroke[3], width=sh.stroke_width * s))
        self.strokes = strokes

    def current_center(self, t: float) -> Point:            # beat / camera helpers (same API as IconPop)
        return self.center

    def current_height(self, t: float) -> float:
        return self.height

    def _fills(self, ctx: cairo.Context, art: SvgAsset, a: float) -> None:
        s, ox, oy = self._xf
        ctx.save()
        ctx.translate(ox, oy)
        ctx.scale(s, s)
        for sh in art.shapes:
            if sh.fill is not None and a > 0:
                ctx.append_path(sh.cairo_path())
                ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD if sh.fill_rule == "evenodd" else cairo.FILL_RULE_WINDING)
                SvgAsset._source(ctx, sh.fill, a, None)
                ctx.fill()
            if sh.stroke is not None:
                ctx.append_path(sh.cairo_path())
                ctx.set_line_width(sh.stroke_width)
                ctx.set_line_cap(cairo.LINE_CAP_ROUND)
                ctx.set_line_join(cairo.LINE_JOIN_ROUND)
                SvgAsset._source(ctx, sh.stroke, 1.0, None)
                ctx.stroke()
        ctx.restore()

    def draw(self, ctx, t):
        if self.art is None or t < self.t_first:
            return
        if t < self.lines_end:
            self.draw_lines(ctx, t)
            return
        art = self.art
        if self.boil > 0 and t >= self.done_at:
            art = boiled(art, boil_variant(t, self.boil_fps, self.seed), self.boil)
        sx = sy = 1.0
        for at in self.accents:
            if 0 <= t - at <= 0.6:
                k = math.sin(clamp((t - at) / 0.6) * math.pi)
                sx, sy = 1 + 0.035 * k, 1 - 0.03 * k
        cx, base = self.center[0], self.center[1] + self.height / 2
        ctx.save()
        ctx.translate(cx, base)
        ctx.scale(sx, sy)
        ctx.translate(-cx, -base)
        self._fills(ctx, art, ease_out_cubic(clamp((t - self.lines_end) / max(1e-3, self.fill_s))))
        ctx.restore()


@dataclass
class HandText(PenDrawing):
    """Handwritten text: each letter is traced with the pen, then filled with ink."""
    text: str = ""
    center: Point = (0, 0)
    size: float = 90                       # world px
    font: str = "Patrick Hand"
    color: RGB = INK
    underline: Optional[RGB] = None
    glyphs: List[object] = field(default_factory=list, init=False)
    width: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 16, 16)
        c = cairo.Context(surf)
        font = bundled_font(self.font)
        if font is None:                          # not a bundled font: ask Cairo (works on Windows only)
            c.select_font_face(self.font)
            c.set_font_size(self.size)
        lines = [ln for ln in self.text.split("\n") if ln.strip()] or [""]
        lh = self.size * 1.12
        strokes: List[PenStroke] = []
        lw = max(1.5, self.size * 0.035)
        base = x0 = x1 = 0.0
        for li, line in enumerate(lines):
            lw_line = line_width(line, self.font, self.size)
            x = self.center[0] - lw_line / 2
            base = self.center[1] + self.size * 0.33 + (li - (len(lines) - 1) / 2) * lh
            self.width = max(self.width, lw_line)
            x0, x1 = x, x + lw_line
            for ch in line:
                if ch.strip():
                    contours = (font.contours(ch, x, base, self.size) if font is not None
                                else _cairo_contours(c, ch, x, base))
                    strokes += self._glyph(c, contours, lw)
                x += line_width(ch, self.font, self.size)
        if self.underline is not None and self.text.strip():
            y = base + self.size * 0.22
            pts = [(x0 + (x1 - x0) * k / 16, y + math.sin(k * 0.9 + self.seed) * self.size * 0.025)
                   for k in range(17)]
            strokes.append(PenStroke(pts=pts, color=self.underline, width=self.size * 0.075))
        self.strokes = strokes
        self.fill_s = 0.12

    def _glyph(self, c: cairo.Context, contours: List[List[Point]], lw: float) -> List[PenStroke]:
        """One letter: its contours become pen strokes, and their filled shape the ink fill."""
        c.new_path()
        for poly in contours:
            c.move_to(*poly[0])
            for q in poly[1:]:
                c.line_to(*q)
            c.close_path()
        self.glyphs.append(c.copy_path())
        c.new_path()
        g = len(self.glyphs) - 1
        return [PenStroke(pts=poly + [poly[0]], color=self.color, width=lw, group=g)
                for poly in contours if len(poly) > 1]

    def draw(self, ctx, t):
        if t < self.t_first:
            return
        self.draw_lines(ctx, t)
        done: Dict[int, float] = {}
        for s in self.strokes:
            if s.group >= 0:
                done[s.group] = max(done.get(s.group, 0.0), s.t1)
        for g, t_done in done.items():
            a = clamp((t - t_done) / self.fill_s)
            if a > 0:
                ctx.append_path(self.glyphs[g])
                ctx.set_source_rgba(*self.color, a)
                ctx.fill()


def ellipse_stroke(cx: float, cy: float, rx: float, ry: float, seed: int = 0, n: int = 48) -> List[Point]:
    """A hand-drawn loop: slightly more than a full turn, a little uneven."""
    a0 = -2.2 + 0.3 * math.sin(seed)
    out = []
    for k in range(n + 6):
        a = a0 + 2 * math.pi * k / n
        w = 1 + 0.05 * math.sin(3 * a + seed) + 0.02 * k / n
        out.append((cx + rx * w * math.cos(a), cy + ry * w * math.sin(a)))
    return out


def arrow_strokes(p0: Point, p1: Point, bend: float, head: float) -> List[List[Point]]:
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    nx, ny = -dy, dx
    mid = ((p0[0] + p1[0]) / 2 + nx * bend, (p0[1] + p1[1]) / 2 + ny * bend)
    shaft = []
    for k in range(25):
        u = k / 24
        x = (1 - u) ** 2 * p0[0] + 2 * (1 - u) * u * mid[0] + u * u * p1[0]
        y = (1 - u) ** 2 * p0[1] + 2 * (1 - u) * u * mid[1] + u * u * p1[1]
        shaft.append((x, y))
    tx, ty = p1[0] - shaft[-3][0], p1[1] - shaft[-3][1]
    L = math.hypot(tx, ty) or 1.0
    tx, ty = tx / L, ty / L
    left = (p1[0] - head * (tx * 0.9 - ty * 0.5), p1[1] - head * (ty * 0.9 + tx * 0.5))
    right = (p1[0] - head * (tx * 0.9 + ty * 0.5), p1[1] - head * (ty * 0.9 - tx * 0.5))
    return [shaft, [left, p1, right]]


# --------------------------------------------------------------------------- letter outlines
FONT_DIR = PROJECT_ROOT / "assets" / "fonts"
CURVE_STEPS = 8


def _bezier(p0: Point, p1: Point, p2: Point, p3: Point) -> List[Point]:
    out = []
    for k in range(1, CURVE_STEPS + 1):
        u = k / CURVE_STEPS
        m = 1 - u
        out.append((m ** 3 * p0[0] + 3 * m * m * u * p1[0] + 3 * m * u * u * p2[0] + u ** 3 * p3[0],
                    m ** 3 * p0[1] + 3 * m * m * u * p1[1] + 3 * m * u * u * p2[1] + u ** 3 * p3[1]))
    return out


class BundledFont:
    """Letter outlines read straight from a TTF in assets/fonts (fontTools).

    Cairo's text_path() returned empty letters on the Linux CI runner, so handwriting does not
    depend on the platform's font backend: the same outlines on Windows, Linux and macOS."""

    def __init__(self, path: Path):
        from fontTools.ttLib import TTFont
        self.font = TTFont(str(path))
        self.glyph_set = self.font.getGlyphSet()
        self.cmap = self.font.getBestCmap()
        self.upem = self.font["head"].unitsPerEm
        self.hmtx = self.font["hmtx"]
        self._cache: Dict[str, Tuple[List[List[Point]], float]] = {}

    def _units(self, ch: str) -> Tuple[List[List[Point]], float]:
        hit = self._cache.get(ch)
        if hit is not None:
            return hit
        from fontTools.pens.basePen import BasePen
        name = self.cmap.get(ord(ch)) or ".notdef"
        contours: List[List[Point]] = []

        class Pen(BasePen):
            def _moveTo(self, pt):
                contours.append([pt])

            def _lineTo(self, pt):
                contours[-1].append(pt)

            def _curveToOne(self, p1, p2, p3):
                contours[-1].extend(_bezier(contours[-1][-1], p1, p2, p3))

            def _qCurveToOne(self, p1, p2):
                p0 = contours[-1][-1]                     # quadratic -> cubic
                c1 = (p0[0] + 2 / 3 * (p1[0] - p0[0]), p0[1] + 2 / 3 * (p1[1] - p0[1]))
                c2 = (p2[0] + 2 / 3 * (p1[0] - p2[0]), p2[1] + 2 / 3 * (p1[1] - p2[1]))
                contours[-1].extend(_bezier(p0, c1, c2, p2))

        if name in self.glyph_set:
            self.glyph_set[name].draw(Pen(self.glyph_set))
        hit = ([c for c in contours if len(c) > 1], float(self.hmtx[name][0]) if name in self.hmtx.metrics else 0.0)
        self._cache[ch] = hit
        return hit

    def advance(self, ch: str, size: float) -> float:
        return self._units(ch)[1] * size / self.upem

    def contours(self, ch: str, x: float, base: float, size: float) -> List[List[Point]]:
        k = size / self.upem                             # font units -> px; font y points up
        return [[(x + px * k, base - py * k) for px, py in c] for c in self._units(ch)[0]]


@lru_cache(maxsize=8)
def bundled_font(family: str) -> Optional[BundledFont]:
    """The bundled TTF whose family name is ``family`` (case-insensitive), or None."""
    from fontTools.ttLib import TTFont
    for f in sorted(FONT_DIR.glob("*.ttf")):
        name = TTFont(str(f), lazy=True)["name"].getDebugName(1) or ""
        if name.lower() == family.lower():
            return BundledFont(f)
    return None


def line_width(text: str, family: str, size: float) -> float:
    """Advance width of ``text`` in px, from the same metrics HandText uses."""
    font = bundled_font(family)
    if font is not None:
        return sum(font.advance(ch, size) for ch in text)
    c = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 16, 16))
    c.select_font_face(family)
    c.set_font_size(size)
    return c.text_extents(text).x_advance


def _cairo_contours(c: cairo.Context, ch: str, x: float, base: float) -> List[List[Point]]:
    """Fallback for fonts that are not bundled: Cairo's own text_path()."""
    c.new_path()
    c.move_to(x, base)
    c.text_path(ch)
    out: List[List[Point]] = []
    for kind, pts in c.copy_path():
        pts = tuple(pts)
        if kind == cairo.PATH_MOVE_TO:
            out.append([(pts[0], pts[1])])
        elif kind == cairo.PATH_LINE_TO and out:
            out[-1].append((pts[0], pts[1]))
        elif kind == cairo.PATH_CURVE_TO and out:
            out[-1].extend(_bezier(out[-1][-1], pts[0:2], pts[2:4], pts[4:6]))
    c.new_path()
    return [o for o in out if len(o) > 1]


# --------------------------------------------------------------------------- the hand
@lru_cache(maxsize=1)
def hand_asset() -> SvgAsset:
    if not Path(HAND_SVG).exists():
        raise FileNotFoundError(f"drawing hand art missing: {HAND_SVG}")
    return load_svg(HAND_SVG, "marker_hand")


@dataclass
class DrawingHand(Doodle):
    """A hand holding a marker that follows the pen of ``drawings`` (in time order)."""
    drawings: List[PenDrawing] = field(default_factory=list)
    W: int = 1080
    H: int = 1920
    size: float = 450                      # on-screen height of the hand art (px)
    lift_px: float = 16
    travel_s: float = 0.4
    rest_after_s: float = 1.0
    shadow: float = 0.14
    mirror: bool = False                   # left hand: the arm comes in from the bottom-left
    z: int = 4                              # on the board: behind the host (char_z 5)

    def __post_init__(self) -> None:
        self.asset = hand_asset()
        cx, cy = 0.0, 0.0
        tip = self.asset.anchor("tip", cx, cy, self.size, flip=self.mirror)
        wrist = self.asset.anchor("wrist", cx, cy, self.size, flip=self.mirror)
        self._tip_off = tip                                   # tip relative to the art's centre
        self._wrist_off = wrist
        d = (wrist[0] - tip[0], wrist[1] - tip[1])
        L = math.hypot(*d) or 1.0
        self._dir = (d[0] / L, d[1] / L)
        # parked below the bottom corner the arm comes from
        self.rest = ((self.W * 0.22 - self.size) if self.mirror else (self.W * 0.78 + self.size),
                     self.H + self.size * 0.6)
        self.drawings = sorted([d for d in self.drawings if d.strokes and not d.by_host], key=lambda d: d.t_first)

    def tip_at(self, t: float) -> Optional[Tuple[Point, float]]:
        """(pen tip world point, lift 0..1) or None when the hand is off screen."""
        ds = self.drawings
        if not ds:
            return None
        for d in ds:
            p = d.pen(t)
            if p is not None:
                return p
        prev = next((d for d in reversed(ds) if d.t_last < t), None)
        nxt = next((d for d in ds if d.t_first > t), None)
        if prev is not None and nxt is not None and nxt.t_first - prev.t_last <= self.rest_after_s:
            gap = nxt.t_first - prev.t_last
            f = ease_in_out_sine(clamp((t - prev.t_last) / max(1e-3, gap)))
            a, b = prev.end_point(), nxt.start_point()
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f), math.sin(math.pi * f)
        if prev is not None and t - prev.t_last < self.travel_s:
            f = ease_in_out_sine((t - prev.t_last) / self.travel_s)
            a = prev.end_point()
            return (a[0] + (self.rest[0] - a[0]) * f, a[1] + (self.rest[1] - a[1]) * f), 1.0
        if nxt is not None and nxt.t_first - t < self.travel_s:
            f = ease_in_out_sine(1 - (nxt.t_first - t) / self.travel_s)
            b = nxt.start_point()
            return (self.rest[0] + (b[0] - self.rest[0]) * f, self.rest[1] + (b[1] - self.rest[1]) * f), 1.0 - f
        return None

    def draw(self, ctx, t):
        st = self.tip_at(t)
        if st is None:
            return
        (px, py), lift = st
        u = self.size / 450
        # a lifted pen comes towards the viewer: a little bigger, shifted down-right, softer shadow
        k = 1 + 0.035 * lift
        ox, oy = self.lift_px * u * 0.6 * lift * (-1 if self.mirror else 1), self.lift_px * u * lift
        cx, cy = px + ox - self._tip_off[0] * k, py + oy - self._tip_off[1] * k
        wx, wy = cx + self._wrist_off[0] * k, cy + self._wrist_off[1] * k
        far = (wx + self._dir[0] * (self.W + self.H), wy + self._dir[1] * (self.W + self.H))
        sleeve_w = self.size * 0.24 * k
        if self.shadow > 0:
            sh = (10 + 12 * lift) * u
            ctx.push_group()
            self._sleeve(ctx, (wx + sh, wy + sh * 1.4), (far[0] + sh, far[1] + sh * 1.4), sleeve_w, INK, INK)
            self.asset.draw(ctx, cx + sh, cy + sh * 1.4, self.size * k, tint=(INK, 1.0), flip=self.mirror)
            ctx.pop_group_to_source()
            ctx.paint_with_alpha(self.shadow * (1 - 0.35 * lift))
        self._sleeve(ctx, (wx, wy), far, sleeve_w, (0x2E / 255, 0xC4 / 255, 0xB6 / 255), INK)
        self.asset.draw(ctx, cx, cy, self.size * k, flip=self.mirror)

    def _sleeve(self, ctx, a: Point, b: Point, w: float, fill: RGB, ink: RGB) -> None:
        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
        ctx.move_to(*a)
        ctx.line_to(*b)
        ctx.set_source_rgb(*ink)
        ctx.set_line_width(w + self.size * 0.035)
        ctx.stroke()
        ctx.move_to(*a)
        ctx.line_to(*b)
        ctx.set_source_rgb(*fill)
        ctx.set_line_width(w)
        ctx.stroke()
