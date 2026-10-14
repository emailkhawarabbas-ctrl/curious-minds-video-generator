"""Minimal, dependency-free SVG loader that turns SVG files into Cairo display lists.

Supported subset (documented for asset authors in docs/BRAND_GUIDE.md):
  * elements: svg, g, path, circle, ellipse, rect (rx/ry), line, polyline, polygon
  * path commands: M L H V C S Q T A Z (absolute and relative)
  * transforms: translate, scale, rotate (with centre), skewX, skewY, matrix (nested)
  * presentation attributes and ``style=""``: fill, stroke, stroke-width, opacity,
    fill-opacity, stroke-opacity, stroke-linecap, stroke-linejoin, fill-rule
  * gradients are approximated by their first stop colour (flat brand style)
  * anchors: any element with ``id="anchor-NAME"`` is not drawn; its centre is
    recorded as a named anchor point used for labels / arrows / IK targets.
  * metadata: root ``data-title``, ``data-tags`` (comma separated), ``data-license``.

All transforms are baked into the geometry at load time, so drawing is a straight
replay of pre-built ``cairo.Path`` objects (fast enough for per-frame rendering).
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cairo

Matrix = Tuple[float, float, float, float, float, float]  # a b c d e f (SVG order)
RGBA = Tuple[float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_NAMED = {
    "none": None, "transparent": None, "black": "#000000", "white": "#ffffff", "red": "#ff0000",
    "green": "#008000", "blue": "#0000ff", "yellow": "#ffff00", "orange": "#ffa500",
    "gray": "#808080", "grey": "#808080", "pink": "#ffc0cb", "purple": "#800080",
}


class SvgError(ValueError):
    pass


# --------------------------------------------------------------------------- matrices
def mat_mul(m1: Matrix, m2: Matrix) -> Matrix:
    """Return m1 * m2 (apply m2 first, then m1)."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2,
            b1 * c2 + d1 * d2, a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def mat_apply(m: Matrix, x: float, y: float) -> Tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def parse_transform(text: Optional[str]) -> Matrix:
    m = IDENTITY
    if not text:
        return m
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", text):
        v = [float(x) for x in _NUM_RE.findall(args)]
        if name == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale":
            sx = v[0]
            sy = v[1] if len(v) > 1 else sx
            t = (sx, 0, 0, sy, 0, 0)
        elif name == "rotate":
            r = math.radians(v[0])
            cs, sn = math.cos(r), math.sin(r)
            t = (cs, sn, -sn, cs, 0, 0)
            if len(v) == 3:
                cx, cy = v[1], v[2]
                t = mat_mul(mat_mul((1, 0, 0, 1, cx, cy), t), (1, 0, 0, 1, -cx, -cy))
        elif name == "skewX":
            t = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewY":
            t = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        elif name == "matrix" and len(v) == 6:
            t = tuple(v)  # type: ignore[assignment]
        else:
            raise SvgError(f"unsupported transform {name}({args})")
        m = mat_mul(m, t)  # type: ignore[arg-type]
    return m


# --------------------------------------------------------------------------- colours
def parse_color(value: Optional[str]) -> Optional[Tuple[float, float, float]]:
    if value is None:
        return None
    v = value.strip().lower()
    if v in _NAMED:
        v = _NAMED[v]
        if v is None:
            return None
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) != 6:
            raise SvgError(f"bad colour {value}")
        return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)
    if v.startswith("rgb"):
        nums = [float(x) for x in _NUM_RE.findall(v)]
        return (nums[0] / 255, nums[1] / 255, nums[2] / 255)
    raise SvgError(f"unsupported colour {value}")


# --------------------------------------------------------------------------- path parsing
Segment = Tuple  # ('M', x, y) | ('L', x, y) | ('C', x1, y1, x2, y2, x, y) | ('Z',)


