"""Scene composition: turns a validated storyboard Scene into animated layers.

Each layout template is plain code (never LLM-generated) that arranges assets,
doodles, text and the mascot for the active orientation, keeping everything inside the
platform-safe stage and out of the caption band. Element timings are synchronised to
the narration: items / labels / nodes appear when their cue word is spoken.

``compose_scene`` returns a :class:`SceneComposition` whose ``draw(ctx, t)`` renders
background + camera + doodles + character for scene-relative time ``t``. Captions
and transitions are layered on top by the renderer.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cairo

from src.animation.asset_manager import AssetManager, get_asset_manager
from src.animation.backgrounds import Background
from src.animation.character_engine import CharacterAnimator, CharacterCue
from src.animation.character_rig import Placement, Skeleton
from src.animation.demos import Demo, make_demo
from src.animation.doodle_engine import (Arrow, BarChart, Burst, CircleHighlight, Counter, Doodle, IconPop, Label,
                                         LineChart, MarkerHighlight, MorphShape, Particles, Pathway, PopText,
                                         Sparkle, SpeechBubble, StarDoodle, WaveLine, rounded_rect)
from src.animation.easing import clamp, ease_in_out_sine, ease_out_back, ease_out_cubic, progress
from src.animation.palette import ACCENTS, PALETTE, lighten
from src.animation.themes import THEMES
from src.animation.text_render import TextStyle, draw_lines, fit_size
from src.content.models import ObjectSpec, Scene
from src.utils.fonts import CAPTION_FONT, HAND_FONT, TITLE_FONT

Point = Tuple[float, float]


# --------------------------------------------------------------------------- context
@dataclass
class WordTiming:
    word: str
    start: float
    end: float


@dataclass
class LayoutContext:
    W: int
    H: int
    vertical: bool
    safe_top: float
    safe_bottom: float
    safe_left: float
    safe_right: float
    caption_top: float
    caption_bottom: float
    duration: float
    words: List[WordTiming] = field(default_factory=list)
    speech_start: float = 0.3
    speech_end: float = 0.0
    seed: int = 0
    assets: AssetManager = field(default_factory=get_asset_manager)
    brand_name: str = "CURIOUS MINDS"
    tagline: str = "Understand the world in a fun way."

    @property
    def u(self) -> float:
        return min(self.W, self.H) / 1080.0

    @property
    def stage(self) -> Tuple[float, float, float, float]:
        """x0, y0, x1, y1 of the safe stage above the caption band."""
        return (self.safe_left, self.safe_top + 10 * self.u, self.W - self.safe_right,
                self.caption_top - 14 * self.u)

    def sx(self, f: float) -> float:
        x0, _, x1, _ = self.stage
        return x0 + (x1 - x0) * f

    def sy(self, f: float) -> float:
        _, y0, _, y1 = self.stage
        return y0 + (y1 - y0) * f

    @property
    def sw(self) -> float:
        return self.stage[2] - self.stage[0]

    @property
    def sh(self) -> float:
        return self.stage[3] - self.stage[1]

    @property
    def ground_y(self) -> float:
        return self.stage[3]

    def char_height(self, small: bool = False) -> float:
        base = self.sh * (0.6 if self.vertical else 0.74)
        return base * (0.72 if small else 1.0)

    # ------------------------------------------------------------- narration sync
    def cue_time(self, cue: Optional[str], default: float) -> float:
        if not cue or not self.words:
            return default
        target = [w for w in re.findall(r"[a-z0-9']+", cue.lower())]
        if not target:
            return default
        toks = [re.sub(r"[^a-z0-9']", "", w.word.lower()) for w in self.words]
        n = len(target)
        for i in range(len(toks) - n + 1):
            if all(toks[i + k].startswith(target[k]) for k in range(n)):
                return max(0.0, self.words[i].start - 0.12)
        return default

    def spread(self, i: int, n: int, lo: float = 0.12, hi: float = 0.72) -> float:
        """Evenly spread i-th of n reveals across the spoken part of the scene."""
        a = self.speech_start + (self.speech_end - self.speech_start) * lo
        b = self.speech_start + (self.speech_end - self.speech_start) * hi
        return a + (b - a) * (i / max(1, n - 1)) if n > 1 else a


@dataclass
class SceneComposition:
    ctx_info: LayoutContext
    background: Background
    elements: List[Doodle]
    character: Optional[CharacterAnimator]
    char_z: int = 5
    camera_move: str = "drift"
    camera_intensity: float = 0.5
    events: List[Tuple[float, str]] = field(default_factory=list)   # auto sound effects (time, sfx)
    post: List[Callable[[cairo.Context, float], None]] = field(default_factory=list)
    focus_keys: List[Tuple[float, Point]] = field(default_factory=list)   # (time, point) the camera visits
    focus_fn: Optional[Callable[[float], Point]] = None                   # live focus (demonstrations)
    foreground: Optional["_Foreground"] = None
    parallax: float = 0.4                                                 # background follows 40 % of the camera

    def _glide(self, t: float) -> Optional[Point]:
        """Smoothed point of interest at time t: glides between focus keys / follows a demo."""
        if self.focus_fn is not None:
            pts = [self.focus_fn(max(0.0, t - k * 0.15)) for k in range(6)]
            return sum(q[0] for q in pts) / 6, sum(q[1] for q in pts) / 6
        keys = sorted(self.focus_keys)
        if not keys:
            return None
        if t <= keys[0][0]:
            return keys[0][1]
        for (t0, p0), (t1, p1) in zip(keys, keys[1:]):
            if t0 <= t < t1:
                f = ease_in_out_sine(clamp((t - t0) / 0.9))
                return p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f
        return keys[-1][1]

    def camera(self, t: float) -> Tuple[float, float, float]:
        d = self.ctx_info.duration
        k = self.camera_intensity
        u = self.ctx_info.u
        m = self.camera_move
        p = ease_in_out_sine(clamp(t / max(d, 0.1)))
        s, dx, dy = 1.0, 0.0, 0.0
        W, H = self.ctx_info.W, self.ctx_info.H
        if m in ("focus", "follow", "reveal"):
            fp = self._glide(t)
            if fp is None:
                m = "drift"
            else:
                if m == "reveal":
                    pull = ease_in_out_sine(clamp(t / max(1.0, d * 0.65)))
                    s = 1.0 + 0.16 * k * (1 - pull) + 0.02 * k
                    a = 0.45 * (1 - pull) + 0.12
                else:
                    s = 1.0 + (0.06 if m == "focus" else 0.05) * k + 0.015 * math.sin(t * 0.4)
                    a = 0.28 if m == "focus" else 0.36
                # move the point of interest toward the frame centre (point q maps to C + d + s(q - C))
                dx = (fp[0] - W / 2) * (1 - a - s)
                dy = (fp[1] - H / 2) * (1 - a - s)
                lim_x, lim_y = W * 0.09 * s, H * 0.07 * s
                return s, clamp(dx, -lim_x, lim_x), clamp(dy, -lim_y, lim_y)
        if m == "zoom_in":
            s = 1.0 + 0.07 * k * p
        elif m == "zoom_out":
            s = 1.0 + 0.07 * k * (1 - p)
        elif m == "pan_left":
            s, dx = 1.06, 40 * u * k * (0.5 - p) * 2
        elif m == "pan_right":
            s, dx = 1.06, -40 * u * k * (0.5 - p) * 2
        elif m == "drift":
            s = 1.02 + 0.015 * k * math.sin(t * 0.35)
            dx, dy = 12 * u * k * math.sin(t * 0.27), 8 * u * k * math.sin(t * 0.31 + 1)
        elif m == "punch_in":
            s = 1.0 + 0.08 * k * ease_out_back(clamp(t / 0.6)) - 0.03 * k * p
        elif m == "shake":
            s = 1.03
            if t < 0.6:
                amp = 14 * u * k * (1 - t / 0.6)
                dx, dy = amp * math.sin(t * 70), amp * math.cos(t * 55)
        return s, dx, dy

    def draw(self, ctx: cairo.Context, t: float) -> None:
        W, H = self.ctx_info.W, self.ctx_info.H
        s, dx, dy = self.camera(t)
        # depth: the background layer moves less than the stage (parallax)
        k = self.parallax
        sb = 1.0 + (s - 1.0) * k
        ctx.save()
        ctx.translate(W / 2 + dx * k, H / 2 + dy * k)
        ctx.scale(sb, sb)
        ctx.translate(-W / 2, -H / 2)
        self.background.draw(ctx, t)
        ctx.restore()
        ctx.save()
        ctx.translate(W / 2 + dx, H / 2 + dy)
        ctx.scale(s, s)
        ctx.translate(-W / 2, -H / 2)
        drawn_char = False
        for el in sorted(self.elements, key=lambda e: e.z):
            if not drawn_char and el.z >= self.char_z and self.character is not None:
                self.character.draw(ctx, t, self.ctx_info.duration)
                drawn_char = True
            el.draw(ctx, t)
        if not drawn_char and self.character is not None:
            self.character.draw(ctx, t, self.ctx_info.duration)
        for fn in self.post:
            fn(ctx, t)
        ctx.restore()
        if self.foreground is not None:
            kf = 1.3                                    # foreground moves more than the stage
            sf = 1.0 + (s - 1.0) * kf
            ctx.save()
            ctx.translate(W / 2 + dx * kf, H / 2 + dy * kf)
            ctx.scale(sf, sf)
            ctx.translate(-W / 2, -H / 2)
            self.foreground.draw(ctx, t)
            ctx.restore()


# --------------------------------------------------------------------------- helpers
def _char_x(L: LayoutContext, position: str) -> Tuple[float, bool, int]:
    """(ground x, small, facing) for a character position."""
    if position == "left":
        return L.sx(0.2 if not L.vertical else 0.24), False, 1
    if position == "right":
        return L.sx(0.8 if not L.vertical else 0.76), False, -1
    if position == "center":
        return L.sx(0.5), False, 1
    if position == "corner_left":
        return L.sx(0.12 if not L.vertical else 0.17), True, 1
    return L.sx(0.88 if not L.vertical else 0.83), True, -1


def _mains(scene: Scene) -> List[ObjectSpec]:
    return [o for o in scene.objects if o.role == "main"]


def _others(scene: Scene, roles=("secondary", "item")) -> List[ObjectSpec]:
    return [o for o in scene.objects if o.role in roles]


def _overlay(scene: Scene, style: str) -> Optional[str]:
    return next((o.text for o in scene.text_overlays if o.style == style), None)


def _icon_height(asset, h: float, max_w: float) -> float:
    """Height that keeps the asset within max_w."""
    return min(h, max_w / max(asset.aspect, 0.01))


def _anchor_for_label(text: str, anchors: Sequence[str], i: int) -> str:
    """Anchor a label to the part it names ("Left atrium" -> left_atrium, "One-way valves" -> valves)."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    best, score = None, 0
    for a in anchors:
        parts = set(a.split("_"))
        hit = sum(1 for p in parts for w in words if w.startswith(p[:5]) or p.startswith(w[:5]))
        if hit > score:
            best, score = a, hit
    return best if best else anchors[i % len(anchors)]


