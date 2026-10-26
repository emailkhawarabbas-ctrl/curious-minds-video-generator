"""Lively camera: a continuous move on every scene, punch-ins on key words, optional shake.

The camera never stands still: on top of the chosen move it adds a slow hand-held sway.
Zooms pivot on the scene's subject, so a zoom-in pushes towards the visual rather than
the frame centre. All curves are eased; nothing moves linearly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cairo

from src.animation.easing import clamp, ease_in_out_sine, ease_out_back
from src.lively.style import StyleCamera

Point = Tuple[float, float]


@dataclass
class CameraState:
    scale: float = 1.0
    dx: float = 0.0
    dy: float = 0.0
    rot: float = 0.0          # radians


@dataclass
class LivelyCamera:
    move: str
    duration: float
    W: int
    H: int
    cfg: StyleCamera
    pivot: Optional[Point] = None
    punches: List[float] = field(default_factory=list)     # times of punch-ins
    shakes: List[float] = field(default_factory=list)      # times a shake starts
    seed: int = 0
    intensity: float = 1.0

    @property
    def u(self) -> float:
        return min(self.W, self.H) / 1080

    def punch_env(self, t: float) -> float:
        c = self.cfg
        best = 0.0
        for tp in self.punches:
            a = t - tp
            if a < 0 or a > c.punch_in_s + c.punch_hold_s + c.punch_out_s:
                continue
            rise = ease_out_back(clamp(a / c.punch_in_s), 1.4)
            fall = 1 - ease_in_out_sine(clamp((a - c.punch_in_s - c.punch_hold_s) / c.punch_out_s))
            best = max(best, rise * fall)
        return best

    def at(self, t: float) -> CameraState:
        c, k = self.cfg, self.intensity
        d = max(self.duration, 0.1)
        p = ease_in_out_sine(clamp(t / d))
        W, H = self.W, self.H
        s, dx, dy = c.base_zoom, 0.0, 0.0
        m = self.move
        if m == "zoom_in":
            s += c.zoom * k * p
        elif m == "zoom_out":
            s += c.zoom * k * (1 - p)
        elif m in ("pan_left", "pan_right"):
            s += 0.05
            dx = c.pan * k * W * (0.5 - p) * (1 if m == "pan_left" else -1)
        elif m in ("pan_up", "pan_down"):
            s += 0.05
            dy = c.pan * k * H * 0.6 * (0.5 - p) * (1 if m == "pan_up" else -1)
        elif m == "drift":
            s += 0.04 * k * (0.5 + 0.5 * math.sin(t * 0.7 + self.seed))
            dx = 0.022 * k * W * math.sin(t * 0.5 + self.seed)
            dy = 0.014 * k * H * math.sin(t * 0.41 + 1 + self.seed)
        # hand-held float on every move (never fully still)
        dx += 6 * self.u * math.sin(t * 0.83 + self.seed * 1.3)
        dy += 5 * self.u * math.sin(t * 0.67 + self.seed * 0.7)
        rot = math.radians(c.sway_deg) * math.sin(t * 0.45 + self.seed)
        s += c.punch * k * self.punch_env(t)
        for ts in self.shakes:
            a = t - ts
            if 0 <= a <= c.shake_s:
                amp = c.shake_px * self.u * (1 - a / c.shake_s) ** 2
                dx += amp * (math.sin(a * 63) + 0.6 * math.sin(a * 101 + 1)) / 1.6
                dy += amp * (math.cos(a * 57) + 0.6 * math.sin(a * 89 + 2)) / 1.6
                rot += math.radians(1.2) * (1 - a / c.shake_s) * math.sin(a * 41)
        return CameraState(s, dx, dy, rot)

    def apply(self, ctx: cairo.Context, t: float, depth: float = 1.0) -> None:
        """Apply the camera transform; depth < 1 moves a layer less (parallax background)."""
        st = self.at(t)
        px, py = self.pivot or (self.W / 2, self.H / 2)
        # keep the pivot reasonably central so zooms never swing the frame wildly
        px = self.W / 2 + clamp((px - self.W / 2) / (self.W / 2), -0.5, 0.5) * self.W / 2
        py = self.H / 2 + clamp((py - self.H / 2) / (self.H / 2), -0.5, 0.5) * self.H / 2
        s = 1 + (st.scale - 1) * depth
        ctx.translate(px + st.dx * depth, py + st.dy * depth)
        ctx.rotate(st.rot * depth)
        ctx.scale(s, s)
        ctx.translate(-px, -py)