class _Tok:
    def __init__(self, d: str):
        self.d = d
        self.i = 0

    def _skip(self) -> None:
        while self.i < len(self.d) and self.d[self.i] in " \t\r\n,":
            self.i += 1

    def at_number(self) -> bool:
        self._skip()
        return self.i < len(self.d) and (self.d[self.i].isdigit() or self.d[self.i] in "+-.")

    def command(self) -> Optional[str]:
        self._skip()
        if self.i < len(self.d) and self.d[self.i].isalpha():
            c = self.d[self.i]
            self.i += 1
            return c
        return None

    def number(self) -> float:
        self._skip()
        m = _NUM_RE.match(self.d, self.i)
        if not m:
            raise SvgError(f"expected number at {self.i} in path: {self.d[self.i:self.i + 20]!r}")
        self.i = m.end()
        return float(m.group())

    def flag(self) -> int:
        self._skip()
        ch = self.d[self.i]
        if ch not in "01":
            raise SvgError("bad arc flag")
        self.i += 1
        return int(ch)

    def done(self) -> bool:
        self._skip()
        return self.i >= len(self.d)


def _arc_to_beziers(x1, y1, rx, ry, phi_deg, fa, fs, x2, y2) -> List[Segment]:
    """SVG elliptical arc (endpoint parameterisation) -> cubic bezier segments."""
    if rx == 0 or ry == 0:
        return [("L", x2, y2)]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = (x1p ** 2) / rx ** 2 + (y1p ** 2) / ry ** 2
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    den = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if fa == fs:
        coef = -coef
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    th1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not fs and dth > 0:
        dth -= 2 * math.pi
    elif fs and dth < 0:
        dth += 2 * math.pi
    n = max(1, int(math.ceil(abs(dth) / (math.pi / 2) - 1e-9)))
    delta = dth / n
    t = 4 / 3 * math.tan(delta / 4)
    segs: List[Segment] = []
    a0 = th1
    for _ in range(n):
        a1 = a0 + delta
        c0, s0, c1, s1 = math.cos(a0), math.sin(a0), math.cos(a1), math.sin(a1)
        p1 = (c0 - t * s0, s0 + t * c0)
        p2 = (c1 + t * s1, s1 - t * c1)
        p3 = (c1, s1)
        pts = []
        for px, py in (p1, p2, p3):
            ex, ey = px * rx, py * ry
            pts += [cp * ex - sp * ey + cx, sp * ex + cp * ey + cy]
        segs.append(("C", *pts))
        a0 = a1
    return segs


def parse_path_d(d: str) -> List[Segment]:
    tok = _Tok(d)
    segs: List[Segment] = []
    cx = cy = sx = sy = 0.0
    last_c2: Optional[Tuple[float, float]] = None
    last_q: Optional[Tuple[float, float]] = None
    cmd: Optional[str] = None
    while not tok.done():
        c = tok.command()
        if c is not None:
            cmd = c
        elif cmd is None:
            raise SvgError("path must start with a command")
        assert cmd is not None
        rel = cmd.islower()
        C = cmd.upper()
        ox, oy = (cx, cy) if rel else (0.0, 0.0)
        if C == "Z":
            segs.append(("Z",))
            cx, cy = sx, sy
            last_c2 = last_q = None
            cmd = None if not tok.at_number() else cmd
            continue
        if C == "M":
            x, y = tok.number() + ox, tok.number() + oy
            segs.append(("M", x, y))
            cx, cy = sx, sy = x, y
            cmd = "l" if rel else "L"  # subsequent pairs are implicit lineto
            last_c2 = last_q = None
        elif C == "L":
            x, y = tok.number() + ox, tok.number() + oy
            segs.append(("L", x, y))
            cx, cy = x, y
            last_c2 = last_q = None
        elif C == "H":
            x = tok.number() + ox
            segs.append(("L", x, cy))
            cx = x
            last_c2 = last_q = None
        elif C == "V":
            y = tok.number() + oy
            segs.append(("L", cx, y))
            cy = y
            last_c2 = last_q = None
        elif C == "C":
            x1, y1 = tok.number() + ox, tok.number() + oy
            x2, y2 = tok.number() + ox, tok.number() + oy
            x, y = tok.number() + ox, tok.number() + oy
            segs.append(("C", x1, y1, x2, y2, x, y))
            last_c2, last_q = (x2, y2), None
            cx, cy = x, y
        elif C == "S":
            x1, y1 = (2 * cx - last_c2[0], 2 * cy - last_c2[1]) if last_c2 else (cx, cy)
            x2, y2 = tok.number() + ox, tok.number() + oy
            x, y = tok.number() + ox, tok.number() + oy
            segs.append(("C", x1, y1, x2, y2, x, y))
            last_c2, last_q = (x2, y2), None
            cx, cy = x, y
        elif C in ("Q", "T"):
            if C == "Q":
                qx, qy = tok.number() + ox, tok.number() + oy
            else:
                qx, qy = (2 * cx - last_q[0], 2 * cy - last_q[1]) if last_q else (cx, cy)
            x, y = tok.number() + ox, tok.number() + oy
            segs.append(("C", cx + 2 / 3 * (qx - cx), cy + 2 / 3 * (qy - cy),
                         x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y), x, y))
            last_q, last_c2 = (qx, qy), None
            cx, cy = x, y
        elif C == "A":
            rx, ry, rot = tok.number(), tok.number(), tok.number()
            fa, fs = tok.flag(), tok.flag()
            x, y = tok.number() + ox, tok.number() + oy
            segs.extend(_arc_to_beziers(cx, cy, rx, ry, rot, fa, fs, x, y))
            cx, cy = x, y
            last_c2 = last_q = None
        else:
            raise SvgError(f"unsupported path command {cmd}")
    return segs