def _label_style(L: LayoutContext) -> Dict:
    return {"unit": L.u, "size": 40 if L.vertical else 38}


class Builder:
    """Accumulates elements + sound events for one scene."""

    def __init__(self, L: LayoutContext, scene: Scene):
        self.L, self.scene = L, scene
        self.elements: List[Doodle] = []
        self.events: List[Tuple[float, str]] = []
        self.main_icon: Optional[IconPop] = None
        self.seed = L.seed
        self.focus_keys: List[Tuple[float, Point]] = []
        self.demo: Optional[Demo] = None

    def add(self, el: Doodle, sfx: Optional[str] = None) -> Doodle:
        el.unit = self.L.u
        el.seed = self.seed = self.seed + 1
        self.elements.append(el)
        if sfx and el.start < self.L.duration - 0.5:
            self.events.append((el.start, sfx))
        return el

    def icon(self, asset_id: str, center: Point, height: float, start: float, max_w: Optional[float] = None,
             entrance: str = "pop", idle: str = "float", z: int = 3, highlight: Sequence[str] = (),
             sfx: Optional[str] = "pop") -> IconPop:
        a = self.L.assets.get(asset_id)
        h = _icon_height(a, height, max_w or height * 1.6)
        el = IconPop(asset=a, center=center, height=h, start=start, duration=0.55, entrance=entrance,
                     idle=idle, z=z, highlight_groups=tuple(highlight) or None, highlight_start=start + 1.2)
        self.add(el, sfx)
        if z >= 3:
            self.focus_keys.append((start, center))
        return el

    def label(self, text: str, pos: Point, start: float, anchor: Optional[Point] = None, color: str = "white",
              z: int = 6, size: Optional[float] = None, max_width: float = 420) -> Label:
        # never let a label drift into the caption band or outside the safe stage
        x0, y0, x1, y1 = self.L.stage
        pos = (clamp(pos[0], x0 + 120 * self.L.u, x1 - 120 * self.L.u),
               clamp(pos[1], y0 + 36 * self.L.u, y1 - 44 * self.L.u))
        bg = PALETTE[color]
        fg = PALETTE["ink"] if color in ("white", "yellow", "yellow_light", "cream", "teal_light", "sky_light") \
            else (1, 1, 1)
        el = Label(text=text, pos=pos, anchor=anchor, start=start, duration=0.45, bg=bg, fg=fg, z=z,
                   size=size or (48 if self.L.vertical else 44), max_width=max_width)
        self.add(el, "click")
        if anchor is not None:
            self.focus_keys.append((start, ((anchor[0] + pos[0]) / 2, (anchor[1] + pos[1]) / 2)))
        return el


# --------------------------------------------------------------------------- layouts
def _layout_hook_title(b: Builder) -> None:
    L, sc = b.L, b.scene
    title = _overlay(sc, "title") or sc.narration.split("?")[0][:L.W] + ("?" if "?" in sc.narration else "")
    ty = L.sy(0.15 if L.vertical else 0.18)
    b.add(Burst(center=(L.sx(0.5), ty), r0=180, r1=330, rays=14, start=0.15, duration=0.5,
                color=PALETTE["yellow_light"], z=1), "boing")
    b.add(PopText(text=title.upper(), center=(L.sx(0.5), ty), size=120 if L.vertical else 112,
                  max_width=L.sw / L.u * 0.98, max_lines=3, start=0.2, per_word=0.11,
                  colors=("yellow", "white", "white", "teal_light"), z=8))
    mains = _mains(sc)
    if mains:
        cx, cy = (L.sx(0.66), L.sy(0.58)) if L.vertical else (L.sx(0.7), L.sy(0.62))
        h = L.sh * (0.36 if L.vertical else 0.5)
        b.main_icon = b.icon(mains[0].asset, (cx, cy), h, 0.6, max_w=L.sw * 0.5, entrance=mains[0].entrance,
                             idle="float", highlight=mains[0].highlight)
        b.add(Sparkle(center=(cx + h * 0.45, cy - h * 0.4), radius=34, start=1.0, z=4))
        b.add(Sparkle(center=(cx - h * 0.5, cy + h * 0.1), radius=24, start=1.2, z=4))
    for i, o in enumerate(_others(sc)[:2]):
        x = L.sx(0.1 + 0.8 * (i % 2))
        b.icon(o.asset, (x, L.sy(0.38)), L.sh * 0.14, 0.9 + 0.2 * i, z=2, idle="wiggle")


def _layout_character_explains(b: Builder, char_pos: str) -> None:
    L, sc = b.L, b.scene
    main = _mains(sc)[0]
    right = char_pos in ("left", "corner_left", "center")
    if L.vertical:
        cx, cy, h = L.sx(0.6 if right else 0.4), L.sy(0.36), L.sh * 0.42
    else:
        cx, cy, h = L.sx(0.66 if right else 0.34), L.sy(0.48), L.sh * 0.62
    b.main_icon = b.icon(main.asset, (cx, cy), h, L.cue_time(main.cue, 0.35), max_w=L.sw * 0.55,
                         entrance=main.entrance, idle=main.idle, highlight=main.highlight)
    if main.label:
        ly = cy + b.main_icon.height * 0.5 + 50 * L.u
        b.label(main.label, (cx, min(ly, L.stage[3] - 40 * L.u)), b.main_icon.start + 0.6,
                color=ACCENTS[L.seed % len(ACCENTS)])
    others = _others(sc)
    for i, o in enumerate(others[:2]):
        ox = cx + (1 if i == 0 else -1) * b.main_icon.height * 0.62
        oy = cy - b.main_icon.height * (0.42 - 0.5 * i)
        el = b.icon(o.asset, (ox, oy), L.sh * 0.15, L.cue_time(o.cue, L.spread(i + 1, 3)), z=4, idle="wiggle")
        if o.label:
            b.label(o.label, (ox, oy + el.height * 0.62 + 20 * L.u), el.start + 0.3, size=32, z=6)


