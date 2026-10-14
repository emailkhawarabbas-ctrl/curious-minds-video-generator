"""Tests for the narration, niche-identity, storytelling and review upgrades."""
import wave

import cairo
import numpy as np
import pytest

from src.animation import registry as R


# --------------------------------------------------------------------------- narration direction
def test_delivery_intents_follow_story_position():
    from src.audio.narration_director import classify, delivery_for
    assert classify("Why is the sky blue?", first_in_video=True, last_scene=False, last_in_scene=False) == "hook"
    assert classify("Stay curious!", first_in_video=False, last_scene=True, last_in_scene=True) == "ending"
    assert classify("But here's the surprising part:", first_in_video=False, last_scene=False,
                    last_in_scene=False) == "transition"
    assert classify("So what happens next?", first_in_video=False, last_scene=False, last_in_scene=False) == "question"
    assert classify("It turns out the answer is scattering.", first_in_video=False, last_scene=False,
                    last_in_scene=False) == "discovery"
    calm, lively = delivery_for("surprise", 0.3), delivery_for("surprise", 0.9)
    assert abs(lively.speed - 1) > abs(calm.speed - 1) and lively.pause_before > calm.pause_before
    assert delivery_for("surprise", 1.0).gain_db <= 1.5                       # emphasis, never loudness tricks


def test_speech_shaping_keeps_words():
    from src.audio.narration_director import shape_for_speech
    out = shape_for_speech("The heart — a muscle (about 300 grams) — never rests...")
    assert "—" not in out and "(" not in out and "muscle" in out and "300" in out


# --------------------------------------------------------------------------- voices & providers
def test_resolve_voice_profiles_and_ids(settings):
    from src.audio.tts_engine import resolve_voice
    s = settings.model_copy(deep=True)
    resolve_voice(s, "US English Male (Calm)")
    assert s.tts.profile == "documentary"
    resolve_voice(s, "energetic")
    assert s.tts.profile == "energetic"
    resolve_voice(s, "en_US-norman-medium")
    assert s.tts.provider == "piper" and s.tts.voice == "en_US-norman-medium"
    resolve_voice(s, "am_michael:0.7,am_fenrir:0.3")
    assert s.tts.provider == "kokoro"
    with pytest.raises(ValueError):
        resolve_voice(s, "Robot Voice 3000")


def test_no_silent_voice_fallback(settings, monkeypatch):
    from src.audio import tts_engine as T
    s = settings.model_copy(deep=True)
    s.tts.provider = "elevenlabs"
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("TTS_API_KEY", raising=False)
    with pytest.raises(T.TTSError, match="Refusing to switch"):
        T.get_provider(s)

    class Dummy(T.TTSProvider):
        name, voice_name = "piper", "dummy"

        def __init__(self, settings):
            pass

        def synth(self, text, length_scale, delivery=None):
            return np.zeros(100, np.int16), 22050, []

    monkeypatch.setitem(T.PROVIDERS, "piper", Dummy)
    s.tts.fallback_provider = "piper"
    prov, fb = T.get_provider(s)
    assert prov.name == "piper" and fb["requested"] == "elevenlabs" and "API_KEY" in fb["reason"]


