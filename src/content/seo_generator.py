"""Titles, descriptions, keywords, hashtags, thumbnail concepts and YouTube chapters.

Sources: an optional curated ``content_packs/<slug>/metadata.json`` (wins), the LLM
(when configured), or deterministic templates. Chapters are always computed from the
real rendered timeline. Source references are appended from the research pack.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from src.config.settings import Settings
from src.content.llm_client import LLMClient, LLMError, load_prompt
from src.content.models import ResearchPack, Script, Storyboard
from src.research.researcher import keywords as topic_keywords

log = logging.getLogger(__name__)

PILLAR_TAGS = {
    "science": ["science", "sciencefacts", "learnontiktok"],
    "human_body": ["humanbody", "biology", "health"],
    "psychology": ["psychology", "brain", "mindset"],
    "mixed": ["science", "funfacts", "didyouknow"],
}


def fmt_ts(t: float) -> str:
    t = int(t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def chapters(storyboard: Storyboard, scene_starts: Dict[str, float]) -> List[Dict]:
    """YouTube chapters: first at 0:00, >= 3 chapters, each >= 10 s (YouTube's rules)."""
    out: List[Dict] = []
    seen = set()
    for sc in storyboard.scenes:
        if sc.section and sc.section not in seen:
            seen.add(sc.section)
            out.append({"start": scene_starts[sc.scene_id], "title": sc.section})
    if out:
        out[0]["start"] = 0.0
    merged: List[Dict] = []
    for i, ch in enumerate(out):
        nxt = out[i + 1]["start"] if i + 1 < len(out) else None
        if merged and nxt is not None and nxt - ch["start"] < 10:
            continue
        merged.append(ch)
    for ch in merged:
        ch["timestamp"] = fmt_ts(ch["start"])
    return merged if len(merged) >= 3 else []


def _hashtags(topic: str, niche: str, short: bool) -> List[str]:
    tags = ["CuriousMinds"] + [w.capitalize() for w in topic_keywords(topic)[:2]]
    tags += [t for t in PILLAR_TAGS.get(niche, PILLAR_TAGS["mixed"])]
    if short:
        tags += ["Shorts"]
    seen, out = set(), []
    for t in tags:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append("#" + re.sub(r"[^A-Za-z0-9]", "", t))
    return out[:8]


QUESTION_WORDS = ("why", "how", "what", "when", "where", "who", "which", "can", "do", "does", "is", "are")


def _as_question(topic: str) -> str:
    """'Why Water Is the Weirdest Substance on Earth' -> '...on Earth?'; statements stay statements."""
    t = topic.strip().rstrip("?").strip()
    return t + "?" if t.split()[0].lower() in QUESTION_WORDS else t + ":"


def tiktok_metadata(script: Script, meta: Dict) -> Dict:
    """TikTok wants a searchable caption (the question people type), a few relevant tags, no #Shorts."""
    tags = [h for h in meta["hashtags"] if h.lower() != "#shorts"][:5]
    caption = f"{_as_question(script.topic)} {script.hook.strip()}"
    if len(caption) > 150:
        caption = caption[:147].rsplit(" ", 1)[0] + "..."
    return {"title": _as_question(script.topic).rstrip(":"), "caption": caption, "hashtags": tags,
            "caption_full": f"{caption} {' '.join(tags)}", "search_keywords": meta["keywords"][:6],
            "opening_hook": script.hook, "cta": script.cta}


def source_lines(research: ResearchPack, limit: int = 8) -> List[str]:
    order = {"authoritative": 0, "peer_reviewed": 1, "reference": 2, "general": 3}
    srcs = sorted(research.sources, key=lambda s: order[s.tier])[:limit]
    return [f"- {s.title}{f' ({s.published})' if s.published else ''}: {s.url}" for s in srcs]


class SEOGenerator:
    def __init__(self, settings: Settings, llm: Optional[LLMClient] = None):
        self.s = settings
        self.llm = llm

    def generate(self, script: Script, storyboard: Storyboard, research: ResearchPack,
                 scene_starts: Optional[Dict[str, float]], pack_dir: Optional[Path] = None) -> Dict:
        short = script.format == "short"
        meta: Dict = {}
        curated = pack_dir / "metadata.json" if pack_dir else None
        if curated and curated.exists():
            data = json.loads(curated.read_text())
            meta = dict(data.get(script.format, {}))
            meta["source"] = "curated"
        elif self.llm is not None:
            try:
                meta = self._llm(script)
                meta["source"] = "llm"
            except (LLMError, KeyError, ValueError) as exc:
                log.warning("LLM metadata failed (%s); using template", exc)
        if not meta.get("titles"):
            meta.update(self._template(script))
            meta["source"] = meta.get("source", "template")
        meta.setdefault("hashtags", _hashtags(script.topic, script.niche, short))
        meta.setdefault("keywords", self._keywords(script, storyboard))
        if scene_starts and not short:
            meta["chapters"] = chapters(storyboard, scene_starts)
        desc = meta.get("description", "").strip()
        if meta.get("chapters"):
            desc += "\n\nChapters:\n" + "\n".join(f"{c['timestamp']} {c['title']}" for c in meta["chapters"])
        if script.niche in ("human_body", "psychology"):
            desc += ("\n\nThis video is for general education only and is not medical advice. "
                     "If you have concerns about your sleep or health, talk to a doctor.")
        desc += "\n\nSources:\n" + "\n".join(source_lines(research))
        desc += "\n\n" + " ".join(meta["hashtags"])
        meta["description_full"] = desc
        meta["format"] = script.format
        if short:
            meta["tiktok"] = tiktok_metadata(script, meta)
        return meta

    def _template(self, script: Script) -> Dict:
        topic = script.topic.rstrip("?")
        q = _as_question(script.topic)
        subject = topic_keywords(script.topic)[0].capitalize()
        if script.format == "short":
            titles = [f"{q} 🤔", f"{q} Explained Simply", f"The Surprising Science of {subject}"]
        else:
            titles = [f"{q} The Fascinating Science Explained", f"{q} What Scientists Really Know",
                      f"The Science of {subject}: A Fun, Curious Deep Dive"]
        hook = script.hook.strip()
        secs = ", ".join(s.title.lower() for s in script.sections[1:5])
        desc = f"{hook}\n\nIn this Curious Minds episode, Milo explores {topic.lower()}" + (f": {secs}." if secs else ".")
        return {"titles": [t[:100] for t in titles], "description": desc,
                "thumbnail_concepts": []}

    def _keywords(self, script: Script, storyboard: Storyboard) -> List[str]:
        from src.animation.asset_manager import get_asset_manager
        am = get_asset_manager()
        kws = topic_keywords(script.topic) + [script.topic.lower().rstrip("?"), script.niche.replace("_", " "),
                                              "curious minds", "science explained", "educational cartoon"]
        for sc in storyboard.scenes:
            for o in sc.objects:
                kws += list(am.record(o.asset).tags[:2])
        seen, out = set(), []
        for k in kws:
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out[:18]

    def _llm(self, script: Script) -> Dict:
        assert self.llm is not None
        schema = {"type": "object", "additionalProperties": False,
                  "required": ["titles", "description", "keywords", "hashtags", "thumbnail_concepts"],
                  "properties": {
                      "titles": {"type": "array", "items": {"type": "string"}},
                      "description": {"type": "string"},
                      "keywords": {"type": "array", "items": {"type": "string"}},
                      "hashtags": {"type": "array", "items": {"type": "string"}},
                      "thumbnail_concepts": {"type": "array", "items": {
                          "type": "object", "additionalProperties": False,
                          "required": ["main_visual", "expression", "text"],
                          "properties": {"main_visual": {"type": "string"}, "expression": {"type": "string"},
                                         "text": {"type": "string"}}}}}}
        data = self.llm.generate_json(load_prompt("metadata_system"),
                                      load_prompt("metadata_user", format_label=script.format, topic=script.topic,
                                                  script=script.full_text), schema, max_tokens=8000)
        if len(data.get("titles", [])) < 3:
            raise ValueError("LLM returned fewer than 3 titles")
        data["titles"] = [t[:100] for t in data["titles"][:3]]
        return data


def write_metadata(meta: Dict, out_dir: Path, name: str) -> Sequence[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    j = out_dir / f"{name}.json"
    j.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    t = out_dir / f"{name}.txt"
    lines = ["TITLE OPTIONS:"] + [f"  {i}. {x}" for i, x in enumerate(meta["titles"], 1)]
    lines += ["", "DESCRIPTION:", meta["description_full"], "", "KEYWORDS:", ", ".join(meta["keywords"])]
    if meta.get("tiktok"):
        tk = meta["tiktok"]
        lines += ["", "TIKTOK:", f"  Title: {tk['title']}", f"  Caption: {tk['caption_full']}",
                  f"  Search keywords: {', '.join(tk['search_keywords'])}", f"  Opening hook: {tk['opening_hook']}",
                  f"  CTA: {tk['cta']}"]
    t.write_text("\n".join(lines), encoding="utf-8")
    return [j, t]