def _layout_object_focus(b: Builder) -> None:
    L, sc = b.L, b.scene
    main = _mains(sc)[0]
    a = L.assets.get(main.asset)
    if L.vertical:
        cx, cy, h = L.sx(0.5), L.sy(0.4), L.sh * 0.5
    else:
        cx, cy, h = L.sx(0.56), L.sy(0.47), L.sh * 0.7
    b.main_icon = b.icon(main.asset, (cx, cy), h, L.cue_time(main.cue, 0.3), max_w=L.sw * 0.7,
                         entrance=main.entrance if main.entrance != "pop" else "draw", idle="none",
                         highlight=main.highlight, sfx="sparkle")
    labels = [o.text for o in sc.text_overlays if o.style == "label"] or ([main.label] if main.label else [])
    anchors = [n for n in a.anchors if n not in ("center", "top")]
    hh = b.main_icon.height
    for i, text in enumerate(labels[:4]):
        an = _anchor_for_label(text, anchors, i) if anchors else "center"
        ax, ay = a.anchor(an, cx, cy, hh) if anchors else (cx, cy)
        ang = math.atan2(ay - cy, ax - cx) if (ax, ay) != (cx, cy) else (-math.pi / 2 + i * 2.1)
        rx = hh * a.aspect * 0.5 + (150 if not L.vertical else 70) * L.u
        ry = hh * 0.5 + 60 * L.u
        px = clamp(cx + math.cos(ang) * rx, L.stage[0] + 170 * L.u, L.stage[2] - 170 * L.u)
        py = clamp(cy + math.sin(ang) * ry, L.stage[1] + 50 * L.u, L.stage[3] - 50 * L.u)
        cue = next((o.cue for o in sc.text_overlays if o.text == text), None)
        b.label(text, (px, py), L.cue_time(cue, L.spread(i, max(2, len(labels)), 0.15, 0.7)), anchor=(ax, ay),
                color=ACCENTS[(i + L.seed) % len(ACCENTS)], size=36 if not L.vertical else 38)


def _layout_diagram_flow(b: Builder) -> None:
    L, sc = b.L, b.scene
    objs = sc.objects[:4]
    n = len(objs)
    pts: List[Point] = []
    if L.vertical:
        for i in range(n):
            pts.append((L.sx(0.4 if i % 2 == 0 else 0.76), L.sy(0.08 + 0.52 * i / max(1, n - 1))))
        h = min(L.sh * 0.6 / n * 0.72, L.sh * 0.2)
    else:
        for i in range(n):
            pts.append((L.sx(0.36 + 0.56 * i / max(1, n - 1)), L.sy(0.36 + (0.1 if i % 2 else -0.04))))
        h = min(L.sw * 0.62 / n * 0.62, L.sh * 0.34)
    for i, (o, p) in enumerate(zip(objs, pts)):
        start = L.cue_time(o.cue, L.spread(i, n, 0.05, 0.75))
        el = b.icon(o.asset, p, h, start, max_w=h * 1.3, z=4, idle="pulse" if i == n - 1 else "float")
        if o.label:
            off = (el.height * 0.5 + 34 * L.u)
            lp = (p[0] + (el.height * 0.8 if L.vertical and i % 2 == 0 else -el.height * 0.8 if L.vertical else 0),
                  p[1] + (0 if L.vertical else off + 10 * L.u))
            b.label(o.label, lp, start + 0.35, color=ACCENTS[(i + 1) % len(ACCENTS)], size=40, max_width=340)
        if i > 0:
            a0, a1 = pts[i - 1], p
            dx, dy = a1[0] - a0[0], a1[1] - a0[1]
            d = math.hypot(dx, dy) or 1
            m = h * 0.62
            q0 = (a0[0] + dx / d * m, a0[1] + dy / d * m)
            q1 = (a1[0] - dx / d * m, a1[1] - dy / d * m)
            b.add(Arrow(p0=q0, p1=q1, bend=0.15 if i % 2 else -0.15, start=start - 0.35, duration=0.45,
                        color=PALETTE[ACCENTS[i % len(ACCENTS)]], z=3), "whoosh")


def _layout_list_reveal(b: Builder) -> None:
    L, sc = b.L, b.scene
    items = sc.items[:5]
    n = len(items)
    if L.vertical:
        x0, x1 = L.sx(0.02), L.sx(0.98)
        top, bottom = L.sy(0.02), L.sy(0.6)
    else:
        x0, x1 = L.sx(0.36), L.sx(0.99)
        top, bottom = L.sy(0.06), L.sy(0.94)
    rowh = (bottom - top) / n
    card_h = min(rowh * 0.84, 200 * L.u)
    for i, it in enumerate(items):
        y = top + rowh * (i + 0.5)
        start = L.cue_time(it.cue, L.spread(i, n, 0.08, 0.7))
        if i == 0:
            start = min(start, L.spread(0, n, 0.08, 0.7))     # the list never starts on an empty stage
        col = ACCENTS[(i + L.seed) % len(ACCENTS)]
        b.add(_Card(x0=x0, x1=x1, cy=y, h=card_h, color=PALETTE[col], start=start, duration=0.45, z=3,
                    text=it.text, icon=L.assets.get(it.asset) if it.asset else None, index=i + 1), "pop")


def _layout_comparison(b: Builder) -> None:
    L, sc = b.L, b.scene
    a, c = sc.objects[:2]
    if L.vertical:
        pa, pc, h = (L.sx(0.26), L.sy(0.3)), (L.sx(0.74), L.sy(0.3)), L.sh * 0.36
    else:
        pa, pc, h = (L.sx(0.44), L.sy(0.42)), (L.sx(0.82), L.sy(0.42)), L.sh * 0.48
    for i, (o, p) in enumerate(((a, pa), (c, pc))):
        start = L.cue_time(o.cue, L.spread(i, 2, 0.05, 0.5))
        panel_w = (L.sw * (0.46 if L.vertical else 0.32))
        b.add(_Panel(center=p, w=panel_w, h=h * 1.55, color=PALETTE[("teal_light", "pink_light")[i]],
                     start=start - 0.1, duration=0.4, z=1))
        el = b.icon(o.asset, (p[0], p[1] - h * 0.08), h * 0.82, start, max_w=panel_w * 0.85, z=3)
        if o.label:
            b.label(o.label, (p[0], p[1] + h * 0.6), start + 0.3, color=("teal", "coral")[i], size=36,
                    max_width=panel_w / L.u * 0.9)
        _ = el
    mid = ((pa[0] + pc[0]) / 2, pa[1] - h * 0.05)
    b.add(_VsBadge(center=mid, r=62, start=L.spread(1, 2, 0.05, 0.5) + 0.2, duration=0.45, z=5), "boing")


def _layout_thought_bubble(b: Builder, char_x: float) -> None:
    L, sc = b.L, b.scene
    if L.vertical:
        c, w, hh = (L.sx(0.56), L.sy(0.27)), L.sw / L.u * 0.95, L.sh * 0.42
    else:
        c, w, hh = (L.sx(0.64), L.sy(0.34)), L.sw / L.u * 0.56, L.sh * 0.56
    tail = (char_x + 60 * L.u, L.ground_y - L.char_height() * 0.92)
    bubble = SpeechBubble(text="", pos=c, tail_to=tail, width=w, size=10, thought=True, start=0.3,
                          duration=0.6, z=2, bg=PALETTE["white"], min_height=hh / L.u)
    b.add(bubble, "magic")
    objs = sc.objects[:3] or []
    n = max(1, len(objs))
    for i, o in enumerate(objs):
        px = c[0] + (i - (n - 1) / 2) * (w * L.u / (n + 0.6))
        start = L.cue_time(o.cue, L.spread(i, n, 0.1, 0.6))
        el = b.icon(o.asset, (px, c[1]), hh * (0.62 if n == 1 else 0.48), start, max_w=w * L.u / (n + 0.4),
                    z=3, idle="float")
        if i == 0:
            b.main_icon = el
    b.add(Particles(kind="twinkle", area=(c[0] - w * L.u / 2, c[1] - hh / 2, w * L.u, hh), count=10, size=16,
                    start=0.8, z=4))