def _ellipse_segments(cx: float, cy: float, rx: float, ry: float) -> List[Segment]:
    k = 0.5522847498
    return [("M", cx + rx, cy),
            ("C", cx + rx, cy + k * ry, cx + k * rx, cy + ry, cx, cy + ry),
            ("C", cx - k * rx, cy + ry, cx - rx, cy + k * ry, cx - rx, cy),
            ("C", cx - rx, cy - k * ry, cx - k * rx, cy - ry, cx, cy - ry),
            ("C", cx + k * rx, cy - ry, cx + rx, cy - k * ry, cx + rx, cy), ("Z",)]


def _rect_segments(x: float, y: float, w: float, h: float, rx: float, ry: float) -> List[Segment]:
    if rx <= 0 and ry <= 0:
        return [("M", x, y), ("L", x + w, y), ("L", x + w, y + h), ("L", x, y + h), ("Z",)]
    rx = min(rx or ry, w / 2)
    ry = min(ry or rx, h / 2)
    k = 0.5522847498
    return [("M", x + rx, y), ("L", x + w - rx, y),
            ("C", x + w - rx + k * rx, y, x + w, y + ry - k * ry, x + w, y + ry),
            ("L", x + w, y + h - ry),
            ("C", x + w, y + h - ry + k * ry, x + w - rx + k * rx, y + h, x + w - rx, y + h),
            ("L", x + rx, y + h),
            ("C", x + rx - k * rx, y + h, x, y + h - ry + k * ry, x, y + h - ry),
            ("L", x, y + ry),
            ("C", x, y + ry - k * ry, x + rx - k * rx, y, x + rx, y), ("Z",)]


def transform_segments(segs: Sequence[Segment], m: Matrix) -> List[Segment]:
    out: List[Segment] = []
    for s in segs:
        if s[0] == "Z":
            out.append(s)
        elif s[0] in ("M", "L"):
            out.append((s[0], *mat_apply(m, s[1], s[2])))
        else:
            p1 = mat_apply(m, s[1], s[2])
            p2 = mat_apply(m, s[3], s[4])
            p3 = mat_apply(m, s[5], s[6])
            out.append(("C", *p1, *p2, *p3))
    return out


