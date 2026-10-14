import json

import pytest
from pydantic import ValidationError

from src.content.models import Scene, Script, Storyboard
from src.content.script_generator import ScriptError, ScriptGenerator, llm_script_schema
from src.content.storyboard_generator import StoryboardGenerator
from src.research.fact_checker import check_script, extract_facts
from src.research.source_manager import SourceManager, classify_tier

PACK = "content_packs/why_do_we_dream"


def _scene(**kw):
    base = dict(scene_id="s1", narration="Hello there.", est_duration=3, layout="question", background="paper")
    base.update(kw)
    return base


def test_scene_validation_rejects_bad_vocabulary():
    Scene.model_validate(_scene())
    for bad in ({"layout": "explode"}, {"background": "mars"}, {"transition_in": "teleport"},
                {"doodles": ["fireworks"]}, {"character": {"action": "fly"}},
                {"character": {"expression": "smug"}}, {"objects": [{"asset": "unicorn"}]},
                {"sfx": [{"name": "explosion"}]}, {"text_overlays": [{"text": "x" * 80, "style": "title"}]}):
        with pytest.raises(ValidationError):
            Scene.model_validate(_scene(**bad))


def test_layout_requirements():
    with pytest.raises(ValidationError):
        Scene.model_validate(_scene(layout="fact_card"))           # needs a number
    with pytest.raises(ValidationError):
        Scene.model_validate(_scene(layout="list_reveal", items=[{"text": "one"}]))
    Scene.model_validate(_scene(layout="fact_card", number={"value": 90, "suffix": " MIN"}))


def test_storyboard_transition_consistency():
    s1 = _scene(scene_id="a", transition_out="circle_wipe")
    s2 = _scene(scene_id="b", transition_in="slide")
    with pytest.raises(ValidationError):
        Storyboard(topic="t", title="t", format="short", orientation="vertical", width=1080, height=1920,
                   scenes=[Scene(**s1), Scene(**s2)])


def test_curated_packs_valid_and_fact_checked(research_pack):
    for fmt in ("short", "long"):
        sc = Script.model_validate_json(open(f"{PACK}/script_{fmt}.json").read())
        assert sc.source == "curated" and sc.format == fmt
    short = Script.model_validate_json(open(f"{PACK}/script_short.json").read())
    long_ = Script.model_validate_json(open(f"{PACK}/script_long.json").read())
    assert 150 <= short.word_count <= 220
    assert 950 <= long_.word_count <= 1500
    assert short.full_text != long_.full_text          # independent scripts, not a stretched short


def test_fact_checker_flags_unsupported_numbers_and_advice(research_pack):
    good = Script.model_validate({"topic": "t", "niche": "psychology", "format": "short", "title": "t", "hook": "h",
                                  "sections": [{"title": "a", "beats": [
                                      {"id": "b1", "narration": "We spend more than two hours dreaming, in cycles of about 90 minutes."}]}]})
    assert check_script(good, research_pack)["passed"]
    bad = Script.model_validate({"topic": "t", "niche": "psychology", "format": "short", "title": "t", "hook": "h",
                                 "sections": [{"title": "a", "beats": [
                                     {"id": "b1", "narration": "Exactly 73% of people dream in color."},
                                     {"id": "b2", "narration": "If you have nightmares, you should take melatonin."}]}]})
    rep = check_script(bad, research_pack)
    types = {i["type"] for i in rep["issues"]}
    assert not rep["passed"] and {"unsupported_number", "medical_advice"} <= types


def test_fact_extraction_statuses():
    sm = SourceManager(["nih.gov"])
    s = sm.add(title="x", url="https://www.nih.gov/x", provider="t",
               text="Dreams occur mainly during REM sleep in adults. Some researchers suggest dreams may help memory. "
                    "Whether dreams have a function is debated among dream scientists today.")
    facts, unc = extract_facts("Why do we dream", sm.sources, sm.texts)
    st = {f.text[:12]: f.status for f in facts}
    assert st["Dreams occur"] == "established"
    assert st["Some researc"] == "hypothesis"
    assert st["Whether drea"] == "disputed"
    assert classify_tier("https://pubmed.ncbi.nlm.nih.gov/1/", []) == "peer_reviewed"


def test_offline_script_uses_only_research(settings, research_pack):
    sg = ScriptGenerator(settings, llm=None)
    script, rep = sg.generate("Why Do We Dream Tonight?", "psychology", "short", research_pack, 75, source="offline")
    assert script.source == "offline" and rep["passed"]


def test_unresearched_scripts_refused(settings, research_pack):
    empty = research_pack.model_copy(update={"status": "unavailable", "sources": [], "facts": []})
    with pytest.raises(ScriptError):
        ScriptGenerator(settings, llm=None).generate("Unknown Topic Xyz", "science", "short", empty, 75,
                                                     source="offline")


class FakeLLM:
    name = "fake"

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def generate_json(self, system, user, schema, max_tokens=None):
        self.calls.append(user)
        return self.payloads.pop(0)


def _llm_payload(narr):
    v = {"layout": "question", "assets": [], "labels": [], "items": [], "title": None, "bubble": None, "number": None,
         "chart": None, "background": None, "action": None, "expression": None, "sfx": []}
    return {"title": "Dreams", "hook": narr[0], "cta": "Follow!", "sections": [
        {"title": "Part", "beats": [{"id": f"b{i}", "narration": n, "fact_ids": ["F2"], "visual": dict(v)}
                                    for i, n in enumerate(narr)]}]}


def test_llm_script_path_with_repair(settings, research_pack):
    good = ["Dreams happen mostly in REM sleep, and we spend more than two hours dreaming."] * 2
    bad = ["Exactly 73% of people dream every night."] * 2
    fake = FakeLLM([_llm_payload(bad), _llm_payload(good * 6)])
    sg = ScriptGenerator(settings, llm=fake)
    script, rep = sg.generate("Why Do We Dream Llm?", "psychology", "short", research_pack, 75, source="llm")
    assert script.source == "llm" and rep["passed"]
    assert len(fake.calls) == 2 and "REJECTED" in fake.calls[1]


def test_llm_schema_is_closed():
    sch = llm_script_schema()
    assert sch["additionalProperties"] is False
    beat = sch["properties"]["sections"]["items"]["properties"]["beats"]["items"]
    assert set(beat["required"]) == set(beat["properties"])


def test_separate_storyboards(settings):
    sg = StoryboardGenerator()
    short = Script.model_validate_json(open(f"{PACK}/script_short.json").read())
    long_ = Script.model_validate_json(open(f"{PACK}/script_long.json").read())
    v = sg.build(short, settings.profile("vertical"))
    h = sg.build(long_, settings.profile("horizontal"))
    assert v.orientation == "vertical" and h.orientation == "horizontal"
    assert len(h.scenes) > 3 * len(v.scenes)
    for sb in (v, h):
        for sc in sb.scenes:   # every scene carries the full direction set
            assert sc.layout and sc.background and sc.camera and sc.character.action
            assert sc.illustration_notes and sc.animation_notes
        assert len({sc.layout for sc in sb.scenes}) >= (8 if sb is v else 12)