def _layout_fact_card(b: Builder) -> None:
    L, sc = b.L, b.scene
    num = sc.number
    assert num is not None
    c = (L.sx(0.5), L.sy(0.22)) if L.vertical else (L.sx(0.62), L.sy(0.33))
    t0 = L.cue_time(None, 0.35)
    b.add(Burst(center=c, r0=140, r1=260, rays=16, start=t0, duration=0.5, color=PALETTE["yellow"], z=1), "ding")
    b.add(Counter(value=num.value, prefix=num.prefix, suffix=num.suffix, decimals=num.decimals, center=c,
                  size=190 if L.vertical else 180, start=t0, duration=1.1, z=6))
    if num.label:
        b.label(num.label, (c[0], c[1] + 170 * L.u), t0 + 0.6, color="purple", size=44, max_width=760)
    mains = _mains(sc)
    if mains:
        p = (L.sx(0.68), L.sy(0.6)) if L.vertical else (L.sx(0.88), L.sy(0.7))
        b.main_icon = b.icon(mains[0].asset, p, L.sh * 0.24, t0 + 0.9, z=3, idle="wiggle")
    b.add(StarDoodle(center=(c[0] - 330 * L.u, c[1] - 90 * L.u), radius=32, start=t0 + 0.3, z=2))
    b.add(StarDoodle(center=(c[0] + 330 * L.u, c[1] + 70 * L.u), radius=24, start=t0 + 0.5, z=2,
                     color=PALETTE["coral"]))


def _layout_story_scene(b: Builder, char_pos: str) -> None:
    L, sc = b.L, b.scene
    mains = _mains(sc)
    right = char_pos in ("left", "corner_left")
    if mains:
        a = L.assets.get(mains[0].asset)
        h = L.sh * (0.38 if L.vertical else 0.55)
        w = h * a.aspect
        maxw = L.sw * (0.86 if L.vertical else 0.6)
        if w > maxw:
            h = maxw / a.aspect
        cx = L.sx(0.5) if L.vertical else L.sx(0.64 if right else 0.36)
        cy = L.sy(0.32) if L.vertical else L.ground_y - h * 0.5 - 10 * L.u
        if L.vertical and a.aspect < 0.85:
            # standing figures (people) belong on the ground beside Milo, not floating in the sky
            h = L.char_height() * 0.9
            cx, cy = L.sx(0.74), L.ground_y - h * 0.5
        b.main_icon = b.icon(mains[0].asset, (cx, cy), h, 0.25, max_w=maxw, entrance=mains[0].entrance,
                             idle="none" if mains[0].idle == "float" else mains[0].idle, z=2, sfx=None)
    for i, o in enumerate(_others(sc)[:3]):
        cx0 = b.main_icon.center[0] if b.main_icon else L.sx(0.5)
        p = (cx0 + (i - 1) * 220 * L.u, L.sy(0.08 + 0.06 * (i % 2)))
        el = b.icon(o.asset, p, L.sh * 0.13, L.cue_time(o.cue, L.spread(i, 3, 0.2, 0.7)), z=3, idle="float")
        if o.label:
            b.label(o.label, (p[0], p[1] + el.height * 0.7), el.start + 0.3, size=30)


def _layout_network(b: Builder) -> None:
    L, sc = b.L, b.scene
    mains = _mains(sc) or sc.objects[:1]
    sats = [o for o in sc.objects if o is not mains[0]][:5]
    c = (L.sx(0.5), L.sy(0.38)) if L.vertical else (L.sx(0.58), L.sy(0.46))
    hm = L.sh * (0.26 if L.vertical else 0.36)
    b.main_icon = b.icon(mains[0].asset, c, hm, 0.3, idle="pulse", z=4, highlight=mains[0].highlight)
    R = min(L.sw * 0.38, L.sh * (0.36 if L.vertical else 0.42))
    n = len(sats)
    for i, o in enumerate(sats):
        ang = -math.pi / 2 + (i + 0.5) * 2 * math.pi / n + (0.2 if n % 2 else 0)
        p = (c[0] + R * math.cos(ang) * (1.15 if not L.vertical else 1.0), c[1] + R * math.sin(ang) * 0.92)
        start = L.cue_time(o.cue, L.spread(i, n, 0.1, 0.7))
        b.add(Pathway(points=[c, ((c[0] + p[0]) / 2 + 30 * L.u * math.sin(ang * 3), (c[1] + p[1]) / 2), p],
                      color=PALETTE[ACCENTS[i % len(ACCENTS)]], start=start - 0.2, duration=0.5, pulses=2,
                      speed=0.5 + 0.1 * i, z=2), "whoosh")
        el = b.icon(o.asset, p, L.sh * (0.13 if L.vertical else 0.17), start + 0.2, z=4, idle="float", sfx="pop")
        if o.label:
            b.label(o.label, (p[0], p[1] + el.height * 0.62 + 18 * L.u), start + 0.45, size=38, max_width=320,
                    color=ACCENTS[(i + 2) % len(ACCENTS)])


def _layout_chart(b: Builder) -> None:
    L, sc = b.L, b.scene
    ch = sc.chart
    assert ch is not None
    if L.vertical:
        box = (L.sx(0.12), L.sy(0.08), L.sw * 0.82, L.sh * 0.42)
    else:
        box = (L.sx(0.36), L.sy(0.1), L.sw * 0.58, L.sh * 0.62)
    t0 = 0.4
    if ch.kind in ("line", "step"):
        dur = max(1.5, (L.speech_end - t0) * 0.7)
        b.add(LineChart(points=[tuple(p) for p in ch.points], box=box, step=ch.kind == "step",
                        y_labels=ch.labels, x_labels=ch.x_labels, highlight_level=ch.highlight_level,
                        start=t0, duration=dur, z=3), "whoosh")
    else:
        b.add(BarChart(values=ch.values, labels=ch.labels, box=box, value_suffix=ch.value_suffix, start=t0,
                       duration=1.2, z=3), "pop")
    b.chart_center = (box[0] + box[2] / 2, box[1] + box[3] / 2)  # type: ignore[attr-defined]


def _layout_question(b: Builder) -> None:
    L, sc = b.L, b.scene
    q = _overlay(sc, "title") or _overlay(sc, "bubble") or sc.narration
    c = (L.sx(0.5), L.sy(0.17)) if L.vertical else (L.sx(0.6), L.sy(0.22))
    b.add(PopText(text=q, center=c, size=86 if L.vertical else 84, max_width=L.sw / L.u * (0.96 if L.vertical else 0.66),
                  max_lines=3, start=0.25, per_word=0.08, colors=("white", "yellow"), z=7), "pop")
    mains = _mains(sc)
    asset = mains[0].asset if mains else "question_mark"
    p = (L.sx(0.66), L.sy(0.55)) if L.vertical else (L.sx(0.66), L.sy(0.64))
    b.main_icon = b.icon(asset, p, L.sh * (0.3 if L.vertical else 0.4), 0.7, entrance="bounce", idle="wiggle", z=3)
    for i, (fx, fy) in enumerate(((0.1, 0.42), (0.92, 0.5), (0.42, 0.62))):
        b.icon("question_mark", (L.sx(fx), L.sy(fy)), L.sh * 0.08, 1.0 + 0.25 * i, z=1, idle="spin", sfx=None)