def flatten_segments(segs: Sequence[Segment], steps: int = 12) -> List[List[Tuple[float, float]]]:
    """Polyline approximation per sub-path (closed sub-paths repeat their first point)."""
    polys: List[List[Tuple[float, float]]] = []
    cur: List[Tuple[float, float]] = []
    start = (0.0, 0.0)
    for s in segs:
        if s[0] == "M":
            if len(cur) > 1:
                polys.append(cur)
            cur = [(s[1], s[2])]
            start = (s[1], s[2])
        elif s[0] == "L":
            cur.append((s[1], s[2]))
        elif s[0] == "C":
            x0, y0 = cur[-1] if cur else start
            for i in range(1, steps + 1):
                t = i / steps
                mt = 1 - t
                x = mt ** 3 * x0 + 3 * mt * mt * t * s[1] + 3 * mt * t * t * s[3] + t ** 3 * s[5]
                y = mt ** 3 * y0 + 3 * mt * mt * t * s[2] + 3 * mt * t * t * s[4] + t ** 3 * s[6]
                cur.append((x, y))
        elif s[0] == "Z":
            if cur:
                cur.append(start)
                polys.append(cur)
            cur = [start]
    if len(cur) > 1:
        polys.append(cur)
    return polys


def polyline_length(poly: Sequence[Tuple[float, float]]) -> float:
    return sum(math.hypot(poly[i + 1][0] - poly[i][0], poly[i + 1][1] - poly[i][1])
               for i in range(len(poly) - 1))


def segments_to_cairo(ctx: cairo.Context, segs: Sequence[Segment]) -> None:
    for s in segs:
        if s[0] == "M":
            ctx.move_to(s[1], s[2])
        elif s[0] == "L":
            ctx.line_to(s[1], s[2])
        elif s[0] == "C":
            ctx.curve_to(*s[1:])
        elif s[0] == "Z":
            ctx.close_path()


def draw_partial_polylines(ctx: cairo.Context, polys: Sequence[Sequence[Tuple[float, float]]],
                           lengths: Sequence[float], amount: float) -> None:
    """Append the first `amount` (absolute length) of a list of polylines to ctx's path."""
    remaining = amount
    for poly, plen in zip(polys, lengths):
        if remaining <= 0:
            break
        ctx.move_to(*poly[0])
        if remaining >= plen:
            for p in poly[1:]:
                ctx.line_to(*p)
            remaining -= plen
            continue
        for i in range(len(poly) - 1):
            (x0, y0), (x1, y1) = poly[i], poly[i + 1]
            seg = math.hypot(x1 - x0, y1 - y0)
            if remaining >= seg:
                ctx.line_to(x1, y1)
                remaining -= seg
            else:
                f = remaining / seg if seg else 0
                ctx.line_to(x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)
                remaining = 0
                break


# --------------------------------------------------------------------------- shapes
@dataclass
class Shape:
    segments: List[Segment]
    fill: Optional[RGBA]
    stroke: Optional[RGBA]
    stroke_width: float
    linecap: str = "round"
    linejoin: str = "round"
    fill_rule: str = "nonzero"
    groups: Tuple[str, ...] = ()
    polylines: List[List[Tuple[float, float]]] = field(default_factory=list)
    lengths: List[float] = field(default_factory=list)
    _path: Optional[object] = None

    @property
    def length(self) -> float:
        return sum(self.lengths)

    def prepare(self) -> None:
        self.polylines = flatten_segments(self.segments)
        self.lengths = [polyline_length(p) for p in self.polylines]

    def cairo_path(self) -> object:
        if self._path is None:
            surf = cairo.ImageSurface(cairo.FORMAT_A8, 1, 1)
            c = cairo.Context(surf)
            segments_to_cairo(c, self.segments)
            self._path = c.copy_path()
        return self._path


_CAPS = {"butt": cairo.LINE_CAP_BUTT, "round": cairo.LINE_CAP_ROUND, "square": cairo.LINE_CAP_SQUARE}
_JOINS = {"miter": cairo.LINE_JOIN_MITER, "round": cairo.LINE_JOIN_ROUND, "bevel": cairo.LINE_JOIN_BEVEL}


