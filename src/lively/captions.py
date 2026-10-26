"""Lively burned-in captions: big, bold, centred low, one short chunk at a time.

Every word sits on a thick ink outline with a soft drop shadow. The word being spoken
turns the highlight colour and pops slightly larger, timed by the narration's word
timestamps (faster-whisper alignment, see src/audio/word_aligner.py). The block stays
inside the platform safe area, clear of the Shorts/TikTok side buttons.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence

import cairo

from src.animation.easing import clamp, ease_out_back, ease_pop
from src.lively.style import Style
from src.rendering.subtitle_engine import CapWord, CaptionChunk, chunk_words


def lively_chunks(words: Sequence[CapWord], style: Style, vertical: bool) -> List[CaptionChunk]:
    c = style.captions
    if vertical:
        return chunk_words(words, max_words=c.max_words, max_chars=c.max_chars, min_dur=0.35, gap_break=0.35)
    return chunk_words(words, max_words=c.max_words + 3, max_chars=c.max_chars + 22, min_dur=0.5, gap_break=0.4)


class LivelyCaptionRenderer:
    def __init__(self, chunks: Sequence[CaptionChunk], W: int, H: int, style: Style, safe_left: float,
                 safe_right: float):
        self.chunks = list(chunks)
        self.W, self.H = W, H
        self.vertical = H > W
        self.st = style
        c = style.captions
        self.cy = H * (c.center_y if self.vertical else c.center_y_horizontal)
        self.left, self.right = safe_left, safe_right
        self.u = min(W, H) / 1080

    def _active(self, t: float) -> Optional[CaptionChunk]:
        for ch in self.chunks:
            if ch.start - 0.04 <= t < ch.end:
                return ch
        return None

    def _text(self, w: CapWord) -> str:
        return w.text.upper() if self.st.captions.uppercase else w.text

    def draw(self, ctx: cairo.Context, t: float) -> None:
        ch = self._active(t)
        if ch is None:
            return
        c, pal, u = self.st.captions, self.st.palette, self.u
        size = c.size * u * (1.0 if self.vertical else 0.72)
        avail = (self.W - self.left - self.right) * (0.94 if self.vertical else 0.8)
        ctx.save()
        ctx.select_font_face(self.st.fonts.caption)
        ctx.set_font_size(size)
        texts = [self._text(w) for w in ch.words]
        space = ctx.text_extents(" ").x_advance + size * (c.outline + 0.12)   # room for outlines + the active pop
        widths = [ctx.text_extents(x).x_advance for x in texts]
        # shrink to fit (long words), then wrap onto at most two lines
        total = sum(widths) + space * (len(widths) - 1)
        lines: List[List[int]] = [[]]
        lw = 0.0
        for i, ww in enumerate(widths):
            if lines[-1] and lw + space + ww > avail:
                lines.append([])
                lw = 0.0
            lines[-1].append(i)
            lw += (space if lw else 0) + ww
        widest = max(sum(widths[i] for i in ln) + space * (len(ln) - 1) for ln in lines)
        k = min(1.0, avail / max(widest, 1.0)) if len(lines) <= 2 else min(1.0, avail * 2 / max(total, 1.0))
        if k < 1.0:
            size *= k
            ctx.set_font_size(size)
            widths = [w * k for w in widths]
            space *= k
        lh = size * 1.08
        top = self.cy - lh * len(lines) / 2
        cx = self.left + (self.W - self.left - self.right) / 2
        # chunk entrance: quick pop from 85 %
        enter = 0.85 + 0.15 * ease_pop(clamp((t - ch.start + 0.04) / 0.16), 1.06)
        ctx.translate(cx, self.cy)
        ctx.scale(enter, enter)
        ctx.translate(-cx, -self.cy)
        ink = pal.rgb("ink")
        for li, ln in enumerate(lines):
            width = sum(widths[i] for i in ln) + space * (len(ln) - 1)
            x = cx - width / 2
            base = top + li * lh + size * 0.82
            for i in ln:
                w = ch.words[i]
                active = w.start - 0.02 <= t < max(w.end, w.start + 0.12) + 0.04
                col = pal.rgb("caption_active") if active else pal.rgb("caption")
                s = 1.0
                if active:
                    s = 1.0 + 0.14 * ease_out_back(clamp((t - w.start + 0.02) / 0.12), 2.2) - \
                        0.04 * clamp((t - w.start - 0.12) / 0.2)
                ww = widths[i]
                ctx.save()
                ctx.translate(x + ww / 2, base - size * 0.35)
                ctx.scale(s, s)
                ctx.rotate(math.radians(-2.0) if active else 0.0)
                ctx.translate(-(x + ww / 2), -(base - size * 0.35))
                ctx.new_path()
                ctx.move_to(x, base)
                ctx.text_path(texts[i])
                path = ctx.copy_path()
                ctx.set_line_join(cairo.LINE_JOIN_ROUND)
                if c.shadow:
                    ctx.save()
                    ctx.translate(0, size * 0.09)
                    ctx.new_path()
                    ctx.append_path(path)
                    ctx.set_source_rgba(*ink, 0.55)
                    ctx.set_line_width(size * c.outline * 1.25)
                    ctx.stroke_preserve()
                    ctx.fill()
                    ctx.restore()
                ctx.new_path()
                ctx.append_path(path)
                ctx.set_source_rgb(*ink)
                ctx.set_line_width(size * c.outline)
                ctx.stroke_preserve()
                ctx.set_source_rgb(*col)
                ctx.fill()
                ctx.restore()
                x += ww + space
        ctx.restore()
