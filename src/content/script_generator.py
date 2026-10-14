"""Script generation: LLM (Claude), curated content packs, or an offline template.

``script_source``:
  * ``curated`` — ``content_packs/<slug>/script_<short|long>.json`` (reviewed, versioned scripts)
  * ``llm``     — Claude writes the script from the research facts (JSON schema + Pydantic validation,
                  fact-check, up to 2 repair rounds with the validation errors fed back)
  * ``offline`` — deterministic template built from extracted research facts (no API keys; plainer prose)
  * ``auto``    — curated if a pack exists, else llm if a key is set, else offline
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import ValidationError

from src.animation import registry as R
from src.animation.asset_manager import get_asset_manager
from src.config.settings import Settings
from src.content.llm_client import LLMClient, LLMError, get_llm, load_prompt
from src.content.models import Format, ResearchPack, Script
from src.research.fact_checker import check_script
from src.utils.text import slugify, split_sentences

log = logging.getLogger(__name__)

# Planning pace incl. directed pauses; the active voice profile's measured words_per_second overrides it
WORDS_PER_SECOND = 2.85


class ScriptError(RuntimeError):
    pass


def target_words(fmt: Format, seconds: float, wps: float = WORDS_PER_SECOND) -> int:
    return int(seconds * wps * (0.93 if fmt == "short" else 0.95))


# --------------------------------------------------------------------------- JSON schema for the LLM
def _nullable(schema: Dict) -> Dict:
    return {"anyOf": [schema, {"type": "null"}]}


def llm_script_schema() -> Dict:
    am = get_asset_manager()
    from src.animation.character_engine import ACTIONS
    from src.animation.expression_engine import load_expressions
    item = {"type": "object", "additionalProperties": False, "required": ["text", "asset", "cue"],
            "properties": {"text": {"type": "string"}, "asset": _nullable({"type": "string", "enum": am.ids()}),
                           "cue": _nullable({"type": "string"})}}
    demo = _nullable({"type": "object", "additionalProperties": False, "required": ["kind", "labels", "stage_cues"],
                      "properties": {"kind": {"type": "string", "enum": list(R.DEMOS)},
                                     "labels": {"type": "array", "items": {"type": "string"}},
                                     "stage_cues": {"type": "array", "items": {"type": "string"}}}})
    visual = {
        "type": "object", "additionalProperties": False,
        "required": ["layout", "demo", "assets", "labels", "items", "title", "bubble", "number", "chart", "background",
                     "action", "expression", "sfx"],
        "properties": {
            "layout": {"type": "string", "enum": list(R.LAYOUTS)},
            "demo": demo,
            "assets": {"type": "array", "items": {"type": "string", "enum": am.ids()}},
            "labels": {"type": "array", "items": {"type": "string"}},
            "items": {"type": "array", "items": item},
            "title": _nullable({"type": "string"}),
            "bubble": _nullable({"type": "string"}),
            "number": _nullable({"type": "object", "additionalProperties": False,
                                 "required": ["value", "suffix", "label"],
                                 "properties": {"value": {"type": "number"}, "suffix": {"type": "string"},
                                                "label": {"type": "string"}}}),
            "chart": _nullable({"type": "object", "additionalProperties": False,
                                "required": ["kind", "points", "values", "labels", "x_labels"],
                                "properties": {"kind": {"type": "string", "enum": list(R.CHART_KINDS)},
                                               "points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
                                               "values": {"type": "array", "items": {"type": "number"}},
                                               "labels": {"type": "array", "items": {"type": "string"}},
                                               "x_labels": {"type": "array", "items": {"type": "string"}}}}),
            "background": _nullable({"type": "string", "enum": list(R.BACKGROUNDS)}),
            "action": _nullable({"type": "string", "enum": list(ACTIONS)}),
            "expression": _nullable({"type": "string", "enum": sorted(load_expressions())}),
            "sfx": {"type": "array", "items": {"type": "string", "enum": list(R.SFX)}},
        }}
    beat = {"type": "object", "additionalProperties": False,
            "required": ["id", "role", "narration", "fact_ids", "visual"],
            "properties": {"id": {"type": "string"}, "role": {"type": "string", "enum": list(R.STORY_ROLES)},
                           "narration": {"type": "string"},
                           "fact_ids": {"type": "array", "items": {"type": "string"}}, "visual": visual}}
    return {"type": "object", "additionalProperties": False, "required": ["title", "hook", "sections", "cta"],
            "properties": {"title": {"type": "string"}, "hook": {"type": "string"}, "cta": {"type": "string"},
                           "sections": {"type": "array", "items": {
                               "type": "object", "additionalProperties": False, "required": ["title", "beats"],
                               "properties": {"title": {"type": "string"},
                                              "beats": {"type": "array", "items": beat}}}}}}


def _clean_visual(v: Dict) -> Dict:
    """Drop nulls / empty values so the Pydantic VisualHint defaults apply."""
    out = {k: val for k, val in v.items() if val not in (None, [], "")}
    if "number" in out:
        n = out["number"]
        out["number"] = {"value": n["value"], "suffix": n.get("suffix", "")[:16], "label": n.get("label", "")[:40]}
    if "chart" in out:
        out["chart"] = {k: val for k, val in out["chart"].items() if val not in (None,)}
    if "items" in out:
        out["items"] = [{k: val for k, val in it.items() if val is not None} for it in out["items"]]
    if "demo" in out:
        d = out["demo"]
        out["demo"] = {"kind": d["kind"], "labels": [str(x)[:R.MAX_LABEL_CHARS] for x in d.get("labels", [])][:5],
                       "stage_cues": [str(x).split()[0] for x in d.get("stage_cues", []) if str(x).strip()][:5]}
    return out


def script_from_llm_json(data: Dict, topic: str, niche: str, fmt: Format) -> Script:
    sections = []
    for sec in data.get("sections", []):
        beats = [{"id": b["id"], "role": b.get("role"), "narration": b["narration"].strip(),
                  "fact_ids": b.get("fact_ids", []), "visual": _clean_visual(b.get("visual", {}))}
                 for b in sec.get("beats", [])]
        sections.append({"title": sec["title"][:60], "beats": beats})
    return Script.model_validate({"topic": topic, "niche": niche, "format": fmt, "title": data["title"],
                                  "hook": data["hook"], "cta": data.get("cta", ""), "sections": sections,
                                  "source": "llm"})


# --------------------------------------------------------------------------- generator
class ScriptGenerator:
    def __init__(self, settings: Settings, llm: Optional[LLMClient] = None):
        self.s = settings
        self.llm = llm if llm is not None else get_llm(settings)

    # ------------------------------------------------------------------ selection
    def pack_dir(self, topic: str) -> Path:
        return self.s.paths.content_packs / slugify(topic)

    def resolve_source(self, topic: str, fmt: Format, requested: str) -> str:
        if requested != "auto":
            return requested
        if (self.pack_dir(topic) / f"script_{fmt}.json").exists():
            return "curated"
        return "llm" if self.llm is not None else "offline"

    def generate(self, topic: str, niche: str, fmt: Format, research: ResearchPack, duration_s: float,
                 source: str = "auto", source_texts: Optional[Dict[str, str]] = None) -> Tuple[Script, Dict]:
        src = self.resolve_source(topic, fmt, source)
        if research.status == "unavailable" and src != "curated" and not self.s.content.allow_unresearched:
            raise ScriptError("research unavailable: refusing to write an unresearched script "
                              "(set content.allow_unresearched to override)")
        log.info("generating %s script for %r via %s", fmt, topic, src)
        if src == "curated":
            script = self._curated(topic, fmt)
        elif src == "llm":
            if self.llm is None:
                raise ScriptError("script_source=llm but no LLM is configured (set LLM_API_KEY)")
            script = self._llm(topic, niche, fmt, research, duration_s, source_texts)
        elif src == "offline":
            script = self._offline(topic, niche, fmt, research, duration_s)
        else:
            raise ScriptError(f"unknown script source {src!r}")
        report = check_script(script, research, source_texts)
        return script, report

    # ------------------------------------------------------------------ curated
    def _curated(self, topic: str, fmt: Format) -> Script:
        path = self.pack_dir(topic) / f"script_{fmt}.json"
        if not path.exists():
            raise ScriptError(f"no curated script at {path}")
        try:
            return Script.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise ScriptError(f"curated script {path} is invalid:\n{exc}") from exc

    # ------------------------------------------------------------------ llm
    def _llm(self, topic: str, niche: str, fmt: Format, research: ResearchPack, duration_s: float,
             source_texts: Optional[Dict[str, str]]) -> Script:
        assert self.llm is not None
        am = get_asset_manager()
        from src.animation.character_engine import ACTIONS
        from src.animation.expression_engine import load_expressions
        words = target_words(fmt, duration_s, self.s.tts.active.words_per_second)
        structure = ("Structure (a guideline, not a stopwatch): opening hook -> curiosity gap -> relatable "
                     "situation -> unexpected discovery -> visual scientific explanation (demonstration) -> "
                     "surprising insight -> memorable ending that answers the hook. 1-4 sections, 8-11 beats."
                     if fmt == "short" else
                     "Documentary structure: strong opening mystery, a relatable real-world scenario, clear "
                     "questions, then 4-6 sections of progressive discoveries, each with a visual demonstration, "
                     "a scientific explanation and an interesting example; meaningful mini-hook transitions between "
                     "sections; unexpected connections; a satisfying conclusion that resolves the opening mystery. "
                     "6-8 sections, 30-45 beats. Every section must add genuine educational value; no padding.")
        facts = "\n".join(f"{f.id} | {f.status} | {f.text}" for f in research.facts) or "(none)"
        from src.animation.themes import resolve_theme
        theme = resolve_theme(niche, topic)
        user = load_prompt(
            "script_user", format_label="60-90 second vertical short" if fmt == "short" else "6-10 minute long-form",
            topic=topic, niche=niche, theme=theme.label, target_words=str(words),
            demos="\n".join(f"- {k}: {v}" for k, v in R.DEMOS.items()),
            duration_label=f"~{int(duration_s)} seconds of narration", structure=structure,
            layouts="\n".join(f"- {k}: {v}" for k, v in R.LAYOUTS.items()),
            assets="\n".join(f"- {a}: {', '.join(am.record(a).tags[:6])}" for a in am.ids()),
            backgrounds=", ".join(R.BACKGROUNDS), actions=", ".join(ACTIONS),
            expressions=", ".join(sorted(load_expressions())), sfx=", ".join(R.SFX), facts=facts,
            beat_words=str(R.MAX_SCENE_WORDS[fmt] - 5))
        system = load_prompt("script_system")
        schema = llm_script_schema()
        feedback = ""
        last_err: Optional[str] = None
        for attempt in range(3):
            try:
                data = self.llm.generate_json(system, user + feedback, schema)
                script = script_from_llm_json(data, topic, niche, fmt)
                report = check_script(script, research, source_texts)
                if not report["passed"]:
                    raise ScriptError("fact-check failed: " + json.dumps(report["issues"])[:2000])
                from src.content.retention_review import review_story
                story = review_story(script)
                bad = [c for c in story["checks"] if c["level"] == "fail"]
                if bad:
                    raise ScriptError("storytelling review failed: " + "; ".join(f"{c['check']}: {c['detail']}"
                                                                                 for c in bad))
                n = script.word_count
                if not (0.75 * words <= n <= 1.3 * words):
                    raise ScriptError(f"script has {n} words; target is about {words}")
                return script
            except (ValidationError, ScriptError, LLMError, KeyError, TypeError) as exc:
                last_err = str(exc)[:3000]
                log.warning("LLM script attempt %d rejected: %s", attempt + 1, last_err[:300])
                if isinstance(exc, LLMError) and "declined" not in last_err:
                    raise ScriptError(f"LLM failure: {exc}") from exc
                feedback = ("\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED. Fix these problems and return the full "
                            f"script again:\n{last_err}")
        raise ScriptError(f"LLM could not produce a valid script after 3 attempts: {last_err}")

    # ------------------------------------------------------------------ offline template
    def _offline(self, topic: str, niche: str, fmt: Format, research: ResearchPack, duration_s: float) -> Script:
        """Plain but factual template: every sentence is (lightly adapted) research text."""
        words_target = target_words(fmt, duration_s, self.s.tts.active.words_per_second)
        am = get_asset_manager()
        est = [f for f in research.facts if f.status == "established"]
        hyp = [f for f in research.facts if f.status == "hypothesis"]
        other = [f for f in research.facts if f.status == "uncertain"]
        pool = est + other
        if not pool:
            raise ScriptError("offline generator needs at least one research fact")

        from src.content.story_engine import ConnectorPool

        def beat(i: int, text: str, fids: List[str], layout: Optional[str] = None, role: Optional[str] = None,
                 **vis) -> Dict:
            v = {"layout": layout} if layout else {}
            v.update(vis)
            return {"id": f"b{i}", "role": role, "narration": text, "fact_ids": fids, "visual": v}

        q = topic.rstrip("?")
        hooks = {"human_body": f"Your body does this every single day without asking you. {q}?",
                 "psychology": f"We all do it, and almost nobody stops to ask why. {q}?",
                 "science": f"It looks simple, until you really look closer. {q}?"}
        beats_intro = [beat(1, hooks.get(niche, hooks["science"]), [], "hook_title", "hook", title=topic[:48],
                            action="surprised", expression="curious"),
                       beat(2, "The real answer is hiding in plain sight, and it's stranger than most people think.",
                            [], None, "curiosity_gap", action="think", expression="curious")]
        pool_c = ConnectorPool(seed=len(topic))
        body: List[Dict] = []
        i = 3
        used = 0
        for k, f in enumerate(pool):
            if used >= words_target * 0.68:
                break
            sent = _spoken(f.text)
            role = "explanation"
            if f.numbers and k > 0:
                lead = pool_c.take("surprise")
                if lead:
                    sent, role = f"{lead} {sent[0].lower() + sent[1:] if sent[:2] != 'I ' else sent}", "surprise"
            elif k == 1:
                role = "discovery"
            body.append(beat(i, sent, [f.id], None, role))
            used += len(sent.split())
            i += 1
            if k in (2, 6) and len(pool) > k + 1:
                t = pool_c.take("deeper")
                if t:
                    body.append(beat(i, t, [], None, "transition"))
                    i += 1
        theories: List[Dict] = []
        for f in hyp[: (2 if fmt == "short" else 6)]:
            theories.append(beat(i, "One idea scientists are still testing: " + _spoken(f.text), [f.id], None,
                                 "insight", action="think", expression="thinking"))
            i += 1
        outro = [beat(i, f"So, {q[0].lower() + q[1:]}? Now you know what's going on behind the scenes. "
                         f"Stay curious!", [], "outro", "ending")]
        if fmt == "short":
            sections = [{"title": "The question", "beats": beats_intro + body[:6]},
                        {"title": "What scientists think", "beats": theories[:2] + outro}]
        else:
            chunk = max(3, len(body) // 4)
            sections = [{"title": "Introduction", "beats": beats_intro}]
            for k in range(0, len(body), chunk):
                sections.append({"title": f"Part {k // chunk + 1}", "beats": body[k:k + chunk]})
            sections.append({"title": "Theories", "beats": theories or [beat(i + 1, "Scientists are still "
                                                                              "investigating the details.", [])]})
            sections.append({"title": "Wrap-up", "beats": outro})
        return Script.model_validate({"topic": topic, "niche": niche, "format": fmt, "title": topic,
                                      "hook": beats_intro[0]["narration"], "cta": "Stay curious!",
                                      "sections": sections, "source": "offline",
                                      "notes": ["Offline template: factual but plain wording. Set LLM_API_KEY or "
                                                "add a curated content pack for production-quality scripts."]})


def _spoken(sentence: str) -> str:
    s = re.sub(r"\([^)]*\)", "", sentence)
    s = re.sub(r"\s+", " ", s).strip()
    words = s.split()
    if len(words) > 40:
        s = " ".join(words[:40]).rstrip(",;:") + "."
    return split_sentences(s)[0] if split_sentences(s) else s