def _layout_timeline(b: Builder) -> None:
    L, sc = b.L, b.scene
    items = sc.items[:5]
    n = len(items)
    if L.vertical:
        x = L.sx(0.18)
        pts = [(x, L.sy(0.06 + 0.56 * i / max(1, n - 1))) for i in range(n)]
    else:
        y = L.sy(0.45)
        pts = [(L.sx(0.34 + 0.6 * i / max(1, n - 1)), y) for i in range(n)]
    b.add(Pathway(points=[pts[0], pts[-1]] if len(pts) > 1 else pts * 2, color=PALETTE["lavender"], width=12,
                  pulses=1, speed=0.25, curvy=False, start=0.2, duration=0.8, z=1), "whoosh")
    for i, (it, p) in enumerate(zip(items, pts)):
        start = L.cue_time(it.cue, L.spread(i, n, 0.05, 0.75))
        col = ACCENTS[(i + L.seed) % len(ACCENTS)]
        b.add(_Dot(center=p, r=24, color=PALETTE[col], start=start, duration=0.4, z=3, index=i + 1), "click")
        if it.asset:
            ip = (p[0] + 150 * L.u, p[1]) if L.vertical else (p[0], p[1] - 150 * L.u)
            b.icon(it.asset, ip, (130 if L.vertical else 160) * L.u, start + 0.1, z=4, sfx=None)
        lp = (p[0] + (430 if L.vertical else 0) * L.u, p[1]) if L.vertical else (p[0], p[1] + 110 * L.u)
        b.label(it.text, lp, start + 0.25, color=col, size=40, max_width=420 if L.vertical else 330)


def _layout_wave_monitor(b: Builder) -> None:
    L, sc = b.L, b.scene
    if L.vertical:
        box = (L.sx(0.06), L.sy(0.06), L.sw * 0.88, L.sh * 0.34)
    else:
        box = (L.sx(0.34), L.sy(0.1), L.sw * 0.6, L.sh * 0.52)
    items = sc.items or []
    b.add(_Monitor(box=box, start=0.2, duration=0.45, z=2), "click")
    kinds = []
    for it in items or [None]:
        txt = (it.text if it else sc.narration).lower()
        kinds.append("slow" if any(k in txt for k in ("deep", "slow", "delta")) else
                     "heartbeat" if "heart" in txt else "brain")
    n = len(kinds)
    inner = (box[0] + 40 * L.u, box[1] + 40 * L.u, box[2] - 80 * L.u, box[3] - 80 * L.u)
    for i, k in enumerate(kinds):
        start = L.cue_time(items[i].cue if items else None, L.spread(i, n, 0.0, 0.7)) if items else 0.6
        if i == 0:
            start = min(start, 0.6)                           # the monitor is never empty
        end = (L.cue_time(items[i + 1].cue, L.spread(i + 1, n, 0.0, 0.7)) if i + 1 < n else None)
        b.add(WaveLine(box=inner, kind=k, start=max(0.5, start), duration=0.8, end=end, exit_dur=0.15,
                       color=PALETTE[("green", "purple", "teal", "coral")[i % 4]], z=3))
        if items:
            b.label(items[i].text, (box[0] + box[2] / 2, box[1] + box[3] + 60 * L.u), max(0.5, start) + 0.2,
                    color=("green", "purple", "teal", "coral")[i % 4], size=40).end = end
    b.chart_center = (box[0] + box[2] / 2, box[1] + box[3] / 2)  # type: ignore[attr-defined]


def _layout_outro(b: Builder) -> None:
    L, sc = b.L, b.scene
    c = (L.sx(0.5), L.sy(0.13 if L.vertical else 0.17))
    b.add(PopText(text=L.brand_name, center=c, size=118 if L.vertical else 120, max_width=L.sw / L.u, max_lines=2,
                  start=0.2, per_word=0.15, colors=("yellow", "teal_light"), z=7, tilt=-2), "chime")
    b.add(_Tagline(text=L.tagline, center=(c[0], c[1] + (190 if L.vertical else 120) * L.u), start=0.9, z=7))
    cta = _overlay(sc, "cta") or "Follow for more!"
    pos = (L.sx(0.62), L.sy(0.55)) if L.vertical else (L.sx(0.68), L.sy(0.6))
    b.add(SpeechBubble(text=cta, pos=pos, width=(L.sw / L.u) * (0.62 if L.vertical else 0.4), size=50, start=1.4,
                       duration=0.5, z=8, bg=PALETTE["orange"], fg=(1, 1, 1), typewriter=False,
                       tail_to=(L.sx(0.32 if L.vertical else 0.3), L.ground_y - L.char_height() * 0.75)), "pop")
    b.add(Particles(kind="confetti", center=(L.sx(0.5), L.sy(0.35)), count=40, size=12, start=0.4, z=9))
    b.add(Particles(kind="confetti", center=(L.sx(0.5), L.sy(0.35)), count=30, size=10, start=2.4, z=9))


def _demo_box(L: LayoutContext, char_pos: str) -> Tuple[float, float, float, float]:
    if L.vertical:
        return (L.sx(0.02), L.sy(0.0), L.sw * 0.96, L.sh * 0.74)
    left = char_pos in ("left", "corner_left")
    return (L.sx(0.24 if left else 0.03), L.sy(0.02), L.sw * 0.73, L.sh * 0.95)


def _layout_demonstration(b: Builder, char_pos: str) -> None:
    """Animated explanatory diagram; stages start on their cue words, callouts follow the stages."""
    L, sc = b.L, b.scene
    spec = sc.demo
    assert spec is not None
    from src.animation.demos import STAGE_COUNT
    n = STAGE_COUNT.get(spec.kind, 3)
    stages = [0.25]
    for k in range(1, n):
        cue = spec.stage_cues[k - 1] if k - 1 < len(spec.stage_cues) else None
        default = L.spread(k, n, 0.0, 0.8)
        stages.append(max(stages[-1] + 0.6, L.cue_time(cue, default)))
    demo = make_demo(spec.kind, _demo_box(L, char_pos), stages, L.assets, L.u, seed=L.seed)
    b.add(demo, "whoosh")
    demo.seed = L.seed
    b.demo = demo
    for k, t in enumerate(stages[1:], start=1):
        b.events.append((t, ("pop", "sparkle", "click", "ding")[k % 4]))
    names = list(demo.label_points)
    x0, y0, x1, y1 = L.stage
    for i, text in enumerate(spec.labels[:len(names)]):
        ax, ay = demo.label_points[names[i]]
        cx, cy = demo.cx, demo.cy
        ang = math.atan2(ay - cy, ax - cx) if (ax, ay) != (cx, cy) else -math.pi / 2
        px = clamp(ax + math.cos(ang) * 150 * L.u, x0 + 160 * L.u, x1 - 160 * L.u)
        py = clamp(ay + math.sin(ang) * 110 * L.u - 30 * L.u, y0 + 40 * L.u, y1 - 50 * L.u)
        start = stages[min(i + 1, len(stages) - 1)] + 0.35
        b.label(text, (px, py), start, anchor=(ax, ay), color=ACCENTS[(i + L.seed) % len(ACCENTS)],
                size=38 if L.vertical else 36, max_width=360)


def _layout_full_illustration(b: Builder, char_pos: str) -> None:
    """One big illustration drawn on, then toured by the camera via labelled callouts."""
    L, sc = b.L, b.scene
    main = _mains(sc)[0]
    a = L.assets.get(main.asset)
    left = char_pos in ("left", "corner_left")
    if L.vertical:
        cx, cy, h, maxw = L.sx(0.5), L.sy(0.38), L.sh * 0.6, L.sw * 0.98
    else:
        cx, cy, h, maxw = L.sx(0.58 if left else 0.42), L.sy(0.5), L.sh * 0.86, L.sw * 0.74
    b.main_icon = b.icon(main.asset, (cx, cy), h, 0.15, max_w=maxw, entrance="draw", idle="none", z=2,
                         highlight=main.highlight, sfx="sparkle")
    b.main_icon.duration = 1.1
    labels = [o.text for o in sc.text_overlays if o.style == "label"] or ([main.label] if main.label else [])
    anchors = [n for n in a.anchors if n not in ("center", "top")]
    hh = b.main_icon.height
    for i, text in enumerate(labels[:4]):
        an = _anchor_for_label(text, anchors, i) if anchors else "center"
        ax, ay = a.anchor(an, cx, cy, hh) if anchors else (cx, cy)
        ang = math.atan2(ay - cy, ax - cx) if (ax, ay) != (cx, cy) else (-math.pi / 2 + i * 2.1)
        px = clamp(ax + math.cos(ang) * 170 * L.u, L.stage[0] + 170 * L.u, L.stage[2] - 170 * L.u)
        py = clamp(ay + math.sin(ang) * 120 * L.u, L.stage[1] + 50 * L.u, L.stage[3] - 50 * L.u)
        cue = next((o.cue for o in sc.text_overlays if o.text == text), None)
        b.label(text, (px, py), L.cue_time(cue, L.spread(i, max(2, len(labels)), 0.2, 0.75)), anchor=(ax, ay),
                color=ACCENTS[(i + L.seed) % len(ACCENTS)], size=38 if L.vertical else 36)
    if not labels:
        b.focus_keys.append((0.2, (cx, cy - hh * 0.15)))
        b.focus_keys.append((L.duration * 0.6, (cx, cy)))


