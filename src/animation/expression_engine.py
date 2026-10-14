"""Facial expression system: presets, blending, blinking and parametric face drawing.

Faces are drawn procedurally in head-local rig coordinates (neck joint at the origin)
so eyes, brows and mouth can move continuously (blinks, glances, lip sync) while the
head artwork itself comes from the character's SVG parts.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, fields, replace
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

import cairo

from src.animation.palette import hex_to_rgb

EXPRESSIONS_FILE = Path(__file__).resolve().parents[2] / "assets" / "expressions" / "expressions.json"
MOUTH_SHAPES = ("smile", "grin", "open", "o", "frown", "flat", "smirk", "wavy", "yawn")
EYE_SHAPES = ("normal", "arc", "wide", "closed")


@dataclass(frozen=True)
class FaceState:
    eye_open: float = 1.0
    eye_shape: str = "normal"
    pupil: float = 1.0
    brow_raise: float = 0.0
    brow_angle: float = 0.0
    brow_asym: float = 0.0
    mouth: str = "smile"
    mouth_width: float = 0.8
    blush: float = 0.25
    look_x: float = 0.0
    look_y: float = 0.0
    blink: float = 0.0          # 0 open .. 1 fully closed (applied on top of eye_open)
    mouth_open: float = 0.0     # lip-sync openness 0..1
    viseme: float = 0.5         # mouth width variation while talking 0..1
    head_turn: float = 0.0      # -1..1 shifts features for a 3/4 view


_NUMERIC = [f.name for f in fields(FaceState) if f.name not in ("eye_shape", "mouth")]


@lru_cache(maxsize=1)
def load_expressions() -> Dict[str, Dict]:
    data = json.loads(EXPRESSIONS_FILE.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def expression_names() -> Tuple[str, ...]:
    return tuple(sorted(load_expressions()))


def expression_state(name: str) -> FaceState:
    presets = load_expressions()
    if name not in presets:
        raise KeyError(f"unknown expression {name!r}; valid: {sorted(presets)}")
    return FaceState(**presets[name])


def blend(a: FaceState, b: FaceState, t: float) -> FaceState:
    t = max(0.0, min(1.0, t))
    vals = {n: getattr(a, n) + (getattr(b, n) - getattr(a, n)) * t for n in _NUMERIC}
    vals["eye_shape"] = b.eye_shape if t >= 0.5 else a.eye_shape
    vals["mouth"] = b.mouth if t >= 0.5 else a.mouth
    return FaceState(**vals)


def blink_amount(t: float, seed: int = 0) -> float:
    """Deterministic natural blinking: a 0.16 s blink every ~2.6–4.6 s."""
    rng_period = 2.6 + (seed * 0.37 % 1.0) * 2.0
    k = int(t / rng_period)
    jitter = ((k * 7919 + seed * 104729) % 1000) / 1000.0 * 0.9
    start = k * rng_period + jitter
    d = t - start
    if 0 <= d < 0.16:
        return math.sin(d / 0.16 * math.pi)
    # occasional double blink
    if (k + seed) % 5 == 0 and 0.22 <= d < 0.38:
        return math.sin((d - 0.22) / 0.16 * math.pi)
    return 0.0


# --------------------------------------------------------------------------- drawing
def _ellipse(ctx: cairo.Context, cx: float, cy: float, rx: float, ry: float) -> None:
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(max(rx, 0.01), max(ry, 0.01))
    ctx.arc(0, 0, 1, 0, 2 * math.pi)
    ctx.restore()


class FaceRenderer:
    """Draws a face for a character spec (positions & colours from character.json)."""

    def __init__(self, rig: Dict, colors: Dict[str, str]):
        self.rig = rig
        self.c = {k: hex_to_rgb(v) for k, v in colors.items()}
        self.outline = self.c.get("outline", hex_to_rgb("#2B2D42"))

    def draw(self, ctx: cairo.Context, s: FaceState) -> None:
        turn = max(-1.0, min(1.0, s.head_turn))
        ex_l, ey = self.rig["eye_l"]
        ex_r, _ = self.rig["eye_r"]
        shift = turn * 16
        self._blush(ctx, s, shift)
        for side, ex in (("l", ex_l), ("r", ex_r)):
            self._eye(ctx, ex + shift, ey, s, side)
        for side, ex in (("l", ex_l), ("r", ex_r)):
            self._brow(ctx, ex + shift, ey, s, side)
        nx, ny = self.rig["nose"]
        ctx.set_source_rgb(*self.c.get("skin_shadow", (0.9, 0.66, 0.5)))
        ctx.set_line_width(5)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.move_to(nx + turn * 24 - 7, ny - 2)
        ctx.curve_to(nx + turn * 24 - 3, ny + 6, nx + turn * 24 + 3, ny + 6, nx + turn * 24 + 7, ny - 2)
        ctx.stroke()
        mx, my = self.rig["mouth"]
        self._mouth(ctx, mx + turn * 20, my, s)

    # ------------------------------------------------------------------ parts
    def _blush(self, ctx: cairo.Context, s: FaceState, shift: float) -> None:
        if s.blush <= 0.02:
            return
        r, g, b = self.c.get("blush", (1, 0.56, 0.67))
        for cx, cy in (self.rig["cheek_l"], self.rig["cheek_r"]):
            _ellipse(ctx, cx + shift * 0.8, cy, 17, 9)
            ctx.set_source_rgba(r, g, b, 0.55 * min(1.0, s.blush))
            ctx.fill()

    def _eye(self, ctx: cairo.Context, cx: float, cy: float, s: FaceState, side: str) -> None:
        ink = self.outline
        openness = s.eye_open * (1.0 - s.blink)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        if s.eye_shape == "arc" and s.blink < 0.5:
            ctx.set_source_rgb(*ink)
            ctx.set_line_width(7)
            ctx.move_to(cx - 18, cy + 6)
            ctx.curve_to(cx - 10, cy - 16, cx + 10, cy - 16, cx + 18, cy + 6)
            ctx.stroke()
            return
        if s.eye_shape == "closed" or openness < 0.12:
            ctx.set_source_rgb(*ink)
            ctx.set_line_width(6)
            ctx.move_to(cx - 18, cy)
            ctx.curve_to(cx - 8, cy + 10, cx + 8, cy + 10, cx + 18, cy)
            ctx.stroke()
            return
        wide = 1.08 if s.eye_shape == "wide" else 1.0
        rx, ry = 23 * wide, 29 * wide * min(1.3, openness)
        # sclera
        _ellipse(ctx, cx, cy, rx, ry)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill_preserve()
        ctx.save()
        ctx.clip()
        # pupil (clipped to sclera)
        pr = 12.5 * s.pupil
        px = cx + s.look_x * 8 + s.head_turn * 3
        py = cy + s.look_y * 9 + 2
        ctx.set_source_rgb(*self.c.get("pupil", ink))
        ctx.arc(px, py, pr, 0, 2 * math.pi)
        ctx.fill()
        ctx.set_source_rgb(1, 1, 1)
        ctx.arc(px - pr * 0.35, py - pr * 0.4, pr * 0.32, 0, 2 * math.pi)
        ctx.fill()
        ctx.arc(px + pr * 0.35, py + pr * 0.35, pr * 0.14, 0, 2 * math.pi)
        ctx.fill()
        # sleepy upper lid
        if openness < 0.75:
            ctx.set_source_rgb(*self.c.get("skin", (0.97, 0.79, 0.63)))
            ctx.rectangle(cx - rx - 2, cy - ry - 2, 2 * rx + 4, ry * (0.75 - openness) * 1.6)
            ctx.fill()
        ctx.restore()
        _ellipse(ctx, cx, cy, rx, ry)
        ctx.set_source_rgb(*ink)
        ctx.set_line_width(5)
        ctx.stroke()
        if openness < 0.75:
            ctx.set_line_width(5)
            lid_y = cy - ry + ry * (0.75 - openness) * 1.6
            ctx.move_to(cx - rx, lid_y)
            ctx.line_to(cx + rx, lid_y)
            ctx.stroke()

    def _brow(self, ctx: cairo.Context, cx: float, cy: float, s: FaceState, side: str) -> None:
        raise_px = s.brow_raise * 12
        asym = s.brow_asym if side == "r" else 0.0
        by = cy - 46 - raise_px - asym * 8
        ang = s.brow_angle * (1 - 0.6 * asym)
        rot = math.radians(-ang if side == "l" else ang)
        ctx.save()
        ctx.translate(cx, by)
        ctx.rotate(rot)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.move_to(-21, 4)
        ctx.curve_to(-10, -5, 10, -5, 21, 3)
        ctx.set_source_rgb(*self.outline)
        ctx.set_line_width(14)
        ctx.stroke_preserve()
        ctx.set_source_rgb(*self.c.get("brow", (0.36, 0.23, 0.16)))
        ctx.set_line_width(8)
        ctx.stroke()
        ctx.restore()

    def _mouth(self, ctx: cairo.Context, mx: float, my: float, s: FaceState) -> None:
        ink = self.outline
        w = 46 * s.mouth_width
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        shape = s.mouth
        if s.mouth_open > 0.08 and shape not in ("o", "yawn"):
            # talking: open rounded "D" mouth whose size follows the narration envelope
            ww = w * (0.72 + 0.38 * s.viseme) * (1.05 if shape in ("grin", "smile", "open") else 0.9)
            hh = 6 + 26 * min(1.0, s.mouth_open)
            self._open_mouth(ctx, mx, my, ww, hh, smile=shape in ("smile", "grin", "open", "smirk"))
            return
        if shape == "grin":
            self._open_mouth(ctx, mx, my, w, 24, smile=True, teeth=True)
        elif shape == "open":
            self._open_mouth(ctx, mx, my, w, 26, smile=True)
        elif shape in ("o", "yawn"):
            rx, ry = (11, 15) if shape == "o" else (19, 27)
            ry += 6 * s.mouth_open
            _ellipse(ctx, mx, my + 6, rx, ry)
            ctx.set_source_rgb(*self.c.get("mouth", (0.48, 0.18, 0.23)))
            ctx.fill_preserve()
            ctx.set_source_rgb(*ink)
            ctx.set_line_width(5)
            ctx.stroke()
        else:
            ctx.set_source_rgb(*ink)
            ctx.set_line_width(6)
            h = w / 2
            if shape == "smile":
                ctx.move_to(mx - h, my - 4)
                ctx.curve_to(mx - h / 2, my + 12, mx + h / 2, my + 12, mx + h, my - 4)
            elif shape == "frown":
                ctx.move_to(mx - h, my + 8)
                ctx.curve_to(mx - h / 2, my - 8, mx + h / 2, my - 8, mx + h, my + 8)
            elif shape == "flat":
                ctx.move_to(mx - h * 0.8, my + 2)
                ctx.line_to(mx + h * 0.8, my + 2)
            elif shape == "smirk":
                ctx.move_to(mx - h, my + 2)
                ctx.curve_to(mx - h / 3, my + 9, mx + h / 3, my + 6, mx + h, my - 7)
            elif shape == "wavy":
                ctx.move_to(mx - h, my + 3)
                ctx.curve_to(mx - h / 2, my - 6, mx - h / 4, my + 9, mx, my + 2)
                ctx.curve_to(mx + h / 4, my - 5, mx + h / 2, my + 9, mx + h, my)
            ctx.stroke()

    def _open_mouth(self, ctx: cairo.Context, mx: float, my: float, w: float, h: float,
                    smile: bool = True, teeth: bool = False) -> None:
        ink = self.outline
        hw = w / 2
        top = my - 6
        ctx.new_path()
        ctx.move_to(mx - hw, top)
        if smile:
            ctx.curve_to(mx - hw / 2, top + 3, mx + hw / 2, top + 3, mx + hw, top)
        else:
            ctx.curve_to(mx - hw / 2, top - 3, mx + hw / 2, top - 3, mx + hw, top)
        ctx.curve_to(mx + hw, top + h * 0.8, mx + hw * 0.5, top + h, mx, top + h)
        ctx.curve_to(mx - hw * 0.5, top + h, mx - hw, top + h * 0.8, mx - hw, top)
        ctx.close_path()
        path = ctx.copy_path()
        ctx.set_source_rgb(*self.c.get("mouth", (0.48, 0.18, 0.23)))
        ctx.fill()
        ctx.save()
        ctx.append_path(path)
        ctx.clip()
        if teeth or h > 14:
            ctx.set_source_rgb(1, 1, 1)
            ctx.rectangle(mx - hw, top - 4, w, min(9, h * 0.32) + 4)
            ctx.fill()
        if h > 12:
            _ellipse(ctx, mx, top + h + 2, hw * 0.55, h * 0.42)
            ctx.set_source_rgb(*self.c.get("tongue", (1, 0.56, 0.67)))
            ctx.fill()
        ctx.restore()
        ctx.append_path(path)
        ctx.set_source_rgb(*ink)
        ctx.set_line_width(5)
        ctx.stroke()


def with_overrides(state: FaceState, **kw) -> FaceState:
    return replace(state, **kw)
