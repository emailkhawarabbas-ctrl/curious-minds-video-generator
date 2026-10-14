import json
import wave
from pathlib import Path

import cairo
import numpy as np
import pytest

from src.audio.mixer import NarrationClip, SfxEvent, mix_episode
from src.audio.music_engine import generate_music
from src.audio.sound_effects import GENERATORS, ensure_library
from src.rendering.subtitle_engine import CapWord, chunk_words, srt_chunks, write_srt
from src.rendering.quality_control import check_video, parse_srt


def test_sfx_library_generated():
    paths = ensure_library()
    assert set(paths) == set(GENERATORS)
    for p in paths.values():
        with wave.open(str(p)) as w:
            assert w.getframerate() == 44100 and w.getnframes() > 100


def test_music_is_original_and_bounded():
    for mood in ("curious", "dreamy", "upbeat", "calm"):
        m = generate_music(6, mood)
        assert m.shape == (6 * 44100, 2)
        assert np.abs(m).max() <= 0.51 and np.abs(m).mean() > 1e-3


def test_mix_keeps_music_below_voice(tmp_path, settings):
    sr = 22050
    t = np.arange(sr * 3) / sr
    voice = (0.3 * np.sin(2 * np.pi * 220 * t) * (np.sin(2 * np.pi * 3 * t) > 0)).astype(np.float32)
    p = tmp_path / "v.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((voice * 32767).astype(np.int16).tobytes())
    rep = mix_episode([NarrationClip(str(p), 0.5)], [SfxEvent("pop", 1.0), SfxEvent("ding", 1.05)], 4.0, "dreamy",
                      settings.audio, tmp_path / "mix.wav")
    assert rep["music_below_voice_db"] > 10
    assert rep["sfx_placed"] == 1        # stacked effects are de-duplicated


def test_caption_chunking_and_srt(tmp_path):
    words = [CapWord(w, i * 0.4, i * 0.4 + 0.35) for i, w in enumerate(
        "Every night your brain makes a movie. And you are the star of the show!".split())]
    ch = chunk_words(words, 4, 24)
    assert all(len(c.words) <= 4 for c in ch)
    assert all(ch[i].end <= ch[i + 1].start for i in range(len(ch) - 1))
    path = write_srt(srt_chunks(words), tmp_path / "x.srt")
    cues = parse_srt(path)
    assert cues[0][0] == pytest.approx(0) and cues[-1][2].endswith("show!")


def test_tts_scene_timing(settings, tmp_path):
    from src.audio.tts_engine import TTSEngine
    e = TTSEngine(settings)
    a = e.synthesize_scene("t1", "Dreams happen in REM sleep. It was described in 1953!", tmp_path, 1.08)
    assert 2.0 < a.duration < 8.0
    assert [w.word for w in a.words][-1] == "1953!"
    assert all(a.words[i].end <= a.words[i + 1].start + 1e-6 for i in range(len(a.words) - 1))
    assert a.words[-1].end == pytest.approx(a.duration, abs=0.01)
    assert len(a.sentences) == 2 and a.sentences[1].start > a.sentences[0].end   # pause, no overlap


@pytest.mark.integration
def test_render_mini_episode_end_to_end(small_settings, tmp_path):
    """Integration: storyboard -> TTS -> parallel render -> mux -> ffprobe QC on a tiny profile."""
    from src.audio.tts_engine import TTSEngine
    from src.content.models import Script
    from src.content.storyboard_generator import StoryboardGenerator
    from src.rendering.renderer import EpisodeRenderer
    s = small_settings
    script = Script.model_validate({"topic": "Why Do We Dream?", "niche": "psychology", "format": "short",
                                    "title": "t", "hook": "h", "sections": [{"title": "One", "beats": [
                                        {"id": "b1", "narration": "Why do we dream every night?",
                                         "visual": {"layout": "hook_title", "assets": ["dream_cloud"]}},
                                        {"id": "b2", "narration": "Your brain is busy while you sleep.",
                                         "visual": {"layout": "character_explains", "assets": ["brain"]}},
                                        {"id": "b3", "narration": "Stay curious!", "visual": {"layout": "outro"}}]}]})
    prof = s.profile("vertical")
    sb = StoryboardGenerator().build(script, prof)
    sb.scenes[0].transition_out = sb.scenes[1].transition_in = "circle_wipe"
    tts = TTSEngine(s)
    audios = {sc.scene_id: tts.synthesize_scene(sc.scene_id, sc.narration, tmp_path / "a", 1.0) for sc in sb.scenes}
    out = tmp_path / "mini.mp4"
    res = EpisodeRenderer(s, "vertical").render(sb, audios, out, tmp_path / "work", tmp_path / "mini.srt")
    qc = check_video(out, prof.width, prof.height, prof.fps, (1, 60), s.audio.target_lufs, res.srt_path)
    failed = [c for c in qc["checks"] if not c["passed"]]
    assert qc["passed"], failed
    assert res.frames == sum(t.frames for t in res.timings)


def test_qc_reports_missing_file(tmp_path):
    rep = check_video(tmp_path / "nope.mp4", 1080, 1920, 30, (60, 90))
    assert rep["passed"] is False


def test_transition_frames_never_blank():
    from src.animation.transition_engine import draw_transition
    from src.animation.registry import TRANSITIONS
    for kind in TRANSITIONS:
        if kind == "cut":
            continue
        s = cairo.ImageSurface(cairo.FORMAT_RGB24, 192, 108)
        c = cairo.Context(s)
        c.set_source_rgb(1, 1, 1)
        c.paint()
        draw_transition(c, kind, 1.0, 192, 108)
        s.flush()
        g = np.frombuffer(s.get_data(), np.uint8)
        assert g.std() > 3, kind


@pytest.mark.parametrize("bg", ["paper", "night_sky"])
def test_transitions_never_flat_at_any_coverage(bg):
    """Regression: QC once caught flat frames mid-transition (doodle swipe / dip to cream)."""
    from src.animation.backgrounds import Background
    from src.animation.registry import TRANSITIONS
    from src.animation.transition_engine import draw_transition
    W, H = 960, 540
    base = Background(bg, W, H)
    for kind in TRANSITIONS:
        if kind == "cut":
            continue
        for c in np.linspace(0.05, 1.0, 12):
            s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
            ctx = cairo.Context(s)
            base.draw(ctx, 0)
            draw_transition(ctx, kind, float(c), W, H)
            s.flush()
            g = np.frombuffer(s.get_data(), np.uint8).reshape(H, W, 4)[..., :3].mean(axis=2)
            small = g.reshape(54, 10, 96, 10).mean(axis=(1, 3))     # same scale as the QC sampler
            assert small.std() > 3.0, (kind, bg, round(float(c), 2))