def _layout_character_closeup(b: Builder, char_pos: str) -> None:
    """Milo big, talking to the viewer; one prop pops in beside him on the far side."""
    L, sc = b.L, b.scene
    mains = _mains(sc)
    if mains:
        p = (L.sx(0.74), L.sy(0.22)) if L.vertical else (L.sx(0.74), L.sy(0.3))
        b.main_icon = b.icon(mains[0].asset, p, L.sh * (0.24 if L.vertical else 0.36), L.cue_time(mains[0].cue, 0.6),
                             entrance="elastic", idle="float", z=4)
        b.add(Sparkle(center=(p[0] + 90 * L.u, p[1] - 80 * L.u), radius=28, start=b.main_icon.start + 0.3, z=5))
    b.focus_keys.append((0.0, (L.sx(0.4), L.sy(0.45))))


@dataclass
class _Foreground(Doodle):
    """Out-of-focus depth props in front of the stage, per niche (subtle, kept to the frame edges)."""
    kind: str = "science"
    W: int = 1080
    H: int = 1920

    def draw(self, ctx, t):
        u = self.unit
        rnd = __import__("random").Random(self.seed * 31 + 7)
        k = clamp(t / 0.8)
        if self.kind == "medical":
            for i in range(4):
                side = i % 2
                x = (-30 + rnd.random() * 160) * u if side == 0 else self.W - (-30 + rnd.random() * 160) * u
                y = self.H * (0.12 + 0.7 * rnd.random()) + math.sin(t * 0.6 + i) * 18 * u
                r = (60 + 50 * rnd.random()) * u
                ctx.save()
                ctx.translate(x, y)
                ctx.scale(1, 0.7)
                ctx.arc(0, 0, r, 0, 2 * math.pi)
                ctx.restore()
                ctx.set_source_rgba(*PALETTE["red"], 0.16 * k)
                ctx.fill()
        elif self.kind == "mind":
            for i in range(3):
                x = self.W * (0.05 if i % 2 == 0 else 0.95)
                y = self.H * (0.18 + 0.32 * i)
                r = (120 + 60 * i) * u
                ctx.set_line_width(14 * u)
                ctx.set_source_rgba(*PALETTE["lavender"], 0.16 * k)
                a0 = t * 0.2 * (1 if i % 2 else -1) + i
                ctx.arc(x, y, r, a0, a0 + 2.2)
                ctx.stroke()
        else:
            for i in range(7):
                x = self.W * rnd.random()
                y = self.H * (rnd.random() * 0.25 if i % 2 else 0.6 + rnd.random() * 0.15)
                y += math.sin(t * 0.5 + i) * 12 * u
                r = (10 + 18 * rnd.random()) * u
                ctx.arc(x, y, r, 0, 2 * math.pi)
                ctx.set_source_rgba(*lighten(PALETTE["yellow_light"], 0.3), 0.22 * k)
                ctx.fill()


# --------------------------------------------------------------------------- custom small elements
@dataclass
class _Card(Doodle):
    x0: float = 0
    x1: float = 100
    cy: float = 0
    h: float = 120
    color: Tuple[float, float, float] = (1, 1, 1)
    text: str = ""
    icon: Optional[object] = None
    index: int = 1

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        u = self.unit
        p = ease_out_back(progress(t, self.start, self.duration), 1.4) * self.exit_factor(t)
        if p <= 0.01:
            return
        w = self.x1 - self.x0
        ctx.save()
        ctx.translate(self.x0 + (1 - p) * -60 * u, self.cy)
        ctx.scale(1, max(0.01, min(1.2, p)))
        rounded_rect(ctx, 6 * u, -self.h / 2 + 8 * u, w, self.h, 28 * u)
        ctx.set_source_rgba(*PALETTE["ink"], 0.85)
        ctx.fill()
        rounded_rect(ctx, 0, -self.h / 2, w, self.h, 28 * u)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill_preserve()
        ctx.set_source_rgb(*PALETTE["ink"])
        ctx.set_line_width(5 * u)
        ctx.stroke()
        bw = self.h
        rounded_rect(ctx, 0, -self.h / 2, bw, self.h, 28 * u)
        ctx.set_source_rgb(*self.color)
        ctx.fill_preserve()
        ctx.set_source_rgb(*PALETTE["ink"])
        ctx.stroke()
        if self.icon is not None:
            self.icon.draw(ctx, bw / 2, 0, self.h * 0.72 / max(1, self.icon.aspect ** 0.5),
                           rotation=4 * math.sin(t * 2 + self.index))
        else:
            st = TextStyle(font=TITLE_FONT, size=self.h * 0.5, color=(1, 1, 1), outline=PALETTE["ink"],
                           outline_width=self.h * 0.06)
            draw_lines(ctx, [str(self.index)], bw / 2, -self.h * 0.27, st)
        st = TextStyle(font=CAPTION_FONT, size=min(54 * u, self.h * 0.36), color=PALETTE["ink"], outline=None)
        size, lines = fit_size(ctx, self.text, st, w - bw - 50 * u, 2, 22 * u)
        st.size = size
        th = size * (1 + (len(lines) - 1) * st.line_spacing)
        draw_lines(ctx, lines, bw + 28 * u, -th / 2 - size * 0.05, st, "left")
        ctx.restore()


@dataclass
class _Panel(Doodle):
    center: Point = (0, 0)
    w: float = 300
    h: float = 400
    color: Tuple[float, float, float] = (1, 1, 1)

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        p = ease_out_back(progress(t, self.start, self.duration), 1.3) * self.exit_factor(t)
        if p <= 0.01:
            return
        u = self.unit
        ctx.save()
        ctx.translate(*self.center)
        ctx.scale(p, p)
        rounded_rect(ctx, -self.w / 2, -self.h / 2, self.w, self.h, 36 * u)
        ctx.set_source_rgba(*self.color, 0.92)
        ctx.fill_preserve()
        ctx.set_source_rgb(*PALETTE["ink"])
        ctx.set_line_width(6 * u)
        ctx.stroke()
        ctx.restore()


@dataclass
class _VsBadge(Doodle):
    center: Point = (0, 0)
    r: float = 60

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        p = ease_out_back(progress(t, self.start, self.duration), 2.2) * self.exit_factor(t)
        if p <= 0.01:
            return
        u = self.unit
        ctx.save()
        ctx.translate(*self.center)
        ctx.scale(p, p)
        ctx.rotate(math.radians(-8 + 3 * math.sin(t * 3)))
        ctx.arc(0, 0, self.r * u, 0, 2 * math.pi)
        ctx.set_source_rgb(*PALETTE["yellow"])
        ctx.fill_preserve()
        ctx.set_source_rgb(*PALETTE["ink"])
        ctx.set_line_width(6 * u)
        ctx.stroke()
        st = TextStyle(font=TITLE_FONT, size=self.r * u * 0.9, color=PALETTE["coral"], outline=PALETTE["ink"],
                       outline_width=7 * u)
        draw_lines(ctx, ["VS"], 0, -self.r * u * 0.5, st)
        ctx.restore()


@dataclass
class _Dot(Doodle):
    center: Point = (0, 0)
    r: float = 24
    color: Tuple[float, float, float] = (1, 1, 1)
    index: int = 1

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        p = ease_out_back(progress(t, self.start, self.duration), 2.0) * self.exit_factor(t)
        if p <= 0.01:
            return
        u = self.unit
        ctx.arc(self.center[0], self.center[1], self.r * u * p * (1 + 0.08 * math.sin(t * 4 + self.index)), 0,
                2 * math.pi)
        ctx.set_source_rgb(*self.color)
        ctx.fill_preserve()
        ctx.set_source_rgb(*PALETTE["ink"])
        ctx.set_line_width(5 * u)
        ctx.stroke()


