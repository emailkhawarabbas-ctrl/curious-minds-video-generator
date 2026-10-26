"""Beat scheduler: the frame must never stay static for long.

Given what a scene already shows (element entrances, camera punches), the scheduler finds
every gap longer than ``beats.max_gap_s`` and fills it with secondary motion, rotating
through: a keyword sticker of the word being spoken, a hand-drawn circle around the
subject, an arrow pointing at it, a sparkle burst, and a squash-and-stretch bounce with a
camera punch-in. Beats are timed to the narration and leave again, so the frame does not
fill up with clutter.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from src.animation.doodle_engine import Arrow, Burst, CircleHighlight, Doodle, IconPop, PopText, Sparkle
from src.lively.camera import LivelyCamera
from src.lively.style import Style

Point = Tuple[float, float]

STOPWORDS = set("""a an and are as at be been but by can could did do does doing for from had has have he her his
how i if in into is it its just like may me more most my no not now of on one or our out over she so some such
than that the their them then there these they this those through to too up us very was we were what when where
which while who why will with would you your yours really even also only still every each about after before
because during again""".split())

KINDS = ("keyword", "circle", "squash", "arrow", "burst")
STICKER_COLORS = ("yellow", "teal_light", "pink", "orange", "lavender")
BEAT_SFX = {"keyword": ("pop", -4.0), "circle": ("click", -3.0), "arrow": ("whoosh", -9.0),
            "burst": ("sparkle", -6.0), "squash": ("boing", -10.0)}


@dataclass
class WordT:
    word: str
    start: float
    end: float


@dataclass
class BeatPlan:
    W: int
    H: int
    duration: float
    words: Sequence[WordT]
    style: Style
    camera: LivelyCamera
    main: Optional[IconPop] = None
    sticker_spots: List[Point] = field(default_factory=list)   # where keyword stickers go
    arrow_spots: List[Point] = field(default_factory=list)     # where arrows start (free space)
    busy: List[float] = field(default_factory=list)            # times something already happens
    seed: int = 0
    edge_margin: float = 0.35                                   # keep clear of transitions at both ends

    @property
    def u(self) -> float:
        return min(self.W, self.H) / 1080


def content_words(words: Sequence[WordT]) -> List[WordT]:
    out = []
    for w in words:
        tok = re.sub(r"[^A-Za-z0-9']", "", w.word).lower()
        if (len(tok) >= 4 and tok not in STOPWORDS) or re.search(r"\d", tok):
            out.append(w)
    return out


def auto_emphasis(words: Sequence[WordT], every_s: float = 4.0) -> List[WordT]:
    """Pick about one emphasis word per `every_s` seconds: numbers first, then long content words."""
    cands = content_words(words)
    if not cands:
        return []
    span = (words[-1].end - words[0].start) if words else 0.0
    n = max(1, int(span / every_s + 0.5))
    def score(w: WordT) -> float:
        tok = re.sub(r"[^A-Za-z0-9']", "", w.word)
        return (10 if re.search(r"\d", tok) else 0) + len(tok) + (3 if w.word.rstrip().endswith("!") else 0)
    picked: List[WordT] = []
    for k in range(n):
        lo = words[0].start + span * k / n
        hi = words[0].start + span * (k + 1) / n
        window = [w for w in cands if lo <= w.start < hi]
        if window:
            picked.append(max(window, key=score))
    return picked


def _word_near(words: Sequence[WordT], t: float, used: set) -> Optional[WordT]:
    near = [w for w in content_words(words) if -0.2 <= w.start - t <= 0.9 and w.word not in used]
    return max(near, key=lambda w: len(w.word)) if near else None


def schedule(plan: BeatPlan) -> Tuple[List[Doodle], List[Tuple[float, str, float]], List[Dict]]:
    """Return (new elements, sfx events (time, name, gain_db), beat log)."""
    cfg = plan.style.beats
    d = plan.duration
    lo, hi = plan.edge_margin, d - plan.edge_margin
    busy = sorted(t for t in plan.busy if 0 <= t <= d)
    anchors = [0.0] + [t for t in busy if t > 0] + [hi]
    slots: List[float] = []
    for a, b in zip(anchors, anchors[1:]):
        t = a
        while b - t > cfg.max_gap_s:
            t += cfg.target_gap_s
            if t > b - 0.45:
                break
            slots.append(t)
    rnd = random.Random(plan.seed * 7 + 1)
    order = list(KINDS)
    rnd.shuffle(order)
    elements: List[Doodle] = []
    sfx: List[Tuple[float, str, float]] = []
    log: List[Dict] = []
    used_words: set = set()
    k = 0
    for t in slots:
        if not lo <= t <= hi:
            continue
        for attempt in range(len(order)):
            kind = order[(k + attempt) % len(order)]
            made = _make(kind, t, plan, rnd, used_words, k)
            if made is not None:
                elements += made
                name, gain = BEAT_SFX[kind]
                sfx.append((t, name, gain))
                log.append({"t": round(t, 2), "kind": kind})
                k += attempt + 1
                break
    return elements, sfx, log


def _make(kind: str, t: float, plan: BeatPlan, rnd: random.Random, used: set, k: int) -> Optional[List[Doodle]]:
    u, st, main = plan.u, plan.style, plan.main
    end = min(t + 1.35, plan.duration - 0.3)
    spots = plan.sticker_spots or [(plan.W * 0.5, plan.H * 0.2)]
    spot = spots[k % len(spots)]
    if kind == "keyword":
        w = _word_near(plan.words, t, used)
        if w is None:
            return None
        used.add(w.word)
        text = re.sub(r"[^A-Za-z0-9'%\-]", "", w.word).upper()
        if not text:
            return None
        start = max(t, w.start - 0.05)
        return [PopText(text=text, center=spot, size=104, max_width=plan.W / u * 0.62, max_lines=1,
                        start=start, end=min(start + 1.2, plan.duration - 0.3), per_word=0.0, tilt=rnd.uniform(-7, 7),
                        colors=(STICKER_COLORS[k % len(STICKER_COLORS)],), z=9)]
    if main is None:
        return None
    (cx, cy), h = main.current_center(t), main.current_height(t)
    w_ = h * (main.asset.aspect if main.asset else 1.0)
    if kind == "circle":
        return [CircleHighlight(center=(cx, cy), rx=w_ * 0.62, ry=h * 0.6, color=st.palette.rgb("highlight"),
                                width=11, start=t, duration=0.45, end=end, z=4)]
    if kind == "squash":
        main.accents = tuple(sorted(set(main.accents) | {t}))
        plan.camera.punches.append(t)
        return []
    if kind == "arrow":
        sx, sy = (plan.arrow_spots or spots)[k % len(plan.arrow_spots or spots)]
        dx, dy = cx - sx, cy - sy
        dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
        reach = max(0.0, dist - max(w_, h) * 0.55)
        ex, ey = sx + dx / dist * reach, sy + dy / dist * reach
        if reach < 80 * u:
            return None
        return [Arrow(p0=(sx, sy), p1=(ex, ey), bend=rnd.choice((-0.3, 0.3)), color=st.palette.accent(k),
                      width=12, head=44, start=t, duration=0.4, end=end, z=6)]
    if kind == "burst":
        out: List[Doodle] = [Burst(center=(cx, cy), r0=max(w_, h) * 0.52 / u, r1=max(w_, h) * 0.78 / u, rays=12,
                                   color=st.palette.accent(k + 2), width=9, start=t, duration=0.35, z=2)]
        for i in range(3):
            ang = rnd.uniform(0, 6.28)
            out.append(Sparkle(center=(cx + w_ * 0.55 * math.cos(ang),
                                       cy + h * 0.5 * math.sin(ang)),
                               radius=30, start=t + 0.08 * i, end=end, z=6, color=(1, 1, 1) if i % 2 else
                               st.palette.accent(i)))
        return out
    return None
