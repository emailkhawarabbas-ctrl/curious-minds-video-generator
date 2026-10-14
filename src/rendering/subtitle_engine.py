"""Captions from the actual narration timings: SRT export + burned-in caption rendering.

Chunking:
  * vertical (Shorts/TikTok): punchy 1-line chunks (<= 4 words / 24 chars), big type,
    current word highlighted, positioned above the platform UI zone
  * horizontal (YouTube):     <= 2 lines of <= 42 chars, phrase breaks at punctuation
SRT files always use the readable 2-line phrase chunking.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cairo

from src.animation.doodle_engine import rounded_rect
from src.animation.easing import clamp, ease_out_back
from src.animation.palette import PALETTE
from src.animation.text_render import TextStyle, draw_lines
from src.utils.fonts import CAPTION_FONT


@dataclass
class CapWord:
    text: str
    start: float
    end: float


@dataclass
class CaptionChunk:
    start: float
    end: float
    words: List[CapWord] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def chunk_words(words: Sequence[CapWord], max_words: int, max_chars: int, min_dur: float = 0.7,
                gap_break: float = 0.45) -> List[CaptionChunk]:
    chunks: List[CaptionChunk] = []
    cur: List[CapWord] = []

    def flush() -> None:
        if cur:
            chunks.append(CaptionChunk(cur[0].start, cur[-1].end, list(cur)))
            cur.clear()

    for i, w in enumerate(words):
        if cur:
            text_len = len(" ".join(x.text for x in cur)) + 1 + len(w.text)
            if (len(cur) >= max_words or text_len > max_chars or w.start - cur[-1].end > gap_break):
                flush()
        cur.append(w)
        if re.search(r"[.!?]$", w.text) or (re.search(r"[,;:—]$", w.text) and len(cur) >= max(2, max_words // 2)):
            flush()
    flush()
    # timing: hold each chunk until the next starts (bounded), enforce minimum duration
    for i, c in enumerate(chunks):
        nxt = chunks[i + 1].start if i + 1 < len(chunks) else c.end + 1.0
        c.end = min(max(c.end + 0.15, c.start + min_dur), nxt - 0.02) if nxt - 0.02 > c.start else c.end
    return chunks


def to_srt_time(t: float) -> str:
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    ms = int(round((s - int(s)) * 1000))
    if ms == 1000:
        s, ms = s + 1, 0
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"


def wrap_srt(text: str, width: int = 42) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    if len(lines) > 2:   # rebalance into two lines
        mid = len(words) // 2
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
    return "\n".join(lines)


def write_srt(chunks: Sequence[CaptionChunk], path: Path) -> Path:
    out = []
    for i, c in enumerate(chunks, 1):
        out.append(f"{i}\n{to_srt_time(c.start)} --> {to_srt_time(c.end)}\n{wrap_srt(c.text)}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def srt_chunks(words: Sequence[CapWord]) -> List[CaptionChunk]:
    return chunk_words(words, max_words=14, max_chars=84, min_dur=1.0)


def burn_chunks(words: Sequence[CapWord], vertical: bool) -> List[CaptionChunk]:
    if vertical:
        return chunk_words(words, max_words=4, max_chars=24, min_dur=0.5)
    return chunk_words(words, max_words=12, max_chars=60, min_dur=0.9)


class CaptionRenderer:
    """Draws burned-in captions for a time range (scene-relative chunk times)."""

    def __init__(self, chunks: Sequence[CaptionChunk], W: int, H: int, vertical: bool, center_y: float,
                 safe_left: float, safe_right: float):
        self.chunks = list(chunks)
        self.W, self.H, self.vertical = W, H, vertical
        self.cy = center_y
        self.left, self.right = safe_left, safe_right
        self.u = min(W, H) / 1080

    def _active(self, t: float) -> Optional[CaptionChunk]:
        for c in self.chunks:
            if c.start - 0.05 <= t < c.end:
                return c
        return None

    def draw(self, ctx: cairo.Context, t: float) -> None:
        c = self._active(t)
        if c is None:
            return
        u = self.u
        avail = self.W - self.left - self.right
        cx = self.left + avail / 2
        pop = ease_out_back(clamp((t - c.start + 0.05) / 0.18), 2.0)
        size = (78 if self.vertical else 56) * u
        st = TextStyle(font=CAPTION_FONT, size=size, color=(1, 1, 1), outline=PALETTE["ink"],
                       outline_width=size * (0.22 if self.vertical else 0.16), shadow=True)
        ctx.select_font_face(CAPTION_FONT)
        ctx.set_font_size(size)
        # layout words into lines
        space = ctx.text_extents(" ").x_advance
        max_w = avail * (0.96 if self.vertical else 0.84)
        lines: List[List[Tuple[CapWord, float]]] = [[]]
        lw = 0.0
        for w in c.words:
            ww = ctx.text_extents(w.text).x_advance
            if lines[-1] and lw + space + ww > max_w:
                lines.append([])
                lw = 0.0
            lines[-1].append((w, ww))
            lw += (space if lw else 0) + ww
        while size > 30 * u and len(lines) > (2 if self.vertical else 2):
            size *= 0.9
            return self._draw_scaled(ctx, c, t, size)
        lh = size * 1.12
        total_h = lh * len(lines)
        top = self.cy - total_h / 2
        if not self.vertical:
            widest = max(sum(ww for _, ww in ln) + space * (len(ln) - 1) for ln in lines)
            rounded_rect(ctx, cx - widest / 2 - 28 * u, top - 16 * u, widest + 56 * u, total_h + 26 * u, 22 * u)
            ctx.set_source_rgba(*PALETTE["night"], 0.55)
            ctx.fill()
        ctx.save()
        ctx.translate(cx, self.cy)
        s = 0.85 + 0.15 * pop
        ctx.scale(s, s)
        ctx.translate(-cx, -self.cy)
        for li, ln in enumerate(lines):
            width = sum(ww for _, ww in ln) + space * (len(ln) - 1)
            x = cx - width / 2
            y = top + li * lh
            for w, ww in ln:
                active = w.start <= t < w.end + 0.05
                done = t >= w.end
                col = PALETTE["yellow"] if active else ((1, 1, 1) if (done or not self.vertical) else (1, 1, 1))
                st.color = col
                if active and self.vertical:
                    ctx.save()
                    k = 1 + 0.08 * math.sin(clamp((t - w.start) / max(0.08, w.end - w.start)) * math.pi)
                    ctx.translate(x + ww / 2, y + size * 0.5)
                    ctx.scale(k, k)
                    draw_lines(ctx, [w.text], 0, -size * 0.5, st, "center")
                    ctx.restore()
                else:
                    draw_lines(ctx, [w.text], x, y, st, "left")
                x += ww + space
        ctx.restore()

    def _draw_scaled(self, ctx, c, t, size):  # pragma: no cover - rare long chunks
        saved = self.vertical
        try:
            self.u = self.u * size / ((78 if self.vertical else 56) * self.u)
            self.draw(ctx, t)
        finally:
            self.u = min(self.W, self.H) / 1080
            self.vertical = saved


def scene_chunks(chunks: Sequence[CaptionChunk], start: float, end: float) -> List[CaptionChunk]:
    """Chunks overlapping [start, end), converted to scene-relative times."""
    out = []
    for c in chunks:
        if c.end > start and c.start < end:
            out.append(CaptionChunk(c.start - start, c.end - start,
                                    [CapWord(w.text, w.start - start, w.end - start) for w in c.words]))
    return out
