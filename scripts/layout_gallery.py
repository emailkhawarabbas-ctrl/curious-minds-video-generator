"""Render one frame of every layout template (vertical + horizontal) for visual QA.

  python scripts/layout_gallery.py --out gallery_dir --t 4.5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import src  # noqa: F401,E402
import cairo  # noqa: E402

from src.animation.scene_engine import LayoutContext, compose_scene  # noqa: E402
from src.config.settings import get_settings  # noqa: E402
from src.content.models import Scene  # noqa: E402

DEMO = [
    dict(layout="hook_title", background="burst_purple", text_overlays=[{"text": "Why do we dream?", "style": "title"}],
         objects=[{"asset": "dream_cloud"}], character={"action": "surprised", "expression": "surprised"}, doodles=["twinkle_field"]),
    dict(layout="character_explains", background="paper", objects=[{"asset": "brain", "label": "Your brain", "highlight": ["cerebrum"]},
         {"asset": "moon_sleepy", "role": "secondary"}], character={"action": "point", "expression": "happy"}, doodles=["sparkles", "arrow_to_main"]),
    dict(layout="object_focus", background="lab", objects=[{"asset": "brain"}], text_overlays=[{"text": "Memories", "style": "label"},
         {"text": "Emotions", "style": "label"}, {"text": "Vision", "style": "label"}], character={"position": "right", "action": "point", "expression": "curious"}),
    dict(layout="diagram_flow", background="sunny_outdoors", objects=[{"asset": "eye", "label": "You see"}, {"asset": "brain", "label": "Brain stores"},
         {"asset": "dream_cloud", "label": "You dream"}], character={"position": "corner_left", "action": "explain"}),
    dict(layout="list_reveal", background="paper", items=[{"text": "Sort memories", "asset": "memory_photos"}, {"text": "Practice emotions", "asset": "emotion_happy"},
         {"text": "Spark creativity", "asset": "lightbulb"}], character={"action": "explain"}),
    dict(layout="comparison", background="city", objects=[{"asset": "sleeping_person", "label": "REM sleep"}, {"asset": "brain_activity", "label": "Awake brain"}],
         character={"position": "center", "action": "think", "expression": "thinking"}),
    dict(layout="thought_bubble", background="dreamscape", objects=[{"asset": "sheep"}, {"asset": "rocket"}], character={"action": "think", "expression": "thinking"}),
    dict(layout="fact_card", background="burst_teal", number={"value": 2, "suffix": " HOURS", "label": "of dreaming every night"},
         objects=[{"asset": "alarm_clock"}], character={"action": "excited", "expression": "excited"}),
    dict(layout="story_scene", background="bedroom_night", objects=[{"asset": "sleeping_person"}, {"asset": "zzz", "role": "secondary"}],
         character={"action": "talk", "expression": "happy", "position": "left"}, doodles=["zzz"]),
    dict(layout="network", background="brain_space", objects=[{"asset": "brain"}, {"asset": "memory_photos", "label": "Memory"},
         {"asset": "emotion_scared", "label": "Emotion"}, {"asset": "eye", "label": "Vision"}], character={"action": "point"}),
    dict(layout="chart", background="paper", chart={"kind": "step", "points": [[0, 1], [0.1, 0.66], [0.2, 0.33], [0.3, 0], [0.4, 0.66], [0.5, 1], [0.6, 0.33], [0.75, 1], [0.9, 0.66], [1, 1]],
         "labels": ["Deep", "Light", "Light", "REM"], "x_labels": ["11pm", "2am", "5am", "7am"]}, character={"action": "point", "position": "left"}),
    dict(layout="question", background="burst_orange", text_overlays=[{"text": "But why does it feel so real?", "style": "title"}],
         character={"action": "shrug", "expression": "confused"}),
    dict(layout="timeline", background="night_sky", items=[{"text": "Fall asleep", "asset": "moon_sleepy"}, {"text": "Deep sleep", "asset": "zzz"},
         {"text": "REM dreams", "asset": "dream_cloud"}, {"text": "Wake up", "asset": "alarm_clock"}], character={"action": "talk"}),
    dict(layout="wave_monitor", background="lab", items=[{"text": "Awake: fast waves"}, {"text": "Deep sleep: slow waves"}], character={"action": "point"}),
    dict(layout="outro", background="burst_teal", text_overlays=[{"text": "Follow for more!", "style": "cta"}], character={"action": "wave", "expression": "happy"}),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="gallery")
    ap.add_argument("--t", type=float, default=4.6)
    ap.add_argument("--only")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    s = get_settings()
    for orient in ("vertical", "horizontal"):
        prof = s.profile(orient)
        cap_c = prof.height * prof.caption_zone_y
        band = (230 if prof.is_vertical else 130)
        for i, d in enumerate(DEMO):
            if a.only and d["layout"] != a.only:
                continue
            sc = Scene(scene_id=f"s{i}", narration="Test narration for the layout gallery.", est_duration=6, **d)
            L = LayoutContext(W=prof.width, H=prof.height, vertical=prof.is_vertical, safe_top=prof.safe.top,
                              safe_bottom=prof.safe.bottom, safe_left=prof.safe.left, safe_right=prof.safe.right,
                              caption_top=cap_c - band / 2, caption_bottom=cap_c + band / 2, duration=6.0,
                              speech_start=0.3, speech_end=5.5, seed=i)
            comp = compose_scene(sc, L)
            surf = cairo.ImageSurface(cairo.FORMAT_RGB24, prof.width, prof.height)
            ctx = cairo.Context(surf)
            comp.draw(ctx, a.t)
            # visualise safe area + caption band
            ctx.set_source_rgba(1, 0, 0, 0.5)
            ctx.set_line_width(3)
            ctx.rectangle(prof.safe.left, prof.safe.top, prof.width - prof.safe.left - prof.safe.right,
                          prof.height - prof.safe.top - prof.safe.bottom)
            ctx.stroke()
            ctx.set_source_rgba(0, 0, 1, 0.25)
            ctx.rectangle(0, cap_c - band / 2, prof.width, band)
            ctx.fill()
            surf.write_to_png(str(out / f"{orient}_{i:02d}_{d['layout']}.png"))
    print("wrote", out)


if __name__ == "__main__":
    main()