@dataclass
class SvgAsset:
    asset_id: str
    path: Optional[Path]
    view_x: float
    view_y: float
    view_w: float
    view_h: float
    shapes: List[Shape]
    anchors: Dict[str, Tuple[float, float]]
    title: str = ""
    tags: Tuple[str, ...] = ()
    license: str = "Original Curious Minds artwork (owned, CC0 for project use)"

    @property
    def aspect(self) -> float:
        return self.view_w / self.view_h

    @property
    def total_length(self) -> float:
        return sum(s.length for s in self.shapes if s.stroke)

    # -------------------------------------------------------------- geometry helpers
    def placement(self, cx: float, cy: float, height: float) -> Tuple[float, float, float]:
        """Return (scale, origin_x, origin_y) so the viewBox centre lands on (cx, cy)."""
        s = height / self.view_h
        ox = cx - (self.view_x + self.view_w / 2) * s
        oy = cy - (self.view_y + self.view_h / 2) * s
        return s, ox, oy

    def anchor(self, name: str, cx: float, cy: float, height: float,
               rotation: float = 0.0, flip: bool = False) -> Tuple[float, float]:
        """World position of a named anchor for an asset drawn with draw(cx, cy, height)."""
        if name not in self.anchors:
            raise KeyError(f"asset {self.asset_id} has no anchor {name!r}; has {sorted(self.anchors)}")
        ax, ay = self.anchors[name]
        s = height / self.view_h
        lx = (ax - (self.view_x + self.view_w / 2)) * s
        ly = (ay - (self.view_y + self.view_h / 2)) * s
        if flip:
            lx = -lx
        r = math.radians(rotation)
        return (cx + lx * math.cos(r) - ly * math.sin(r), cy + lx * math.sin(r) + ly * math.cos(r))

    # -------------------------------------------------------------- drawing
    def draw(self, ctx: cairo.Context, cx: float, cy: float, height: float,
             rotation: float = 0.0, alpha: float = 1.0, flip: bool = False,
             draw_progress: float = 1.0, only_groups: Optional[Sequence[str]] = None,
             tint: Optional[Tuple[Tuple[float, float, float], float]] = None,
             stroke_scale: float = 1.0) -> None:
        """Draw the asset centred at (cx, cy) with the given on-screen height.

        draw_progress < 1 produces the hand-drawn reveal: outlines are traced in
        document order, then fills fade in.
        """
        if alpha <= 0.001 or height <= 0.5:
            return
        s = height / self.view_h
        ctx.save()
        ctx.translate(cx, cy)
        if rotation:
            ctx.rotate(math.radians(rotation))
        ctx.scale(-s if flip else s, s)
        ctx.translate(-(self.view_x + self.view_w / 2), -(self.view_y + self.view_h / 2))
        p = max(0.0, min(1.0, draw_progress))
        shapes = self.shapes if not only_groups else [
            sh for sh in self.shapes if set(sh.groups) & set(only_groups)]
        if p >= 0.999:
            for sh in shapes:
                self._draw_shape(ctx, sh, alpha, tint, stroke_scale)
        else:
            line_p = min(1.0, p / 0.7)
            fill_a = max(0.0, (p - 0.45) / 0.55)
            total = sum(sh.length for sh in shapes if sh.stroke) or 1.0
            budget = total * line_p
            for sh in shapes:
                if sh.fill and fill_a > 0:
                    ctx.append_path(sh.cairo_path())
                    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD if sh.fill_rule == "evenodd"
                                      else cairo.FILL_RULE_WINDING)
                    self._source(ctx, sh.fill, alpha * fill_a, tint)
                    ctx.fill()
            for sh in shapes:
                if not sh.stroke or budget <= 0:
                    continue
                draw_partial_polylines(ctx, sh.polylines, sh.lengths, budget)
                budget -= sh.length
                ctx.set_line_width(sh.stroke_width * stroke_scale)
                ctx.set_line_cap(cairo.LINE_CAP_ROUND)
                ctx.set_line_join(cairo.LINE_JOIN_ROUND)
                self._source(ctx, sh.stroke, alpha, tint)
                ctx.stroke()
        ctx.restore()

    def draw_native(self, ctx: cairo.Context, only_groups: Optional[Sequence[str]] = None,
                    alpha: float = 1.0) -> None:
        """Draw in the SVG's own user coordinates (used by rig parts authored in rig space)."""
        for sh in self.shapes:
            if only_groups and not (set(sh.groups) & set(only_groups)):
                continue
            self._draw_shape(ctx, sh, alpha, None, 1.0)

    @staticmethod
    def _source(ctx: cairo.Context, rgba: RGBA, alpha: float, tint) -> None:
        r, g, b, a = rgba
        if tint:
            (tr, tg, tb), amt = tint
            r, g, b = r + (tr - r) * amt, g + (tg - g) * amt, b + (tb - b) * amt
        ctx.set_source_rgba(r, g, b, a * alpha)

    def _draw_shape(self, ctx: cairo.Context, sh: Shape, alpha: float, tint, stroke_scale: float) -> None:
        ctx.append_path(sh.cairo_path())
        if sh.fill:
            ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD if sh.fill_rule == "evenodd"
                              else cairo.FILL_RULE_WINDING)
            self._source(ctx, sh.fill, alpha, tint)
            if sh.stroke:
                ctx.fill_preserve()
            else:
                ctx.fill()
        if sh.stroke:
            ctx.set_line_width(sh.stroke_width * stroke_scale)
            ctx.set_line_cap(_CAPS.get(sh.linecap, cairo.LINE_CAP_ROUND))
            ctx.set_line_join(_JOINS.get(sh.linejoin, cairo.LINE_JOIN_ROUND))
            self._source(ctx, sh.stroke, alpha, tint)
            ctx.stroke()
        else:
            ctx.new_path()