def test_trim_keeps_soft_endings_and_normalises():
    from src.audio.tts_engine import _trim, abrupt_ending, normalise_speech
    sr = 24000
    t = np.arange(sr) / sr
    voiced = 0.5 * np.sin(2 * np.pi * 150 * t)
    soft_tail = 0.004 * np.random.default_rng(0).standard_normal(int(sr * 0.1))   # an "s" below the gate
    x = (np.concatenate([np.zeros(sr // 4), voiced, soft_tail, np.zeros(sr // 4)]) * 32767).astype(np.int16)
    y = _trim(x, sr)
    assert len(y) >= len(voiced) + int(sr * 0.1)          # tail kept
    assert abs(int(y[-1])) < 50 and abs(int(y[0])) < 50   # faded, no clicks
    z, info = normalise_speech(y, sr, 0.0)
    assert np.abs(z).max() <= 0.9 * 32767 and -22 < info["speech_dbfs"] + info["gain_db"] < -18
    cut = (voiced[: sr // 2] * 32767).astype(np.int16)
    assert abrupt_ending(cut, sr) and not abrupt_ending(y, sr)


# --------------------------------------------------------------------------- narration QC
def _wav(path, x, sr=24000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def test_narration_qc_flags_clipping_and_cutoffs(tmp_path):
    from src.audio.audio_qc import narration_qc, word_error_rate
    from src.audio.tts_engine import SceneAudio, SentenceTime
    sr = 24000
    t = np.arange(sr * 2) / sr
    f0 = 120 * (1 + 0.15 * np.sin(2 * np.pi * 0.5 * t))
    clean = 0.3 * np.sin(2 * np.pi * np.cumsum(f0) / sr) * np.hanning(len(t))
    _wav(tmp_path / "a.wav", clean)
    _wav(tmp_path / "b.wav", np.clip(clean * 6, -1, 1))
    good = SceneAudio("a", str(tmp_path / "a.wav"), sr, 2.0, [SentenceTime("Hello there my friend.", 0, 2)])
    bad = SceneAudio("b", str(tmp_path / "b.wav"), sr, 2.0, [SentenceTime("Hello there my friend.", 0, 2)],
                     flags=["sentence 1 may end abruptly"])
    ok = narration_qc({"a": good}, asr="off")
    assert all(c["passed"] for c in ok["checks"] if c["severity"] == "hard")
    rep = narration_qc({"b": bad}, {"b": 1.5}, asr="off")
    failed = {c["check"] for c in rep["checks"] if not c["passed"]}
    assert {"no_clipping", "no_cut_off_sentences", "narration_fits_scenes"} <= failed and not rep["passed"]
    assert word_error_rate("Sleep cycles last 90 minutes", "sleep cycles last ninety minutes") == 0.0


# --------------------------------------------------------------------------- niche identity & selection
def test_theme_resolution():
    from src.animation.themes import resolve_theme
    assert resolve_theme("human_body").name == "human_body"
    assert resolve_theme("mixed", "Why Is the Sky Blue?").name == "science"
    assert resolve_theme("mixed", "Why do we overthink everything?").name == "psychology"
    assert resolve_theme("mixed", "How does your heart pump blood?").name == "human_body"


@pytest.mark.parametrize("niche,topic,text,want,forbid", [
    ("human_body", "How Does Your Heart Actually Work?", "The right side sends oxygen-poor blood to your lungs.",
     {"heart_cutaway", "heart", "lungs", "oxygen_o2", "red_blood_cell", "body_circulation", "blood_vessel"},
     {"star", "rocket", "planet_saturn"}),
    ("science", "Why Is the Sky Blue?", "Air molecules scatter short blue waves in every direction.",
     {"nitrogen_n2", "light_wave", "atmosphere_layers", "observer_kid", "prism"}, {"heart", "brain", "rocket"}),
    ("psychology", "Why Do We Overthink Everything?", "Your thoughts circle the same worry over and over.",
     {"thought_spiral", "overthinking_head", "worried_face", "person_thinking"}, {"heart_cutaway", "atom", "star"}),
])
def test_selector_picks_topic_assets(niche, topic, text, want, forbid):
    from src.animation.themes import resolve_theme
    from src.content.visual_selector import VisualSelector
    sel = VisualSelector(resolve_theme(niche, topic), topic, niche)
    picks = [p.asset for p in sel.select_assets(text, 3)]
    assert picks and picks[0] in want, picks
    assert not set(picks) & forbid, picks


def test_selector_demos_and_novelty():
    from src.animation.themes import resolve_theme
    from src.content.visual_selector import VisualSelector
    sel = VisualSelector(resolve_theme("science", "Why Is the Sky Blue?"), "Why Is the Sky Blue?", "science")
    assert sel.demo_for("At sunset the light crosses much more air.") == "sunset_path"
    assert sel.demo_for("Air molecules scatter blue light in every direction.") == "light_scattering"
    first = sel.select_assets("Sunlight hits nitrogen molecules in the air.", 1)[0].asset
    sel.commit([first])
    again = sel.select_assets("Sunlight hits nitrogen molecules in the air.", 1)[0]
    assert again.asset != first or "used" in " ".join(again.reasons)


def test_asset_metadata_complete():
    from src.animation.asset_manager import AssetManager
    m = AssetManager()
    assert m.missing_metadata() == {}
    rec = m.record("heart_cutaway")
    assert rec.category == "human_body" and rec.subcategory == "cardiovascular" and "beat" in rec.animations
    for niche in ("human_body", "science", "psychology"):
        assert len(m.ids(niche)) >= 20


@pytest.mark.parametrize("bg", ["bloodstream", "body_lab", "anatomy_blueprint", "cell_world", "sky_day", "science_grid",
                                "atmosphere_view", "sunset_sky", "mind_maze", "thought_room", "emotion_waves"])
def test_niche_backgrounds_render(bg):
    from src.animation.backgrounds import Background
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, 270, 480)
    ctx = cairo.Context(s)
    Background(bg, 270, 480, seed=2).draw(ctx, 1.0)
    s.flush()
    g = np.frombuffer(s.get_data(), np.uint8).reshape(480, 270, 4)[..., :3]
    assert g.std() > 6 and bg in R.BACKGROUNDS


@pytest.mark.parametrize("kind", sorted(R.DEMOS))
def test_every_demo_animates_through_its_stages(kind):
    from src.animation.asset_manager import get_asset_manager
    from src.animation.demos import STAGE_COUNT, make_demo
    W, H = 360, 640
    stages = [0.2 + 1.0 * k for k in range(STAGE_COUNT[kind])]
    d = make_demo(kind, (20, 40, 320, 420), stages, get_asset_manager(), 1 / 3)
    frames = []
    for t in [0.1] + [s + 0.9 for s in stages]:
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
        ctx = cairo.Context(surf)
        ctx.set_source_rgb(1, 1, 1)
        ctx.paint()
        d.draw(ctx, t)
        surf.flush()
        frames.append(np.frombuffer(surf.get_data(), np.uint8).copy())
    assert frames[1].std() > 5                                    # visible after the first stage
    diffs = [np.abs(frames[i + 1].astype(int) - frames[i].astype(int)).mean() for i in range(1, len(frames) - 1)]
    assert sum(1 for x in diffs if x > 0.2) >= len(diffs) - 1      # each stage changes the picture
    fx, fy = d.focus(stages[-1] + 0.5)
    assert 0 <= fx <= W and 0 <= fy <= H


# --------------------------------------------------------------------------- story & storyboard
def _script(niche, topic, beats):
    from src.content.models import Script
    return Script.model_validate({"topic": topic, "niche": niche, "format": "short", "title": topic, "hook": beats[0],
                                  "sections": [{"title": "A", "beats": [{"id": f"b{i}", "narration": n}
                                                                         for i, n in enumerate(beats)]}]})


def test_hook_strength_and_review_flags_weak_openings():
    from src.content.retention_review import review_story
    from src.content.story_engine import hook_strength
    weak = hook_strength("Today we are going to talk about the heart and how it works in the body overall.", "heart")
    strong = hook_strength("Your heart beats 72 times a minute. But what starts each beat?", "heart")
    assert strong["score"] >= 6 > weak["score"]
    s = _script("human_body", "How Does the Heart Work?",
                ["Today we are going to talk about the heart.", "The heart pumps blood.", "The heart pumps blood.",
                 "Stay curious!"])
    rev = review_story(s)
    levels = {c["check"]: c["level"] for c in rev["checks"]}
    assert levels["opening_hook"] in ("fail", "warn") and levels["curiosity_gap"] != "pass"
    assert levels["no_repetition_or_filler"] != "pass"


@pytest.mark.parametrize("niche,topic", [("human_body", "How Does Your Heart Actually Work?"),
                                         ("science", "Why Is the Sky Blue?"),
                                         ("psychology", "Why Do We Overthink Everything?")])
def test_curated_samples_get_distinct_identities(settings, niche, topic):
    from pathlib import Path
    from src.animation.themes import THEMES
    from src.content.models import Script
    from src.content.retention_review import review
    from src.content.storyboard_generator import StoryboardGenerator
    from src.utils.text import slugify
    path = Path(__file__).resolve().parents[1] / "content_packs" / slugify(topic) / "script_short.json"
    script = Script.model_validate_json(path.read_text(encoding="utf-8"))
    sb = StoryboardGenerator().build(script, settings.profile("vertical"))
    theme = THEMES[niche]
    assert sb.theme == niche
    own = {b for opts in theme.backgrounds.values() for b in opts}
    assert sum(s.background in own for s in sb.scenes) / len(sb.scenes) >= 0.75
    assert any(s.demo for s in sb.scenes)
    layouts = [s.layout for s in sb.scenes]
    assert len(set(layouts)) >= 6 and not any(a == b == c for a, b, c in zip(layouts, layouts[1:], layouts[2:]))
    assert any(c.cue for s in sb.scenes for c in s.character.cues)          # Milo reacts on spoken words
    rev = review(script, sb)
    assert rev["passed"], [c for c in rev["checks"] if c["level"] == "fail"]


def test_research_filters_off_topic_pages():
    from src.research.researcher import OFF_TOPIC_DESC, expanded_topic, keywords
    assert OFF_TOPIC_DESC.search("2007 studio album by Wilco")
    assert OFF_TOPIC_DESC.search("Former American visual effects and computer animation studio")
    assert not OFF_TOPIC_DESC.search("Light scattering by small particles")
    assert "work" not in keywords("How Does Your Heart Actually Work?")
    assert "Rayleigh scattering" in expanded_topic("Why Is the Sky Blue?")
