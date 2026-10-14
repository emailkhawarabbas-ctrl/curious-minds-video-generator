import csv
import json

import cairo
import numpy as np
import pytest

from src.animation import registry as R
from src.animation.scene_engine import LayoutContext, compose_scene
from src.content.models import Scene

DEMO = {
    "hook_title": dict(text_overlays=[{"text": "Why?", "style": "title"}], objects=[{"asset": "dream_cloud"}]),
    "character_explains": dict(objects=[{"asset": "brain", "label": "Brain"}]),
    "object_focus": dict(objects=[{"asset": "heart"}], text_overlays=[{"text": "Pump", "style": "label"}]),
    "diagram_flow": dict(objects=[{"asset": "eye"}, {"asset": "brain"}, {"asset": "dream_cloud"}]),
    "list_reveal": dict(items=[{"text": "One", "asset": "star"}, {"text": "Two"}]),
    "comparison": dict(objects=[{"asset": "sun"}, {"asset": "moon"}]),
    "thought_bubble": dict(objects=[{"asset": "sheep"}]),
    "fact_card": dict(number={"value": 90, "suffix": " MIN"}),
    "story_scene": dict(objects=[{"asset": "sleeping_person"}]),
    "network": dict(objects=[{"asset": "brain"}, {"asset": "eye"}, {"asset": "ear"}]),
    "chart": dict(chart={"kind": "bar", "values": [1, 3, 2], "labels": ["a", "b", "c"]}),
    "question": dict(text_overlays=[{"text": "Why?", "style": "title"}]),
    "timeline": dict(items=[{"text": "A"}, {"text": "B"}, {"text": "C"}]),
    "wave_monitor": dict(items=[{"text": "Awake"}, {"text": "Deep sleep"}]),
    "outro": dict(text_overlays=[{"text": "Follow!", "style": "cta"}]),
}


@pytest.mark.parametrize("layout", list(R.LAYOUTS))
@pytest.mark.parametrize("vertical", [True, False])
def test_every_layout_renders(layout, vertical):
    W, H = (270, 480) if vertical else (480, 270)
    sc = Scene(scene_id="x", narration="Test narration here.", est_duration=4, layout=layout, background="paper",
               **DEMO[layout])
    cap = H * (0.695 if vertical else 0.885)
    L = LayoutContext(W=W, H=H, vertical=vertical, safe_top=H * 0.12, safe_bottom=H * 0.22, safe_left=W * 0.06,
                      safe_right=W * 0.12, caption_top=cap - 20, caption_bottom=cap + 20, duration=4.0,
                      speech_start=0.3, speech_end=3.6)
    comp = compose_scene(sc, L)
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surf)
    frames = []
    for t in (0.2, 1.5, 3.5):
        comp.draw(ctx, t)
        surf.flush()
        frames.append(np.frombuffer(surf.get_data(), np.uint8).copy())
    assert np.abs(frames[2].astype(int) - frames[0].astype(int)).mean() > 0.5   # animated, not static
    assert len(comp.elements) >= 1


def test_all_backgrounds_render():
    from src.animation.backgrounds import Background
    for name in R.BACKGROUNDS:
        b = Background(name, 160, 90)
        s = cairo.ImageSurface(cairo.FORMAT_RGB24, 160, 90)
        b.draw(cairo.Context(s), 1.0)


def test_analytics_import_and_report(tmp_path):
    from src.analytics.csv_importer import import_csv
    from src.analytics.performance_analyzer import analyze, load_metrics
    from src.analytics.weekly_report import build_weekly_report
    f = tmp_path / "yt.csv"
    with open(f, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Content", "Video title", "Views", "Average view duration", "Average percentage viewed (%)",
                    "Likes", "Shares", "Subscribers"])
        w.writerow(["Total", "", "300", "", "", "", "", ""])
        w.writerow(["abc", "Why Do We Dream?", "1,200", "0:45", "61.5", "80", "12", "5"])
        w.writerow(["def", "Why Is the Sky Blue?", "800", "0:30", "40", "30", "4", "1"])
    store = tmp_path / "an"
    assert import_csv(f, "youtube", store) == 2
    rows = load_metrics(store)
    r = next(r for r in rows if r["video_id"] == "abc")
    assert r["views"] == 1200 and r["avg_view_duration_s"] == 45 and r["completion_rate"] == pytest.approx(0.615)
    assert analyze(rows)["videos"] == 2
    md = build_weekly_report(store, tmp_path / "generated")
    text = md.read_text()
    assert "Suggested next topics" in text and "nothing is estimated" in text


def test_analytics_without_data_does_not_invent():
    from src.analytics.performance_analyzer import analyze
    assert analyze([])["status"] == "no_data"


def test_topic_suggestions_follow_pillar_mix(tmp_path):
    from src.content.topic_generator import pillar_weights, suggest_topics
    w = pillar_weights()
    assert w == {"human_body": 0.40, "psychology": 0.35, "science": 0.25}
    s = suggest_topics(6, tmp_path)
    assert len(s) == 6 and {x["niche"] for x in s} == {"human_body", "psychology", "science"}