# --------------------------------------------------------------------------- loader
def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _style_dict(el: ET.Element) -> Dict[str, str]:
    d = {k: v for k, v in el.attrib.items()}
    style = el.attrib.get("style")
    if style:
        for part in style.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                d[k.strip()] = v.strip()
    return d


_INHERITED = ("fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin",
              "fill-rule", "fill-opacity", "stroke-opacity")


def load_svg_string(text: str, asset_id: str = "inline", path: Optional[Path] = None) -> SvgAsset:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SvgError(f"{asset_id}: invalid XML: {exc}") from exc
    if _strip_ns(root.tag) != "svg":
        raise SvgError(f"{asset_id}: root element must be <svg>")
    vb = root.attrib.get("viewBox")
    if vb:
        vx, vy, vw, vh = [float(x) for x in _NUM_RE.findall(vb)]
    else:
        vx, vy = 0.0, 0.0
        vw = float(_NUM_RE.findall(root.attrib.get("width", "100"))[0])
        vh = float(_NUM_RE.findall(root.attrib.get("height", "100"))[0])

    gradients: Dict[str, str] = {}
    for el in root.iter():
        if _strip_ns(el.tag) in ("linearGradient", "radialGradient"):
            stops = [s for s in el if _strip_ns(s.tag) == "stop"]
            if stops:
                st = _style_dict(stops[0])
                gradients[el.attrib.get("id", "")] = st.get("stop-color", "#000000")

    shapes: List[Shape] = []
    anchors: Dict[str, Tuple[float, float]] = {}

    def resolve_paint(v: Optional[str]) -> Optional[str]:
        if v and v.startswith("url("):
            gid = v[v.find("#") + 1: v.find(")")]
            return gradients.get(gid, "#000000")
        return v

    def walk(el: ET.Element, m: Matrix, inherited: Dict[str, str], opacity: float,
             groups: Tuple[str, ...]) -> None:
        tag = _strip_ns(el.tag)
        if tag in ("defs", "metadata", "title", "desc", "linearGradient", "radialGradient",
                   "style", "clipPath", "mask"):
            return
        st = _style_dict(el)
        m2 = mat_mul(m, parse_transform(st.get("transform")))
        inh = dict(inherited)
        for k in _INHERITED:
            if k in st:
                inh[k] = st[k]
        op = opacity * float(st.get("opacity", 1.0))
        el_id = st.get("id", "")
        if el_id.startswith("anchor-"):
            segs = _element_segments(tag, st)
            if segs:
                pts = [p for poly in flatten_segments(transform_segments(segs, m2)) for p in poly]
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                anchors[el_id[7:]] = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
            elif tag == "g":
                pass
            return
        grp = groups + ((el_id[5:],) if el_id.startswith("part-") else ())
        if tag in ("svg", "g"):
            for child in el:
                walk(child, m2, inh, op, grp)
            return
        segs = _element_segments(tag, st)
        if not segs:
            return
        fill_v = resolve_paint(inh.get("fill", "#000000" if tag not in ("line", "polyline") else "none"))
        stroke_v = resolve_paint(inh.get("stroke", "none"))
        fill_rgb, stroke_rgb = parse_color(fill_v), parse_color(stroke_v)
        fo = float(inh.get("fill-opacity", 1.0)) * op
        so = float(inh.get("stroke-opacity", 1.0)) * op
        sw = float(_NUM_RE.findall(inh.get("stroke-width", "1"))[0])
        det = abs(m2[0] * m2[3] - m2[1] * m2[2])
        sh = Shape(
            segments=transform_segments(segs, m2),
            fill=(*fill_rgb, fo) if fill_rgb else None,
            stroke=(*stroke_rgb, so) if stroke_rgb and sw > 0 else None,
            stroke_width=sw * math.sqrt(det),
            linecap=inh.get("stroke-linecap", "round"),
            linejoin=inh.get("stroke-linejoin", "round"),
            fill_rule=inh.get("fill-rule", "nonzero"),
            groups=grp,
        )
        sh.prepare()
        shapes.append(sh)

    walk(root, IDENTITY, {}, 1.0, ())
    tags = tuple(t.strip().lower() for t in root.attrib.get("data-tags", "").split(",") if t.strip())
    asset = SvgAsset(asset_id=asset_id, path=path, view_x=vx, view_y=vy, view_w=vw, view_h=vh,
                     shapes=shapes, anchors=anchors, title=root.attrib.get("data-title", asset_id),
                     tags=tags)
    if root.attrib.get("data-license"):
        asset.license = root.attrib["data-license"]
    if not shapes:
        raise SvgError(f"{asset_id}: no drawable shapes")
    return asset


