"""Line boil: the hand-drawn "wobble" of traditional animation.

Each SVG asset gets a few slightly redrawn variants: every outline and fill point is
displaced by a smooth noise field, a different one per variant. Cycling the variants
at a low frame rate (8-12 fps) makes the lines shimmer as if each frame was traced again
by hand. Because the noise depends only on position, a point shared by two shapes moves
the same way in both, so outlines and fills stay together.
"""
from __future__ import annotations

import math
import random
from dataclasses import replace
from functools import lru_cache
from typing import Dict, List, Sequence, Tuple

import cairo

from src.animation.svg_loader import Shape, SvgAsset, polyline_length

VARIANTS = 3
MAX_STEP = 6.0     # resample outlines so straight segments wobble too (viewBox units)
_CACHE: Dict[Tuple[int, int, float], SvgAsset] = {}

Point = Tuple[float, float]


def _resample(poly: Sequence[Point], step: float) -> List[Point]:
    out = [poly[0]]
    for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
        for k in range(1, n + 1):
            f = k / n
            out.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
    return out


@lru_cache(maxsize=64)
def _field(variant: int) -> Tuple[Tuple[float, float, float, float], ...]:
    """A few random sine waves: (fx, fy, phase, weight) per axis wave."""
    rnd = random.Random(9173 + variant * 31)
    waves = []
    for _ in range(4):
        ang = rnd.uniform(0, math.pi)
        k = 2 * math.pi / rnd.uniform(45, 110)          # wavelength 45-110 viewBox units
        waves.append((math.cos(ang) * k, math.sin(ang) * k, rnd.uniform(0, 2 * math.pi), rnd.uniform(0.6, 1.0)))
    return tuple(waves)


def _displace(p: Point, variant: int, amount: float) -> Point:
    w = _field(variant)
    x, y = p
    dx = sum(wt * math.sin(fx * x + fy * y + ph) for fx, fy, ph, wt in w[:2]) / 1.6
    dy = sum(wt * math.sin(fx * x + fy * y + ph) for fx, fy, ph, wt in w[2:]) / 1.6
    return x + dx * amount, y + dy * amount


def _boil_shape(sh: Shape, variant: int, amount: float, closed_eps: float) -> Shape:
    polys = [[_displace(p, variant, amount) for p in _resample(poly, MAX_STEP)] for poly in sh.polylines if poly]
    surf = cairo.ImageSurface(cairo.FORMAT_A8, 1, 1)
    c = cairo.Context(surf)
    for poly in polys:
        c.move_to(*poly[0])
        for q in poly[1:]:
            c.line_to(*q)
        if len(poly) > 2 and math.hypot(poly[0][0] - poly[-1][0], poly[0][1] - poly[-1][1]) < closed_eps:
            c.close_path()
    return replace(sh, polylines=polys, lengths=[polyline_length(p) for p in polys], _path=c.copy_path())


def boiled(asset: SvgAsset, variant: int, amount: float) -> SvgAsset:
    """The asset redrawn with boil variant ``variant`` (cached). amount is in viewBox units."""
    if amount <= 0:
        return asset
    v = variant % VARIANTS
    key = (id(asset), v, round(amount, 2))
    hit = _CACHE.get(key)
    if hit is None:
        eps = max(asset.view_w, asset.view_h) * 0.004
        hit = replace(asset, shapes=[_boil_shape(sh, v, amount, eps) for sh in asset.shapes])
        _CACHE[key] = hit
    return hit


def boil_variant(t: float, fps: float, seed: int = 0) -> int:
    """Which variant to show at time t (changes `fps` times per second)."""
    return (int(t * fps) + seed) % VARIANTS
