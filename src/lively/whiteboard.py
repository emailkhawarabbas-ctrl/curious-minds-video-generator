"""Whiteboard explainer scenes (script mode's default look).

One pen draws everything, in order: the headline (if any), the main visual stroke by stroke,
extra visuals, then the scene's keyword in handwriting. A visible hand holds the pen; when the
host's action is ``draw`` the host writes the keyword itself with a marker. While the hand
draws, the host watches the drawing; when it is done the host acts (thinks, counts on its
fingers, reacts, shrugs, holds something up, explains). Quiet gaps get a quick pen beat
(circle, arrow, underline, emphasis rays) so the frame never stays still for long.

The camera is calm: a slow 3-5 % zoom per scene, at most one smooth punch-in, no shake
unless the script asks. All values live in ``config/style.yaml`` under ``whiteboard``.
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Sequence, Tuple

from src.animation.character_engine import MARKER_REACH, CharacterAnimator, CharacterCue
from src.animation.character_rig import Placement, load_character
from src.animation.doodle_engine import Doodle, IconPop
from src.animation.easing import clamp
from src.content.models import Scene
from src.lively.beats import WordT, auto_emphasis
from src.lively.camera import LivelyCamera
from src.lively.composer import ENTRANCE, LivelyComposition, _cue_time, paper_background, spotlight_frame
from src.lively.drawing import (DrawingHand, DrawnSvg, HandText, PenDrawing, PenPath, PenStroke, arrow_strokes,
                                ellipse_stroke)
from src.lively.style import Style, get_style

Point = Tuple[float, float]
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "first": 1, "second": 2, "third": 3, "twice": 2,
                "double": 2, "triple": 3}
FILLERS = ("circle", "rays", "arrow", "underline")
SCRIBBLE_EVERY = 1.2        # the scribble sample is ~1.3 s; repeat it through long drawings


def count_target(text: str) -> Tuple[int, Optional[str]]:
    """How many fingers to count to and the word that starts the count (1-3, else 3)."""
    for w in re.findall(r"[A-Za-z0-9']+", text):
        lw = w.lower()
        if lw in NUMBER_WORDS:
            return NUMBER_WORDS[lw], w
        if lw.isdigit() and 1 <= int(lw) <= 3:
            return int(lw), w
    return 3, None


def wrap_balanced(text: str, max_chars: int) -> str:
    """Up to two lines of about equal length."""
    if len(text) <= max_chars:
        return text
    words = text.split()
    best, best_d = text, 1e9
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        d = abs(len(a) - len(b))
        if d < best_d:
            best, best_d = a + "\n" + b, d
    return best


def _text_width(text: str, font: str, size: float) -> float:
    import cairo
    c = cairo.Context(cairo.ImageSurface(cairo.FORMAT_A8, 4, 4))
    c.select_font_face(font)
    c.set_font_size(size)
    return max(c.text_extents(ln).x_advance for ln in text.split("\n"))


def fit_hand_text(text: str, font: str, size: float, max_w: float, min_size: float) -> float:
    while size > min_size and _text_width(text, font, size) > max_w:
        size *= 0.92
    return max(size, min_size)


def _scribbles(events: List[Tuple[float, str]], gains: Dict[int, float], d: PenDrawing, gain: float,
               scene_end: float) -> None:
    t = d.t_first
    while t < d.t_last - 0.3 and t < scene_end - 0.5:
        gains[len(events)] = gain
        events.append((t, "scribble"))
        t += SCRIBBLE_EVERY


def compose_whiteboard(scene: Scene, L, envelope: Optional[Sequence[float]] = None, fps: int = 30,
                       char_id: Optional[str] = None, style: Optional[Style] = None,
                       first: bool = False) -> LivelyComposition:
    st = style or get_style()
    wb, dr = st.whiteboard, st.whiteboard.drawing
    W, H, u = L.W, L.H, L.u
    D = L.duration
    lv = scene.lively
    cd = scene.character
    words = [WordT(w.word, w.start, w.end) for w in L.words]
    ink, hi = st.palette.rgb("ink"), st.palette.rgb("highlight")
    headline = lv.headline if lv else None
    cap_y = H * (st.captions.center_y if H > W else st.captions.center_y_horizontal)
    cap_clear = cap_y - st.captions.size * u * 1.3      # top of a two-line caption block: labels stay above
    fr = spotlight_frame(W, H, cd.position, cd.present, bool(headline), st.host.scale, cap_y)
    host_char = char_id or cd.character
    elements: List[Doodle] = []
    events: List[Tuple[float, str]] = []
    gains: Dict[int, float] = {}
    pen: List[PenDrawing] = []
    seed = L.seed
    end_by = D - 0.35                                   # leave the transition alone

    def add(el: Doodle) -> Doodle:
        nonlocal seed
        seed += 1
        el.unit, el.seed = u, seed
        elements.append(el)
        return el

    t0 = 0.0 if first else st.transitions.duration_s / 2 * 0.6
    cursor = t0
    # 1. headline, handwritten across the top
    if headline:
        text = wrap_balanced(headline, 22)
        size = fit_hand_text(text, dr.text_font, dr.text_size * u * 1.05, W * 0.84, 40 * u)
        n = len(headline)
        ht = HandText(text=text, center=fr.headline, size=size, font=dr.text_font, color=ink,
                      underline=hi if dr.underline else None, z=2, lift_s=0.03)
        ht.plan(cursor, clamp(n * dr.text_s_per_char * (0.6 if first else 1.0), 0.6, 1.8))
        add(ht)
        pen.append(ht)
        cursor = ht.t_last + 0.12
    # 2. main visual, drawn stroke by stroke (or a calm pop / slide when the script asks for it)
    main_spec = next(o for o in scene.objects if o.role == "main")
    anim = lv.animation if lv else "draw_on"
    asset = L.assets.get(main_spec.asset)
    mx, my, mh = fr.main
    mh = min(mh, W * (0.66 if H > W else 0.42) / max(asset.aspect, 0.01))
    if anim == "draw_on":
        total = clamp(dr.scene_fraction * D - (cursor - t0), dr.min_s, dr.max_s)
        main: Doodle = DrawnSvg(asset=asset, center=(mx, my), height=mh, outline_fills=dr.outline_fills,
                                boil=dr.boil_amount, boil_fps=dr.boil_fps, fill_s=dr.fill_s, lift_s=dr.lift_s, z=3)
        main.plan(cursor, max(0.5, total - dr.fill_s))
        pen.append(main)
        main_done = main.done_at
        pen_free = main.t_last + 0.12
    else:
        main = IconPop(asset=asset, center=(mx, my), height=mh, start=cursor, duration=st.animation.pop_s,
                       entrance=ENTRANCE[anim], idle="none", z=3, overshoot=st.animation.pop_overshoot,
                       boil=dr.boil_amount, boil_fps=dr.boil_fps,
                       slide_from=1.0 if fr.host and fr.host[0] < W / 2 else -1.0)
        events.append((cursor, {"slide_in": "whoosh"}.get(anim, "pop")))
        main_done = cursor + st.animation.pop_s
        pen_free = main_done
    add(main)
    cursor = pen_free
    # 3. extra visuals: drawn small in the free spots (the first one is held up instead for hold_up)
    extras = [o.asset for o in scene.objects if o.role != "main"] + (lv.visuals if lv else [])
    action = cd.action if cd.present else "none"
    prop = None
    if action == "hold_up" and extras:
        prop = L.assets.get(extras.pop(0))
    spots = list(fr.extras)
    for i, a_id in enumerate(extras[:2]):
        a = L.assets.get(a_id)
        eh = min(H * (0.13 if H > W else 0.22), W * 0.28 / max(a.aspect, 0.01))
        dur = 1.0
        if cursor + dur + 0.35 > end_by:
            break
        ex = DrawnSvg(asset=a, center=spots[i % len(spots)], height=eh, outline_fills=dr.outline_fills,
                      boil=dr.boil_amount, boil_fps=dr.boil_fps, fill_s=0.35, lift_s=0.04, z=2)
        ex.plan(max(cursor, _cue_time(words, a_id.replace("_", " ").split()[0], cursor)), dur)
        add(ex)
        pen.append(ex)
        cursor = ex.t_last + 0.12
    # 4. the keyword, handwritten (by the host when it is drawing)
    emph = list(lv.emphasis) if lv else []
    head_words = set(re.findall(r"[a-z0-9']+", (headline or "").lower()))
    kw: Optional[WordT] = None
    for e in emph:
        if not set(re.findall(r"[a-z0-9']+", e.lower())) <= head_words:
            t_e = _cue_time(words, e, -1.0)
            kw = WordT(e, max(0.0, t_e), max(0.0, t_e) + 0.4)
            break
    if kw is None and not emph:
        picks = [w for w in auto_emphasis(words, 99.0) if w.word.lower().strip(".,!?") not in head_words]
        if picks:
            kw = WordT(re.sub(r"[^A-Za-z0-9'%\- ]", "", picks[0].word), picks[0].start, picks[0].end)
    host_writes = action == "draw" and wb.host.draw_labels and fr.host is not None
    style_c = load_character(host_char) if fr.host is not None else None
    label: Optional[HandText] = None
    if kw is not None and kw.word.strip():
        text = kw.word.strip().upper()
        if host_writes:
            hx, gy, hh, facing = fr.host
            place = Placement(hx, gy, hh, facing)
            r = style_c.rig
            shx, shy = place.to_world(style_c, tuple(r["shoulder_r"]))
            reach = (r["upper_arm"] + r["forearm"] + 26 + MARKER_REACH) * place.scale(style_c)
            size = fit_hand_text(text, dr.text_font, dr.text_size * u * 0.85, reach * 1.25, 36 * u)
            w = _text_width(text, dr.text_font, size)
            cx = clamp(shx + facing * (reach * 0.55 + w * 0.5), W * 0.1 + w / 2, W * 0.9 - w / 2)
            center = (cx, min(shy - reach * 0.25, cap_clear - size * 0.6))
        else:
            size = fit_hand_text(text, dr.text_font, dr.text_size * u, W * 0.7, 40 * u)
            center = (mx, min(my + mh * 0.5 + size * 0.75, cap_clear - size * 0.6))
        dur = clamp(len(text) * dr.text_s_per_char, 0.5, 1.4)
        start = max(cursor, kw.start - 0.15)
        if start + dur + 0.2 > end_by:
            start = max(cursor, end_by - dur - 0.2)
        if start + dur <= end_by:
            label = HandText(text=text, center=center, size=size, font=dr.text_font, color=ink,
                             underline=hi if dr.underline and not host_writes else None, z=2,
                             by_host=host_writes, lift_s=0.03)
            label.plan(start, dur)
            add(label)
            pen.append(label)
            cursor = label.t_last + 0.12
    # 5. host: watches the drawing, then acts
    character = None
    t_react = main_done
    if fr.host is not None:
        hx, gy, hh, facing = fr.host
        target = (mx, my)
        expr = cd.expression
        cues: List[CharacterCue] = []
        watch = CharacterCue("look_at", "curious", 0.0, target=target)
        if action == "think":
            cues.append(CharacterCue("think", expr if expr != "happy" else "thinking", 0.0))
            cues.append(CharacterCue("point", "happy", t_react + 0.2, target=target))
        elif action == "surprised":
            at = next((_cue_time(words, e, -1.0) for e in emph if _cue_time(words, e, -1.0) > t_react), t_react)
            cues += [watch, CharacterCue("surprised", "surprised", at),
                     CharacterCue("explain", "happy", min(at + 1.3, end_by))]
        elif action == "count":
            n, word = count_target(scene.narration)
            at = max(t_react - 0.3, _cue_time(words, word, t_react) if word else t_react)
            cues += [watch, CharacterCue("count", expr, at, count=n),
                     CharacterCue("explain", "happy", min(at + n * wb.host.count_step_s + 0.9, end_by))]
        elif action == "shrug":
            cues += [watch, CharacterCue("shrug", expr if expr != "happy" else "confused", t_react),
                     CharacterCue("talk", "happy", min(t_react + 1.4, end_by))]
        elif action == "draw" and label is not None and label.by_host:
            lab = label

            def nib(t: float, d: PenDrawing = lab) -> Optional[Point]:
                p = d.pen(t)
                return p[0] if p is not None else None
            cues += [watch, CharacterCue("draw", expr, max(0.0, lab.t_first - 0.35), target_fn=nib),
                     CharacterCue("present", "happy", min(lab.done_at + 0.25, end_by))]
        elif action == "hold_up" and prop is not None:
            cues += [watch, CharacterCue("hold_up", expr if expr != "happy" else "excited", t_react)]
        else:
            act = action if action not in ("draw", "hold_up", "none") else "explain"
            cues += [watch, CharacterCue(act, expr, t_react,
                                         target=target if act in ("point", "interact", "look_at") else None)]
        cues = sorted(cues, key=lambda c: c.start)
        cues = [c for i, c in enumerate(cues) if i == 0 or c.start - cues[i - 1].start > 0.2]
        ent = cd.entrance if cd.entrance in ("walk", "run", "slide", "none") else ("pop" if first else "none")
        character = CharacterAnimator(place=Placement(hx, gy, hh, facing), cues=cues, char_id=host_char,
                                      envelope=envelope, fps=fps, seed=L.seed + 3, entrance=ent,
                                      entrance_from="left" if hx < W / 2 else "right", prop=prop,
                                      exit=cd.exit, exit_to="left" if hx < W / 2 else "right",
                                      count_step=wb.host.count_step_s)
        busy = [c.start for c in cues]
    else:
        busy = []
    # 6. quiet gaps get a quick pen beat
    busy += [d.t_first for d in pen] + [d.done_at for d in pen]
    _fill_gaps(pen, add, busy, main_center=(mx, my), main_size=(mh * asset.aspect, mh), label=label,
               spots=list(fr.extras), color=hi, accent=st.palette.accent(L.seed), u=u, max_gap=st.beats.max_gap_s,
               start=max(t0, main_done), end_by=end_by, seed=L.seed)
    # 7. the hand, the sounds and the camera
    if wb.hand.show:
        add(DrawingHand(drawings=pen, W=W, H=H, size=wb.hand.size * min(W, H), lift_px=wb.hand.lift_px,
                        travel_s=wb.hand.travel_s, rest_after_s=wb.hand.rest_after_s, shadow=wb.hand.shadow,
                        mirror=bool(fr.host and fr.host[0] > W / 2)))
    for d in pen:
        _scribbles(events, gains, d, -11.0 if d is main else -14.0, D)
    if label is not None and label.done_at < end_by:
        gains[len(events)] = -8.0
        events.append((label.done_at - 0.05, "click"))
    punches = [p + 0.08 for p in (_cue_time(words, e, -1.0) for e in emph) if p > 0][:1]
    cam = LivelyCamera(lv.camera if lv else "zoom_in", D, W, H, wb.camera, pivot=(mx, my), punches=punches,
                       shakes=([punches[0] if punches else 0.15] if lv and lv.shake else []), seed=L.seed)
    if isinstance(main, DrawnSvg):
        main.accents = tuple(p for p in punches if p > main.done_at)
    log = [{"t": round(d.t_first, 2), "kind": type(d).__name__, "end": round(d.done_at, 2),
            "by": "host" if d.by_host else "hand"} for d in pen]
    return LivelyComposition(W=W, H=H, fps=fps, duration=D, background=paper_background(W, H), elements=elements,
                             character=character, camera=cam, style=st, events=events, sfx_gains=gains,
                             transition_in=scene.transition_in, transition_out=scene.transition_out, seed=L.seed,
                             beats=log)


def _fill_gaps(pen: List[PenDrawing], add, busy: List[float], main_center: Point, main_size: Point,
               label: Optional[HandText], spots: List[Point], color, accent, u: float, max_gap: float,
               start: float, end_by: float, seed: int) -> None:
    """Add pen beats wherever nothing new happens for longer than ``max_gap``."""
    (cx, cy), (w, h) = main_center, main_size
    k = 0
    while True:
        times = sorted(t for t in busy if start - 0.01 <= t <= end_by)
        anchors = [start] + times + [end_by]
        gap_at = next((a for a, b in zip(anchors, anchors[1:]) if b - a > max_gap), None)
        if gap_at is None or k >= 4:
            return
        t = gap_at + min(0.6, max_gap * 0.4)
        # the hand may still be busy: start after any pen drawing that overlaps t
        for d in pen:
            if d.t_first <= t <= d.t_last:
                t = d.t_last + 0.12
        dur = 0.55
        if t + dur > end_by:
            return
        kind = FILLERS[(k + seed) % len(FILLERS)]
        strokes: List[PenStroke] = []
        if kind == "underline" and label is None:
            kind = "circle"
        if kind == "arrow" and not spots:
            kind = "rays"
        if kind == "circle":
            strokes = [PenStroke(pts=ellipse_stroke(cx, cy, w * 0.6, h * 0.58, seed + k), color=color, width=10 * u)]
        elif kind == "rays":
            ox, oy = cx + w * 0.5, cy - h * 0.5
            for ang in (-0.9, -0.45, 0.0):
                a0 = (ox + math.cos(ang) * 24 * u, oy + math.sin(ang) * 24 * u)
                a1 = (ox + math.cos(ang) * 70 * u, oy + math.sin(ang) * 70 * u)
                strokes.append(PenStroke(pts=[a0, a1], color=accent, width=10 * u))
        elif kind == "arrow":
            sx, sy = spots[k % len(spots)]
            dx, dy = cx - sx, cy - sy
            dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
            reach = dist - max(w, h) * 0.55
            if reach < 80 * u:
                kind = "circle"
                strokes = [PenStroke(pts=ellipse_stroke(cx, cy, w * 0.6, h * 0.58, seed + k), color=color,
                                     width=10 * u)]
            else:
                p1 = (sx + dx / dist * reach, sy + dy / dist * reach)
                strokes = [PenStroke(pts=pts, color=accent, width=10 * u)
                           for pts in arrow_strokes((sx, sy), p1, 0.18 if k % 2 else -0.18, 36 * u)]
        elif kind == "underline":
            strokes = [PenStroke(pts=[(label.center[0] - label.width * 0.55, label.center[1] + label.size * 0.68),
                                      (label.center[0] + label.width * 0.55, label.center[1] + label.size * 0.62)],
                                 color=color, width=label.size * 0.07)]
        d = PenPath(strokes=strokes, z=2, lift_s=0.04, fill_s=0.0)
        d.plan(t, dur)
        add(d)
        pen.append(d)
        pen.sort(key=lambda x: x.t_first)
        busy += [d.t_first, d.done_at]
        k += 1