def _f(st: Dict[str, str], k: str, default: float = 0.0) -> float:
    v = st.get(k)
    if v is None:
        return default
    nums = _NUM_RE.findall(v)
    return float(nums[0]) if nums else default


def _element_segments(tag: str, st: Dict[str, str]) -> List[Segment]:
    if tag == "path":
        d = st.get("d", "")
        return parse_path_d(d) if d.strip() else []
    if tag == "circle":
        r = _f(st, "r")
        return _ellipse_segments(_f(st, "cx"), _f(st, "cy"), r, r) if r > 0 else []
    if tag == "ellipse":
        return _ellipse_segments(_f(st, "cx"), _f(st, "cy"), _f(st, "rx"), _f(st, "ry"))
    if tag == "rect":
        return _rect_segments(_f(st, "x"), _f(st, "y"), _f(st, "width"), _f(st, "height"),
                              _f(st, "rx"), _f(st, "ry"))
    if tag == "line":
        return [("M", _f(st, "x1"), _f(st, "y1")), ("L", _f(st, "x2"), _f(st, "y2"))]
    if tag in ("polyline", "polygon"):
        nums = [float(x) for x in _NUM_RE.findall(st.get("points", ""))]
        pts = list(zip(nums[0::2], nums[1::2]))
        if len(pts) < 2:
            return []
        segs: List[Segment] = [("M", *pts[0])] + [("L", *p) for p in pts[1:]]
        if tag == "polygon":
            segs.append(("Z",))
        return segs
    return []


def load_svg(path: Path, asset_id: Optional[str] = None) -> SvgAsset:
    path = Path(path)
    return load_svg_string(path.read_text(encoding="utf-8"), asset_id or path.stem, path)
