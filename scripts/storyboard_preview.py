"""Render a contact sheet of a storyboard's scenes (no TTS, no encoding) for fast visual review.

Word timings are estimated from the planning pace, so cue-driven reveals land roughly where
they will in the real render.

    python scripts/storyboard_preview.py --script content_packs/why_is_the_sky_blue/script_short.json \
        --profile vertical --out sheet.png [--at 0.55 0.9] [--scale 0.25]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import src  # noqa: F401,E402  (fontconfig bootstrap)
import cairo  # noqa: E402

from src.animation.scene_engine import LayoutContext, WordTiming, compose_scene  # noqa: E402
from src.config.settings import load_settings  # noqa: E402
from src.content.models import Script  # noqa: E402
from src.content.storyboard_generator import WORDS_PER_SECOND, StoryboardGenerator  # noqa: E402


def render_sheet(script: Script, profile_name: str, out: Path, ats=(0.55,), scale: float = 0.25, cols: int = 6) -> Path:
    s = load_settings()
    prof = s.profile(profile_name)
    sb = StoryboardGenerator().build(script, prof)
    W, H = prof.width, prof.height
    tw, th = int(W * scale), int(H * scale)
    n = len(sb.scenes) * len(ats)
    rows = (n + cols - 1) // cols
    sheet = cairo.ImageSurface(cairo.FORMAT_RGB24, cols * tw, rows * th)
    sc_ctx = cairo.Context(sheet)
    center = prof.height * prof.caption_zone_y
    band = 240 if prof.is_vertical else 140
    k = 0
    for idx, scene in enumerate(sb.scenes):
        words = re.findall(r"\S+", scene.narration)
        dur = max(2.0, len(words) / WORDS_PER_SECOND + 0.75)
        wt = [WordTiming(w, 0.3 + i / WORDS_PER_SECOND, 0.3 + (i + 0.9) / WORDS_PER_SECOND) for i, w in enumerate(words)]
        L = LayoutContext(W=W, H=H, vertical=prof.is_vertical, safe_top=prof.safe.top, safe_bottom=prof.safe.bottom,
                          safe_left=prof.safe.left, safe_right=prof.safe.right, caption_top=center - band / 2,
                          caption_bottom=center + band / 2, duration=dur, words=wt, speech_start=0.3,
                          speech_end=dur - 0.4, seed=idx * 7 + 3)
        comp = compose_scene(scene, L, envelope=[0.5] * int(dur * 30 + 2))
        for a in ats:
            surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
            ctx = cairo.Context(surf)
            comp.draw(ctx, dur * a)
            sc_ctx.save()
            sc_ctx.translate((k % cols) * tw, (k // cols) * th)
            sc_ctx.scale(scale, scale)
            sc_ctx.set_source_surface(surf, 0, 0)
            sc_ctx.paint()
            sc_ctx.restore()
            k += 1
        print(f"{scene.scene_id} {scene.layout:18s} {scene.background:18s} {scene.purpose:11s} "
              f"{(scene.demo.kind if scene.demo else ','.join(o.asset for o in scene.objects))[:50]}")
    sheet.write_to_png(str(out))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True)
    ap.add_argument("--profile", default="vertical")
    ap.add_argument("--out", default="storyboard_sheet.png")
    ap.add_argument("--at", nargs="*", type=float, default=[0.55])
    ap.add_argument("--scale", type=float, default=0.25)
    ap.add_argument("--cols", type=int, default=6)
    a = ap.parse_args()
    script = Script.model_validate_json(Path(a.script).read_text(encoding="utf-8"))
    render_sheet(script, a.profile, Path(a.out), a.at, a.scale, a.cols)
    return 0


if __name__ == "__main__":
    sys.exit(main())