@dataclass
class _Monitor(Doodle):
    box: Tuple[float, float, float, float] = (0, 0, 100, 100)

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        p = ease_out_back(progress(t, self.start, self.duration), 1.3) * self.exit_factor(t)
        if p <= 0.01:
            return
        u = self.unit
        x, y, w, h = self.box
        ctx.save()
        ctx.translate(x + w / 2, y + h / 2)
        ctx.scale(p, p)
        rounded_rect(ctx, -w / 2 - 24 * u, -h / 2 - 24 * u, w + 48 * u, h + 48 * u, 34 * u)
        ctx.set_source_rgb(*PALETTE["navy"])
        ctx.fill_preserve()
        ctx.set_source_rgb(*PALETTE["ink"])
        ctx.set_line_width(7 * u)
        ctx.stroke()
        rounded_rect(ctx, -w / 2, -h / 2, w, h, 20 * u)
        ctx.set_source_rgb(*PALETTE["night"])
        ctx.fill()
        ctx.set_source_rgba(*PALETTE["teal"], 0.15)
        ctx.set_line_width(2 * u)
        gx = -w / 2
        while gx < w / 2:
            ctx.move_to(gx, -h / 2)
            ctx.line_to(gx, h / 2)
            gx += 60 * u
        gy = -h / 2
        while gy < h / 2:
            ctx.move_to(-w / 2, gy)
            ctx.line_to(w / 2, gy)
            gy += 60 * u
        ctx.stroke()
        ctx.arc(w / 2 - 30 * u, -h / 2 + 30 * u, 9 * u, 0, 2 * math.pi)
        ctx.set_source_rgba(*PALETTE["coral"], 0.6 + 0.4 * math.sin(t * 6))
        ctx.fill()
        ctx.restore()


@dataclass
class _Tagline(Doodle):
    text: str = ""
    center: Point = (0, 0)

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        a = progress(t, self.start, 0.6) * self.exit_factor(t)
        st = TextStyle(font=HAND_FONT, size=58 * self.unit, color=(1, 1, 1), outline=PALETTE["ink"],
                       outline_width=8 * self.unit)
        draw_lines(ctx, [self.text], self.center[0], self.center[1] - 30 * self.unit, st, "center", a)


# --------------------------------------------------------------------------- generic doodles / overlays
def _apply_doodles(b: Builder, char_anim: Optional[CharacterAnimator], char_place: Optional[Placement]) -> None:
    L, sc = b.L, b.scene
    mi = b.main_icon
    mc = mi.center if mi else (L.sx(0.5), L.sy(0.4))
    mh = mi.height if mi else L.sh * 0.3
    t_main = mi.start if mi else 0.4
    for kind in sc.doodles:
        if kind == "sparkles":
            for i in range(4):
                ang = i * 1.7 + L.seed
                b.add(Sparkle(center=(mc[0] + math.cos(ang) * mh * 0.62, mc[1] + math.sin(ang) * mh * 0.55),
                              radius=26 + 8 * (i % 2), start=t_main + 0.4 + 0.15 * i, z=6,
                              color=(1, 1, 1) if i % 2 else PALETTE["yellow_light"]))
        elif kind == "stars":
            for i in range(3):
                b.add(StarDoodle(center=(mc[0] + (i - 1) * mh * 0.7, mc[1] - mh * 0.62 - 10 * (i % 2) * L.u),
                                 radius=26, start=t_main + 0.5 + 0.2 * i, z=6,
                                 color=PALETTE[("yellow", "coral", "teal")[i]]))
        elif kind == "burst":
            b.add(Burst(center=mc, r0=mh * 0.55 / L.u, r1=mh * 0.85 / L.u, start=t_main + 0.1, z=1), None)
        elif kind == "confetti":
            b.add(Particles(kind="confetti", center=mc, count=36, start=t_main + 0.5, z=9), "success")
        elif kind == "zzz":
            b.add(Particles(kind="zzz", area=(mc[0] - mh * 0.2, mc[1] - mh * 1.3, mh * 0.8, mh * 1.1), count=4,
                            size=18, start=t_main + 0.3, z=5, colors=("lavender",)), None)
        elif kind == "bubbles":
            b.add(Particles(kind="bubbles", area=(L.stage[0], L.stage[1], L.sw, L.sh), count=14, size=16,
                            start=0.2, z=0, colors=("lavender", "sky", "pink")))
        elif kind == "twinkle_field":
            b.add(Particles(kind="twinkle", area=(L.stage[0], L.stage[1], L.sw, L.sh), count=22, size=14,
                            start=0.1, z=0))
        elif kind == "float_up":
            b.add(Particles(kind="float_up", area=(L.stage[0], L.stage[1], L.sw, L.sh), count=14, size=14,
                            start=0.1, z=0))
        elif kind == "circle_main" and mi:
            b.add(CircleHighlight(center=mc, rx=mh * 0.62 * max(1, mi.asset.aspect if mi.asset else 1),
                                  ry=mh * 0.6, start=t_main + max(1.0, (L.speech_end - t_main) * 0.4),
                                  duration=0.6, z=4), "click")        # under labels (z=6)
        elif kind == "arrow_to_main" and mi and char_place is not None:
            sx = char_place.x + char_place.facing * char_place.height * 0.32
            sy = char_place.y - char_place.height * 0.75
            ex = mc[0] - (mc[0] - sx) / max(1, abs(mc[0] - sx)) * mh * 0.55
            b.add(Arrow(p0=(sx, sy), p1=(ex, mc[1]), bend=-0.25, start=t_main + 0.6, duration=0.5, z=6), "whoosh")
        elif kind == "underline_title":
            b.add(MarkerHighlight(x0=L.sx(0.2), x1=L.sx(0.8), y=L.sy(0.27 if L.vertical else 0.3), underline=True,
                                  color=PALETTE["coral"], start=1.0, duration=0.5, z=9))
        elif kind == "morph":
            p = (L.sx(0.85), L.sy(0.12)) if not L.vertical else (L.sx(0.86), L.sy(0.08))
            b.add(MorphShape(center=p, size=60, start=0.6, z=2))


def _apply_text_overlays(b: Builder, layout: str, char_anim: Optional[CharacterAnimator],
                         char_place: Optional[Placement]) -> None:
    """Overlays not consumed by the layout: titles, notes, speech bubbles."""
    L, sc = b.L, b.scene
    consumed = {"hook_title": ("title",), "question": ("title", "bubble"), "outro": ("cta",),
                "object_focus": ("label",), "fact_card": ("fact",),
                "full_illustration": ("label",)}.get(layout, ())
    for ov in sc.text_overlays:
        if ov.style in consumed:
            continue
        start = L.cue_time(ov.cue, 0.5)
        if ov.style == "title":
            y = L.sy(0.05 if L.vertical else 0.06)
            b.add(_TitleBanner(text=ov.text, center=(L.sx(0.5), y), start=start, z=8), "pop")
        elif ov.style in ("bubble", "fact") and char_place is not None:
            hx = char_place.x
            top = char_place.y - char_place.height
            right = hx < L.W / 2
            pos = (hx + (300 if right else -300) * L.u, max(L.sy(0.12), top - 40 * L.u))
            if L.vertical:
                pos = (L.sx(0.5), max(L.sy(0.08), top - 140 * L.u))
            b.add(SpeechBubble(text=ov.text, pos=pos, tail_to=(hx, top + char_place.height * 0.08),
                               width=min(560, L.sw / L.u * 0.8), size=42, start=start, duration=0.45, z=9), "pop")
        elif ov.style == "label":
            b.label(ov.text, (L.sx(0.5), L.sy(0.92)), start, color="yellow", z=8)
        elif ov.style == "note":
            b.add(_Note(text=ov.text, pos=(L.sx(0.06), L.sy(0.04)), start=start, z=8), "click")
        elif ov.style == "cta":
            b.add(SpeechBubble(text=ov.text, pos=(L.sx(0.5), L.sy(0.08)), width=min(640, L.sw / L.u * 0.85),
                               size=44, bg=PALETTE["orange"], fg=(1, 1, 1), start=start, z=9, typewriter=False), "pop")


