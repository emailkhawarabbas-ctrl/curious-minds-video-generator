"""Lively scene composition.

* ``compose_spotlight`` builds the script-mode "spotlight" layout: one big visual, a large
  host whose position and pose change from scene to scene, a headline sticker, extra visuals,
  then the beat scheduler fills every quiet gap.
* ``enhance_classic`` gives any classic layout (topic mode, ``--style lively``) the lively
  treatment: paper background, continuous camera, boil, pop-in easing and beats.

Both return a :class:`LivelyComposition` with the same ``draw(ctx, t)`` / ``events`` interface
as the classic ``SceneComposition``, so the renderer treats them alike.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cairo

from src.animation.backgrounds import Background
from src.animation.character_engine import CharacterAnimator, CharacterCue
from src.animation.character_rig import Placement
from src.animation.doodle_engine import Doodle, IconPop, Sparkle, rounded_rect
from src.animation.easing import clamp, ease_pop
from src.animation.palette import PALETTE
from src.animation.text_render import TextStyle, draw_lines, fit_size
from src.content.models import Scene
from src.lively.beats import BeatPlan, WordT, auto_emphasis, schedule
from src.lively.camera import LivelyCamera
from src.lively.style import Style, get_style
from src.lively.transitions import Phase, draw_stage_with_transition, lively_kind, phase_at

Point = Tuple[float, float]
PAPER_SEED = 7          # one sheet of paper for the whole video, so cuts and whips feel continuous

ENTRANCE = {"draw_on": "draw", "pop_in": "pop_in", "bounce": "bounce", "slide_in": "slide_in", "spin_in": "spin",
            "fade_in": "fade"}
CLASSIC_TO_LIVELY_CAMERA = {"zoom_in": "zoom_in", "zoom_out": "zoom_out", "pan_left": "pan_left",
                            "pan_right": "pan_right", "drift": "drift", "static": "drift", "punch_in": "zoom_in",
                            "shake": "drift", "focus": "drift", "follow": "drift", "reveal": "zoom_out"}


@lru_cache(maxsize=4)
def paper_background(W: int, H: int) -> Background:
    return Background("doodle_paper", W, H, seed=PAPER_SEED)


# --------------------------------------------------------------------------- composition
@dataclass
class LivelyComposition:
    W: int
    H: int
    fps: int
    duration: float
    background: Background
    elements: List[Doodle]
    character: Optional[CharacterAnimator]
    camera: LivelyCamera
    style: Style
    char_z: int = 5
    events: List[Tuple[float, str]] = field(default_factory=list)
    sfx_gains: Dict[int, float] = field(default_factory=dict)     # index in events -> gain dB
    transition_in: str = "cut"
    transition_out: str = "cut"
    seed: int = 0
    post: List[Callable[[cairo.Context, float], None]] = field(default_factory=list)
    foreground: Optional[Doodle] = None
    classic_camera: Optional[Callable[[float], Tuple[float, float, float]]] = None
    beats: List[Dict] = field(default_factory=list)
    loop_into: Optional["LivelyComposition"] = None   # last scene of a looping video: flows into scene 1
    loop_t0: float = 0.0                              # scene-1 time shown by the video's first frame

    @property
    def half(self) -> float:
        return self.style.transitions.duration_s / 2

    def _stage(self, ctx: cairo.Context, t: float) -> None:
        ctx.save()
        self.camera.apply(ctx, t)
        if self.classic_camera is not None:          # topic mode: keep the classic focus/follow glide
            s, dx, dy = self.classic_camera(t)
            ctx.translate(self.W / 2 + dx, self.H / 2 + dy)
            ctx.scale(s, s)
            ctx.translate(-self.W / 2, -self.H / 2)
        drawn_char = False
        for el in sorted(self.elements, key=lambda e: e.z):
            if getattr(el, "hud", False):
                continue
            if not drawn_char and el.z >= self.char_z and self.character is not None:
                self.character.draw(ctx, t, self.duration)
                drawn_char = True
            el.draw(ctx, t)
        if not drawn_char and self.character is not None:
            self.character.draw(ctx, t, self.duration)
        for fn in self.post:
            fn(ctx, t)
        ctx.restore()
        hud = [el for el in self.elements if getattr(el, "hud", False)]
        if hud:                                      # headlines follow the camera only a little: always readable
            ctx.save()
            self.camera.apply(ctx, t, depth=0.25)
            for el in sorted(hud, key=lambda e: e.z):
                el.draw(ctx, t)
            ctx.restore()

    def draw(self, ctx: cairo.Context, t: float, reveal: Optional[Phase] = None) -> None:
        if reveal is None and self.loop_into is not None and t >= self.duration - self.half:
            # final half-transition of a looping video: reveal scene 1 as it looks just before frame 0
            last = self.duration - 1.0 / self.fps                # the reveal is complete on the final frame
            q = clamp((last - t) / max(1e-3, self.half - 1.0 / self.fps))
            self.loop_into.draw(ctx, self.loop_t0 - (self.duration - t),
                                reveal=Phase(lively_kind(self.transition_out), "in", q))
            return
        if reveal is not None:
            ph: Optional[Phase] = reveal
        else:
            # a looping last scene plays its "out" half one half-transition early
            dur = self.duration - (self.half if self.loop_into is not None else 0.0)
            ph = phase_at(t, dur, self.transition_in, self.transition_out, self.half)
        ctx.save()
        self.camera.apply(ctx, t, depth=0.35)
        self.background.draw(ctx, t)
        ctx.restore()
        draw_stage_with_transition(ctx, lambda c: self._stage(c, t), ph, self.W, self.H, self.fps, self.style,
                                   self.seed)
        if self.foreground is not None:
            ctx.save()
            self.camera.apply(ctx, t, depth=1.3)
            self.foreground.draw(ctx, t)
            ctx.restore()


# --------------------------------------------------------------------------- stickers
@dataclass
class HeadlineSticker(Doodle):
    """Big bold text on a tilted colour tape; pops in 0 -> 1.1 -> 1.0 and keeps a gentle wobble."""
    text: str = ""
    center: Point = (0, 0)
    max_width: float = 900
    color: Tuple[float, float, float] = PALETTE["coral"]
    font: str = "Luckiest Guy"
    size: float = 92
    tilt: float = -3.0
    hud: bool = True              # drawn on the low-parallax layer (see LivelyComposition._stage)

    def draw(self, ctx, t):
        if not self.visible(t) or not self.text:
            return
        u = self.unit
        p = ease_pop(clamp((t - self.start) / self.duration)) * self.exit_factor(t)
        if p <= 0.01:
            return
        st = TextStyle(font=self.font, size=self.size * u, color=(1, 1, 1), outline=PALETTE["ink"],
                       outline_width=self.size * u * 0.16, shadow=False)
        size, lines = fit_size(ctx, self.text, st, self.max_width * u - 70 * u, 2, 34 * u)
        st.size, st.outline_width = size, size * 0.16
        ctx.select_font_face(self.font)
        ctx.set_font_size(size)
        w = max(ctx.text_extents(ln).x_advance for ln in lines) + 70 * u
        h = size * 1.12 * len(lines) + 44 * u
        ctx.save()
        ctx.translate(*self.center)
        ctx.rotate(math.radians(self.tilt + 1.4 * math.sin(t * 2.1 + self.seed)))
        ctx.scale(p, p)
        rounded_rect(ctx, -w / 2 + 9 * u, -h / 2 + 11 * u, w, h, 26 * u)
        ctx.set_source_rgba(*PALETTE["ink"], 0.9)
        ctx.fill()
        rounded_rect(ctx, -w / 2, -h / 2, w, h, 26 * u)
        ctx.set_source_rgb(*self.color)
        ctx.fill_preserve()
        ctx.set_source_rgb(*PALETTE["ink"])
        ctx.set_line_width(7 * u)
        ctx.stroke()
        draw_lines(ctx, lines, 0, -h / 2 + 22 * u, st)
        ctx.restore()


# --------------------------------------------------------------------------- spotlight layout
@dataclass
class Frame:
    """Where things go for one host position."""
    host: Optional[Tuple[float, float, float, int]]   # x, ground y, height, facing
    main: Tuple[float, float, float]                   # cx, cy, height
    headline: Point
    extras: List[Point]                                # free spots for extra visuals / arrow tails


def spotlight_frame(W: int, H: int, position: str, present: bool, has_headline: bool, host_scale: float,
                    caption_y: float) -> Frame:
    if H > W:                                           # vertical 9:16
        head_y = H * 0.165
        shift = 0.0 if has_headline else -0.04 * H
        if not present:
            return Frame(None, (W * 0.5, H * 0.42 + shift, H * 0.42), (W * 0.5, head_y),
                         [(W * 0.2, H * 0.26), (W * 0.8, H * 0.26)])
        if position in ("left", "right"):
            right = position == "right"
            hx = W * (0.70 if right else 0.27)
            mx = W * (0.36 if right else 0.65)
            return Frame((hx, H * 0.86, H * 0.46 * host_scale, -1 if right else 1),
                         (mx, H * 0.37 + shift, H * 0.33), (W * 0.5, head_y),
                         [(W * (0.78 if right else 0.22), H * 0.29 + shift)])
        if position in ("corner_left", "corner_right"):
            right = position == "corner_right"
            return Frame((W * (0.79 if right else 0.19), H * 0.84, H * 0.31 * host_scale, -1 if right else 1),
                         (W * 0.52, H * 0.43 + shift, H * 0.40), (W * 0.5, head_y),
                         [(W * (0.22 if right else 0.8), H * 0.66), (W * (0.2 if right else 0.82), H * 0.27)])
        # center / closeup: host big and waist-up at the bottom, visual above the head
        h = H * 0.80 * host_scale
        return Frame((W * 0.5, H * 0.50 + h, h, 1), (W * 0.5, H * 0.335 + shift, H * 0.25), (W * 0.5, head_y),
                     [(W * 0.18, H * 0.42), (W * 0.82, H * 0.42)])
    # horizontal 16:9
    head_y = H * 0.13
    if not present:
        return Frame(None, (W * 0.5, H * 0.47, H * 0.6), (W * 0.5, head_y), [(W * 0.2, H * 0.5), (W * 0.8, H * 0.5)])
    right = position in ("right", "corner_right")
    small = position in ("corner_left", "corner_right")
    hx = W * ((0.84 if small else 0.78) if right else (0.16 if small else 0.22))
    hh = H * (0.6 if small else 0.86) * host_scale
    mx = W * (0.42 if right else 0.58)
    return Frame((hx, H * 1.0, hh, -1 if right else 1), (mx, H * 0.5, H * (0.62 if small else 0.56)),
                 (mx, head_y), [(W * (0.82 if not right else 0.18), H * 0.3)])


def _cue_time(words: Sequence[WordT], cue: Optional[str], default: float) -> float:
    if not cue:
        return default
    target = re.findall(r"[a-z0-9']+", cue.lower())
    toks = [re.sub(r"[^a-z0-9']", "", w.word.lower()) for w in words]
    for i in range(len(toks) - len(target) + 1):
        if target and all(toks[i + k].startswith(target[k]) for k in range(len(target))):
            return max(0.0, words[i].start - 0.08)
    return default


def compose_spotlight(scene: Scene, L, envelope: Optional[Sequence[float]] = None, fps: int = 30,
                      char_id: Optional[str] = None, style: Optional[Style] = None,
                      first: bool = False) -> LivelyComposition:
    """`first` = the video's opening scene: content is on screen from frame 0 (the hook)."""
    st = style or get_style()
    W, H, u = L.W, L.H, L.u
    lv = scene.lively
    words = [WordT(w.word, w.start, w.end) for w in L.words]
    cd = scene.character
    headline = (lv.headline if lv else None) or next((o.text for o in scene.text_overlays if o.style == "title"), None)
    cap_y = H * (st.captions.center_y if H > W else st.captions.center_y_horizontal)
    fr = spotlight_frame(W, H, cd.position, cd.present, bool(headline), st.host.scale, cap_y)
    elements: List[Doodle] = []
    events: List[Tuple[float, str]] = []
    gains: Dict[int, float] = {}
    seed = L.seed

    def add(el: Doodle, sfx: Optional[str] = None, gain: float = 0.0) -> Doodle:
        nonlocal seed
        seed += 1
        el.unit, el.seed = u, seed
        elements.append(el)
        if sfx and el.start < L.duration - 0.4:
            gains[len(events)] = gain
            events.append((max(0.0, el.start), sfx))
        return el

    t0 = 0.0 if first else st.transitions.duration_s / 2 * 0.6       # content enters as the transition reveals
    busy: List[float] = []
    if headline:
        add(HeadlineSticker(text=headline.upper(), center=fr.headline, start=t0, duration=st.animation.pop_s,
                            max_width=W / u * 0.86, color=st.palette.accent(seed // 7), font=st.fonts.headline,
                            tilt=-3 if seed % 2 else 2.5, z=9), "pop", -2.0)
        busy.append(t0)
    main_spec = next(o for o in scene.objects if o.role == "main")
    anim = lv.animation if lv else "pop_in"
    ent = ENTRANCE[anim]
    asset = L.assets.get(main_spec.asset)
    mx, my, mh = fr.main
    max_w = W * (0.66 if H > W else 0.42)
    mh = min(mh, max_w / max(asset.aspect, 0.01))
    m_start = _cue_time(words, main_spec.cue, t0 + (0.12 if headline else 0.0))
    main = IconPop(asset=asset, center=(mx, my), height=mh, start=m_start,
                   duration=st.animation.draw_on_s if ent == "draw" else st.animation.pop_s, entrance=ent,
                   idle="float", z=3, fill_start=0.7, overshoot=st.animation.pop_overshoot,
                   boil=st.animation.boil_amount, boil_fps=st.animation.boil_fps, float_amount=st.animation.idle_bob,
                   slide_from=1.0 if fr.host and fr.host[0] < W / 2 else -1.0,
                   highlight_groups=tuple(main_spec.highlight) or None, highlight_start=m_start + 1.2)
    add(main, {"draw": "sparkle", "slide_in": "whoosh"}.get(ent, "pop"), -1.0)
    busy.append(m_start)
    if ent == "draw":
        busy.append(m_start + st.animation.draw_on_s * 0.7)    # the fill-in is a second visible change
    # extra visuals, revealed one by one through the narration
    extras = [o.asset for o in scene.objects if o.role != "main"] + (lv.visuals if lv else [])
    spots = list(fr.extras)
    n = len(extras)
    for i, a_id in enumerate(extras[:3]):
        a = L.assets.get(a_id)
        spot = spots[i % len(spots)]
        spots_left = [s for s in spots if s != spot]
        lo = L.speech_start + (L.speech_end - L.speech_start) * 0.2
        hi = L.speech_start + (L.speech_end - L.speech_start) * 0.75
        t_e = lo + (hi - lo) * (i / max(1, n - 1)) if n > 1 else (lo + hi) / 2
        t_e = _cue_time(words, a_id.replace("_", " ").split()[0], t_e)
        eh = min(H * (0.14 if H > W else 0.24), W * 0.3 / max(a.aspect, 0.01))
        add(IconPop(asset=a, center=spot, height=eh, start=t_e, duration=st.animation.pop_s, entrance="pop_in",
                    idle="wiggle", z=4, overshoot=st.animation.pop_overshoot, boil=st.animation.boil_amount,
                    boil_fps=st.animation.boil_fps), "pop", -3.0)
        add(Sparkle(center=(spot[0] + eh * 0.45, spot[1] - eh * 0.45), radius=26, start=t_e + 0.15, z=5))
        busy.append(t_e)
        spots = spots_left or spots
    # host
    character = None
    if fr.host is not None:
        hx, gy, hh, facing = fr.host
        target = (mx, my)
        cues = [CharacterCue(cd.action, cd.expression, 0.0,
                             target=target if cd.action in ("point", "interact", "look_at") else None)]
        for cs in cd.cues:
            at = _cue_time(words, cs.cue, cs.at * L.duration) if cs.cue else cs.at * L.duration
            cues.append(CharacterCue(cs.action, cs.expression, at,
                                     target=target if cs.action in ("point", "interact", "look_at") else None))
            busy.append(at)
            if cs.action in ("surprised", "excited"):
                cues.append(CharacterCue("talk", "happy", at + 1.0))
        cues.sort(key=lambda c: c.start)
        cues = [c for i, c in enumerate(cues) if i == 0 or c.start - cues[i - 1].start > 0.25]
        character = CharacterAnimator(place=Placement(hx, gy, hh, facing), cues=cues,
                                      char_id=char_id or cd.character, envelope=envelope, fps=fps, seed=L.seed + 3,
                                      entrance="pop" if first else "none",
                                      entrance_from="left" if hx < W / 2 else "right")
    # camera: continuous move + punch-ins on emphasised words + optional shake
    emph = [w for w in (lv.emphasis if lv else [])]
    punches = [_cue_time(words, w, -1.0) + 0.08 for w in emph]
    punches = [p for p in punches if p > 0]
    if not punches:
        punches = [w.start for w in auto_emphasis(words, 3.5)]
    cam = LivelyCamera(lv.camera if lv else "zoom_in", L.duration, W, H, st.camera, pivot=(mx, my),
                       punches=punches, shakes=([punches[0] if punches else 0.15] if lv and lv.shake else []),
                       seed=L.seed)
    main.accents = tuple(punches)
    busy += punches
    # beats: fill every gap > max_gap with secondary motion
    # keyword stickers sit under the visual like a label; arrows start from the free side
    under = (mx, min(my + mh * 0.55, cap_y - 150 * u))
    plan = BeatPlan(W=W, H=H, duration=L.duration, words=words, style=st, camera=cam, main=main,
                    sticker_spots=[under], arrow_spots=list(fr.extras), busy=busy, seed=L.seed)
    new, sfx, log = schedule(plan)
    for el in new:
        add(el)
    for t, name, gain in sfx:
        gains[len(events)] = gain
        events.append((t, name))
    return LivelyComposition(W=W, H=H, fps=fps, duration=L.duration, background=paper_background(W, H),
                             elements=elements, character=character, camera=cam, style=st, events=events,
                             sfx_gains=gains, transition_in=scene.transition_in, transition_out=scene.transition_out,
                             seed=L.seed, beats=log)


# --------------------------------------------------------------------------- classic layouts, lively treatment
def enhance_classic(comp, scene: Scene, L, style: Optional[Style] = None) -> LivelyComposition:
    """Wrap a classic SceneComposition with the lively look (topic mode, --style lively)."""
    st = style or get_style()
    W, H = L.W, L.H
    words = [WordT(w.word, w.start, w.end) for w in L.words]
    main: Optional[IconPop] = None
    for el in comp.elements:
        if type(el).__name__ in ("PopText", "_TitleBanner", "Counter"):
            el.hud = True                            # big titles / numbers stay readable under the zoom
        if isinstance(el, IconPop):
            el.boil, el.boil_fps = st.animation.boil_amount, st.animation.boil_fps
            if el.entrance == "pop":
                el.entrance, el.overshoot = "pop_in", st.animation.pop_overshoot
            if el.entrance == "draw":
                el.fill_start = 0.7
            if main is None and el.z >= 3:
                main = el
    move = CLASSIC_TO_LIVELY_CAMERA.get(scene.camera.move, "drift")
    punches = [w.start for w in auto_emphasis(words, 3.5)]
    if scene.camera.move == "punch_in":
        punches.insert(0, 0.25)
    shakes = [0.2] if scene.camera.move == "shake" else []
    pivot = main.center if main is not None else (W / 2, H * 0.42)
    cam = LivelyCamera(move, L.duration, W, H, st.camera, pivot=pivot, punches=punches, shakes=shakes, seed=L.seed,
                       intensity=0.45 if scene.camera.move in ("focus", "follow", "reveal") else 0.7)
    classic_cam = None
    if scene.camera.move in ("focus", "follow", "reveal"):
        classic_cam = comp.camera
    if main is not None:
        main.accents = tuple(punches)
    busy = [el.start for el in comp.elements if el.start < L.duration] + punches
    busy += [t for t, _ in comp.events]
    plan = BeatPlan(W=W, H=H, duration=L.duration, words=words, style=st, camera=cam, main=main,
                    sticker_spots=[(W * 0.5, H * (0.2 if H > W else 0.16)), (W * 0.5, L.caption_top - 80 * L.u)],
                    busy=busy, seed=L.seed)
    new, sfx, log = schedule(plan)
    elements = list(comp.elements)
    for el in new:
        el.unit = L.u
        elements.append(el)
    events = list(comp.events)
    gains: Dict[int, float] = {}
    for t, name, gain in sfx:
        gains[len(events)] = gain
        events.append((t, name))
    return LivelyComposition(W=W, H=H, fps=comp.character.fps if comp.character else 30, duration=L.duration,
                             background=paper_background(W, H), elements=elements, character=comp.character,
                             camera=cam, style=st, char_z=comp.char_z, events=events, sfx_gains=gains,
                             transition_in=scene.transition_in, transition_out=scene.transition_out, seed=L.seed,
                             post=list(comp.post), foreground=comp.foreground, classic_camera=classic_cam, beats=log)


def compose_lively(scene: Scene, L, envelope: Optional[Sequence[float]] = None, fps: int = 30,
                   char_id: Optional[str] = None, first: bool = False,
                   style: Optional[Style] = None) -> LivelyComposition:
    """Entry point used by the renderer for lively storyboards (any layout)."""
    if scene.layout == "spotlight":
        return compose_spotlight(scene, L, envelope, fps, char_id, style, first=first)
    from src.animation.scene_engine import compose_scene
    return enhance_classic(compose_scene(scene, L, envelope, fps, char_id), scene, L, style)
