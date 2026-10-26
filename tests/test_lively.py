"""Lively style + script mode: script files, defaults, camera, beats, captions, alignment, render."""
import json
from pathlib import Path

import cairo
import numpy as np
import pytest

from src.animation.easing import ease_pop
from src.audio.tts_engine import WordTime
from src.audio.word_aligner import align_words
from src.lively.camera import LivelyCamera
from src.lively.style import get_style, load_style
from src.script_mode.builder import build_storyboard
from src.script_mode.schema import ScriptFileError, load_user_script

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "scripts" / "sample_24_hours_awake.yaml"


def _write(tmp_path, text, name="s.yaml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ------------------------------------------------------------------ script files
def test_sample_script_builds_a_lively_storyboard(settings):
    us = load_user_script(SAMPLE)
    sb = build_storyboard(us, settings.profile("vertical"), "lively")
    assert sb.style == "lively" and sb.loop_to_start
    assert 6 <= len(sb.scenes) <= 8
    assert all(sc.layout == "spotlight" for sc in sb.scenes)
    assert sb.scenes[0].transition_in == "cut" and sb.scenes[-1].transition_out != "cut"
    assert "*" not in " ".join(sc.narration for sc in sb.scenes)              # emphasis markers are not spoken
    assert sb.scenes[0].lively.emphasis == ["24 hours", "drunk"]
    assert sb.scenes[0].lively.headline                                        # text on screen in the hook


def test_sample_script_also_builds_classic(settings):
    sb = build_storyboard(load_user_script(SAMPLE), settings.profile("vertical"), "classic")
    assert sb.style == "classic" and all(sc.layout != "spotlight" for sc in sb.scenes)


def test_json_scripts_work(tmp_path, settings):
    p = _write(tmp_path, json.dumps({"title": "Tiny test", "scenes": [{"text": "Hello brain."}]}), "s.json")
    sb = build_storyboard(load_user_script(p), settings.profile("vertical"))
    assert sb.scenes[0].objects[0].asset


def test_missing_fields_get_varied_defaults(tmp_path, settings):
    p = _write(tmp_path, 'title: "Defaults"\nscenes:\n' + "".join(
        f'  - text: "Scene number {i} talks about the brain and sleep."\n' for i in range(5)))
    sb = build_storyboard(load_user_script(p), settings.profile("vertical"))
    pos = [sc.character.position for sc in sb.scenes]
    cams = [sc.lively.camera for sc in sb.scenes]
    vis = [sc.objects[0].asset for sc in sb.scenes]
    assert all(a != b for a, b in zip(pos, pos[1:]))
    assert all(a != b for a, b in zip(cams, cams[1:]))
    assert all(a != b for a, b in zip(vis, vis[1:]))


def test_script_errors_are_clear(tmp_path):
    p = _write(tmp_path, 'title: "Bad one"\nvoice_language: ur\nscenes:\n  - text: "Hi there"\n    visul: brain.svg\n'
                         '  - text: "Second"\n    visual: clok.svg\n    animation: drawon\n')
    with pytest.raises(ScriptFileError) as e:
        load_user_script(p)
    msg = "\n".join(e.value.problems)
    assert "English" in msg
    assert "scene 1: unknown field 'visul'. Did you mean 'visual'?" in msg
    assert "clock.svg" in msg and "scene 2" in msg
    assert "draw_on" in msg


def test_missing_text_and_file(tmp_path):
    with pytest.raises(ScriptFileError, match="not found"):
        load_user_script(tmp_path / "nope.yaml")
    p = _write(tmp_path, 'title: "No text"\nscenes:\n  - visual: brain.svg\n')
    with pytest.raises(ScriptFileError) as e:
        load_user_script(p)
    assert "scene 1: required field 'text' is missing" in e.value.problems


def test_too_long_scene_is_reported(tmp_path, settings):
    p = _write(tmp_path, 'title: "Long"\nscenes:\n  - text: "' + "word " * 60 + '"\n')
    with pytest.raises(ScriptFileError, match="split it in two"):
        build_storyboard(load_user_script(p), settings.profile("vertical"))


# ------------------------------------------------------------------ motion building blocks
def test_pop_in_overshoots_to_1_1_then_settles():
    vals = [ease_pop(x / 100) for x in range(101)]
    assert vals[0] == 0 and abs(vals[-1] - 1.0) < 1e-6
    assert 1.08 <= max(vals) <= 1.11


def test_camera_moves_clearly_and_punches():
    st = get_style()
    cam = LivelyCamera("zoom_in", 6.0, 1080, 1920, st.camera, punches=[3.0])
    s0, s_end = cam.at(0.0).scale, cam.at(6.0).scale
    assert s_end - s0 >= 0.12                                   # visible on a phone
    assert cam.at(3.2).scale > cam.at(2.9).scale + 0.08         # punch-in on the key word
    still = LivelyCamera("static", 6.0, 1080, 1920, st.camera)
    assert still.at(1.0).dx != still.at(2.0).dx                 # never fully still


def test_style_file_loads():
    st = load_style()
    assert st.transitions.duration_s <= 0.3 and st.beats.max_gap_s <= 2.0
    assert st.palette.rgb("paper")


def test_word_alignment_moves_words_to_measured_times():
    est = [WordTime(w, i * 0.5, i * 0.5 + 0.4) for i, w in enumerate("Stay awake for 24 hours, brain.".split())]
    rec = [(" Stay", 0.10, 0.30), (" awake", 0.32, 0.70), (" for", 0.72, 0.85), (" twenty-four", 0.9, 1.5),
           (" hours,", 1.55, 1.9), (" brain.", 2.4, 2.9)]
    out, ratio = align_words(est, rec, 3.0)
    assert ratio == 1.0
    assert [round(w.start, 2) for w in out] == [0.1, 0.32, 0.72, 0.9, 1.55, 2.4]
    assert out[3].word == "24"                                   # caption text stays the script's


def test_word_alignment_keeps_estimates_when_transcript_is_unrelated():
    est = [WordTime(w, i * 0.5, i * 0.5 + 0.4) for i, w in enumerate("one two three four".split())]
    out, ratio = align_words(est, [(" banana", 0.0, 1.0)], 2.0)
    assert ratio < 0.6 and out == est


def _spot_comp(first=True, duration=6.0):
    from src.animation.scene_engine import LayoutContext, WordTiming
    from src.content.models import Scene
    from src.lively.composer import compose_lively
    text = "After one night without sleep your brain starts acting like it is drunk and slow."
    words = [WordTiming(w, 0.3 + i * 0.33, 0.6 + i * 0.33) for i, w in enumerate(text.split())]
    sc = Scene(scene_id="s1", narration=text, est_duration=duration, layout="spotlight", background="doodle_paper",
               objects=[{"asset": "brain"}], character={"character": "science", "position": "left"},
               lively={"animation": "draw_on", "headline": "24 HOURS"}, transition_out="whip_left")
    W, H = 270, 480
    L = LayoutContext(W=W, H=H, vertical=True, safe_top=58, safe_bottom=105, safe_left=18, safe_right=38,
                      caption_top=300, caption_bottom=360, duration=duration, words=words, speech_start=0.3,
                      speech_end=duration - 0.4, seed=3)
    return compose_lively(sc, L, envelope=[0.5] * 200, first=first), W, H


def _frame(comp, W, H, t):
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    comp.draw(cairo.Context(s), t)
    s.flush()
    return np.frombuffer(s.get_data(), np.uint8).reshape(H, -1, 4)[:, :W, :3].astype(int)


def test_hook_frame_already_shows_content_and_text():
    comp, W, H = _spot_comp(first=True)
    paper = _frame(type(comp)(**{**comp.__dict__, "elements": [], "character": None}), W, H, 0.45)
    f0 = _frame(comp, W, H, 0.45)                                # renderer preroll for the first scene
    assert (np.abs(f0 - paper) > 30).mean() > 0.05


def test_frame_never_stays_static_and_beats_fill_gaps():
    comp, W, H = _spot_comp(duration=8.0)
    frames = [_frame(comp, W, H, t) for t in np.arange(0.5, 7.5, 0.5)]
    changes = [(np.abs(frames[i + 2] - frames[i]) > 12).mean() for i in range(len(frames) - 2)]
    assert min(changes) > 0.02
    times = sorted([e.start for e in comp.elements] + comp.camera.punches)
    inner = [t for t in times if 0.3 < t < 7.6]
    assert max(b - a for a, b in zip([0.0] + inner, inner + [7.6])) <= get_style().beats.max_gap_s + 0.5


def test_lively_transition_cut_frame_is_not_flat():
    comp, W, H = _spot_comp(first=False)
    f = _frame(comp, W, H, comp.duration - 0.01)                 # whip at its fastest
    assert f.std() > 3.0


def test_lively_captions_render(tmp_path):
    from src.lively.captions import LivelyCaptionRenderer, lively_chunks
    from src.rendering.subtitle_engine import CapWord
    words = [CapWord(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate("your brain starts acting drunk".split())]
    chunks = lively_chunks(words, get_style(), True)
    assert all(len(c.words) <= get_style().captions.max_words for c in chunks)
    r = LivelyCaptionRenderer(chunks, 270, 480, get_style(), 18, 38)
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, 270, 480)
    r.draw(cairo.Context(s), 0.5)
    s.flush()
    a = np.frombuffer(s.get_data(), np.uint8).reshape(480, -1, 4)[:, :270, :3]
    yellow = (a[..., 2] > 200) & (a[..., 1] > 170) & (a[..., 0] < 120)     # BGRA: the active word
    assert yellow.sum() > 20


# ------------------------------------------------------------------ real render
@pytest.mark.integration
def test_render_script_end_to_end(tmp_path, small_settings):
    from src.script_mode.runner import render_script
    p = _write(tmp_path, 'title: "Mini lively test"\nloop_to_start: true\nscenes:\n'
                         '  - text: "Stay awake for *one* night."\n    visual: brain.svg\n'
                         '  - text: "Your brain gets slow."\n    visual: clock.svg\n    animation: draw_on\n')
    small_settings.tts.word_alignment = "off"
    rep = render_script(p, small_settings, formats=["short", "long"])
    assert rep["status"] == "success", rep.get("failed_checks")
    root = Path(small_settings.paths.generated) / "mini_lively_test"
    assert set(rep["outputs"]) == {"short", "long"}
    for o in rep["outputs"].values():                            # one narration, both videos
        assert (root / o["video"]).exists() and o["status"] == "success"
    thumbs = rep["thumbnails"]
    assert any(t.endswith("16x9.jpg") for t in thumbs) and any(t.endswith("9x16.jpg") for t in thumbs)
    assert all((root / t).exists() for t in thumbs)