@dataclass
class _TitleBanner(Doodle):
    text: str = ""
    center: Point = (0, 0)

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        u = self.unit
        p = ease_out_back(progress(t, self.start, 0.45), 1.6) * self.exit_factor(t)
        if p <= 0.01:
            return
        st = TextStyle(font=TITLE_FONT, size=64 * u, color=(1, 1, 1), outline=PALETTE["ink"], outline_width=10 * u)
        ctx.select_font_face(TITLE_FONT)
        ctx.set_font_size(st.size)
        w = min(ctx.text_extents(self.text).x_advance + 80 * u, 1700 * u)
        h = 108 * u
        ctx.save()
        ctx.translate(self.center[0], self.center[1] + h / 2)
        ctx.scale(p, p)
        ctx.rotate(math.radians(-1.5))
        rounded_rect(ctx, -w / 2 + 6 * u, -h / 2 + 8 * u, w, h, 30 * u)
        ctx.set_source_rgba(*PALETTE["ink"], 0.9)
        ctx.fill()
        rounded_rect(ctx, -w / 2, -h / 2, w, h, 30 * u)
        ctx.set_source_rgb(*PALETTE["coral"])
        ctx.fill_preserve()
        ctx.set_source_rgb(*PALETTE["ink"])
        ctx.set_line_width(6 * u)
        ctx.stroke()
        size, lines = fit_size(ctx, self.text, st, w - 50 * u, 1, 24 * u)
        st.size = size
        draw_lines(ctx, lines[:1], 0, -size * 0.62, st)
        ctx.restore()


@dataclass
class _Note(Doodle):
    text: str = ""
    pos: Point = (0, 0)

    def draw(self, ctx, t):
        if not self.visible(t):
            return
        u = self.unit
        n = int(len(self.text) * clamp((t - self.start) / max(0.5, len(self.text) * 0.04)))
        st = TextStyle(font=HAND_FONT, size=52 * u, color=PALETTE["ink"], outline=(1, 1, 1), outline_width=8 * u)
        draw_lines(ctx, [self.text[:n]], self.pos[0], self.pos[1], st, "left", self.exit_factor(t))


# --------------------------------------------------------------------------- entry point
def compose_scene(scene: Scene, L: LayoutContext, envelope: Optional[Sequence[float]] = None,
                  fps: int = 30, char_id: str = "milo") -> SceneComposition:
    if L.speech_end <= 0:
        L.speech_end = max(L.speech_start + 0.5, L.duration - 0.4)
    b = Builder(L, scene)
    layout = scene.layout
    cd = scene.character
    char_place: Optional[Placement] = None
    position = cd.position
    if layout in ("object_focus", "network", "diagram_flow", "list_reveal", "timeline", "chart", "wave_monitor",
                  "fact_card", "comparison") and position in ("left", "right") and L.vertical:
        position = "corner_left" if position == "left" else "corner_right"
    if layout in ("comparison", "diagram_flow", "timeline") and not L.vertical:
        position = "corner_left"
    if layout in ("object_focus", "network") and position in ("left", "right"):
        position = "corner_left" if position == "left" else "corner_right"
    if layout == "list_reveal" and not L.vertical and position not in ("left", "corner_left"):
        position = "left"
    if layout == "outro":
        position = "left" if not L.vertical else "corner_left"
    if layout == "fact_card" and not L.vertical:
        position = "left"                                     # keep the mascot clear of the big number
    if layout == "demonstration" and position not in ("corner_left", "corner_right"):
        position = "corner_left" if position in ("left", "center") else "corner_right"
    if layout == "full_illustration" and position in ("left", "right", "center"):
        position = "corner_left" if position == "left" else "corner_right"
    if position == "closeup":
        cx, small, facing = (L.sx(0.3), False, 1)
    else:
        cx, small, facing = _char_x(L, position)
    if layout == "demonstration" and not L.vertical:
        cx = L.sx(0.11) if position == "corner_left" else L.sx(0.89)
    if layout == "hook_title":
        cx, small = (L.sx(0.3), False) if L.vertical else (L.sx(0.28), False)

    builders: Dict[str, Callable[[], None]] = {
        "hook_title": lambda: _layout_hook_title(b),
        "character_explains": lambda: _layout_character_explains(b, position),
        "object_focus": lambda: _layout_object_focus(b),
        "diagram_flow": lambda: _layout_diagram_flow(b),
        "list_reveal": lambda: _layout_list_reveal(b),
        "comparison": lambda: _layout_comparison(b),
        "thought_bubble": lambda: _layout_thought_bubble(b, cx),
        "fact_card": lambda: _layout_fact_card(b),
        "story_scene": lambda: _layout_story_scene(b, position),
        "network": lambda: _layout_network(b),
        "chart": lambda: _layout_chart(b),
        "question": lambda: _layout_question(b),
        "timeline": lambda: _layout_timeline(b),
        "wave_monitor": lambda: _layout_wave_monitor(b),
        "outro": lambda: _layout_outro(b),
        "demonstration": lambda: _layout_demonstration(b, position),
        "full_illustration": lambda: _layout_full_illustration(b, position),
        "character_closeup": lambda: _layout_character_closeup(b, position),
    }
    builders[layout]()

    character: Optional[CharacterAnimator] = None
    if cd.present:
        h = L.char_height(small)
        ground = L.ground_y
        if layout == "comparison" and L.vertical:
            h *= 0.85
        if position == "closeup":
            h = L.sh * (1.15 if L.vertical else 1.45)    # waist-up: the lower body sits below the stage edge
            ground = L.ground_y + h * (0.58 if L.vertical else 0.55)
        if layout == "demonstration":
            h *= 0.6 if L.vertical else 0.72
        char_place = Placement(cx, ground, h, facing)
        main_t = b.main_icon.center if b.main_icon is not None else (
            b.chart_center if hasattr(b, "chart_center") else None)  # type: ignore[attr-defined]
        demo = b.demo

        def target_for(kind: Optional[str], at: float) -> Optional[Point]:
            if kind == "up":
                return (cx, L.sy(0.0))
            if kind == "viewer":
                return None
            if demo is not None and kind in (None, "demo", "main"):
                return demo.focus(at + 0.4)
            return main_t

        base_target = target_for("demo" if cd.look_at == "demo" else cd.look_at, 0.0)
        cues = [CharacterCue(cd.action, cd.expression, 0.0, target=base_target if cd.action in
                             ("point", "interact", "look_at") else None)]
        for cs in cd.cues:
            at = L.cue_time(cs.cue, cs.at * L.duration) if cs.cue else cs.at * L.duration
            tgt = target_for(cs.target, at)
            cues.append(CharacterCue(cs.action, cs.expression, at,
                                     target=tgt if cs.action in ("point", "interact", "look_at") else None))
            if cs.action == "surprised":                     # reactions are short: settle back into talking
                cues.append(CharacterCue("talk", "excited", at + 0.9))
        if cd.look_at in ("main", "demo") and base_target is not None and cd.action not in ("point", "interact"):
            cues[0] = CharacterCue("look_at", cd.expression, 0.0, target=base_target)
            cues.insert(1, CharacterCue(cd.action, cd.expression, min(1.2, L.duration * 0.25)))
        cues.sort(key=lambda c: c.start)
        cues = [c for i, c in enumerate(cues) if i == 0 or c.start - cues[i - 1].start > 0.25 or c.start == 0]
        held = None
        props = [o for o in scene.objects if o.role == "prop"]
        if props and cd.action == "hold":
            prop = L.assets.get(props[0].asset)

            def held(ctx: cairo.Context, sk: Skeleton, t: float, _p=prop) -> None:
                _p.draw(ctx, 0, -112 + 4 * math.sin(t * 2), 150, rotation=3 * math.sin(t * 1.5))
        character = CharacterAnimator(place=char_place, cues=cues, char_id=char_id, envelope=envelope, fps=fps,
                                      seed=L.seed + 3, entrance=cd.entrance,
                                      entrance_from="left" if cx < L.W / 2 else "right", held=held)

    _apply_doodles(b, character, char_place)
    _apply_text_overlays(b, layout, character, char_place)
    bg = Background(scene.background, L.W, L.H, seed=L.seed)
    theme = THEMES.get(scene.theme)
    fg = None
    if theme is not None and layout not in ("outro", "hook_title"):
        fg = _Foreground(kind=theme.foreground, W=L.W, H=L.H, z=20)
        fg.unit, fg.seed = L.u, L.seed
    return SceneComposition(ctx_info=L, background=bg, elements=b.elements, character=character, char_z=5,
                            camera_move=scene.camera.move, camera_intensity=scene.camera.intensity,
                            events=b.events, focus_keys=b.focus_keys,
                            focus_fn=b.demo.focus if b.demo is not None else None, foreground=fg)
