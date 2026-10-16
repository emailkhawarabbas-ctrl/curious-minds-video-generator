"""Retention-oriented story structure: beat roles, scene purposes and curiosity connectors.

Short (60-90 s) arc — a guideline, not a stopwatch:
    hook -> curiosity_gap -> relatable -> discovery -> explanation (visual) -> surprise/insight -> ending
Long-form arc:
    hook (opening mystery) -> relatable scenario -> question -> [discovery -> explanation -> example]* with
    transitions (mini-hooks) between sections -> insight -> recap -> ending (resolves the opening question)

Every beat gets a ``role``; scenes get a ``purpose`` that drives the niche theme's environment,
camera temperament and the narrator's delivery. Curiosity connectors (mini-hooks) are drawn from
varied pools and never repeated within a video.
"""
from __future__ import annotations

import random
import re
from typing import Dict, List, Optional, Sequence

from src.content.models import Script, ScriptBeat

ROLE_TO_PURPOSE = {
    "hook": "hook", "curiosity_gap": "question", "question": "question", "relatable": "relatable",
    "explanation": "explain", "discovery": "discovery", "surprise": "surprise", "insight": "surprise",
    "example": "environment", "transition": "question", "recap": "explain", "ending": "ending",
}

SHORT_ARC = ("hook", "curiosity_gap", "relatable", "discovery", "explanation", "surprise", "ending")

MINI_HOOKS = {
    "surprise": ["But here's the surprising part:", "Here's the twist:", "And this is where it gets strange:",
                 "Now here's something most people never notice:"],
    "deeper": ["But that raises a bigger question.", "So what's really going on?", "And it goes even deeper.",
               "But that's only half the story."],
    "discovery": ["Scientists finally figured it out.", "And the answer is hiding in plain sight.",
                  "It turns out the explanation is beautifully simple."],
}

WEAK_OPENINGS = re.compile(r"^(today|in this video|hi,? i'?m|hello|welcome|let'?s (talk|learn|explore)|"
                           r"we('re| are) going to|have you ever wondered)\b", re.I)
_MINI = re.compile(r"(here'?s the (surprising|twist|strange|catch|thing)|but here'?s|this is where (it|things) get|"
                   r"something (even )?(stranger|weirder)|and that'?s not all|so what'?s (really )?going on|"
                   r"it turns out|but that'?s only|the answer is)", re.I)


def infer_role(beat: ScriptBeat, idx: int, total: int, fmt: str) -> str:
    if beat.role:
        return beat.role
    t = beat.narration.strip()
    low = t.lower()
    if idx == 0:
        return "hook"
    if idx == total - 1:
        return "ending"
    if beat.visual.number is not None:
        return "surprise"
    if _MINI.search(low):
        return "surprise" if len(t.split()) > 10 else "transition"
    if re.search(r"\b(imagine|picture this|you know (that|when)|we'?ve all|you'?ve (probably )?(felt|seen|noticed))", low):
        return "relatable"
    if t.endswith("?"):
        return "curiosity_gap" if idx <= 2 else "question"
    if re.search(r"\b(discover|found that|turns out|the answer|that'?s why|this is why|the reason)", low):
        return "discovery"
    if re.search(r"\b(surpris|incredibl|actually|in fact|believe it or not|more than|wild)", low):
        return "surprise"
    if re.search(r"\b(for example|like when|for instance|think of)", low):
        return "example"
    if re.search(r"\b(so,? (in short|basically)|to recap|in other words)", low):
        return "recap"
    return "explanation"


def assign_roles(script: Script) -> Dict[str, str]:
    beats = script.beats
    return {b.id: infer_role(b, i, len(beats), script.format) for i, b in enumerate(beats)}


def purpose_for(role: str, has_demo: bool = False) -> str:
    p = ROLE_TO_PURPOSE.get(role, "explain")
    if has_demo and p in ("explain", "discovery", "question"):
        return "process"
    return p


class ConnectorPool:
    """Varied, non-repeating mini-hooks for generated (offline) scripts."""

    def __init__(self, seed: int = 0):
        self.rnd = random.Random(seed)
        self.left = {k: self.rnd.sample(v, len(v)) for k, v in MINI_HOOKS.items()}

    def take(self, kind: str) -> Optional[str]:
        pool = self.left.get(kind) or []
        return pool.pop() if pool else None


def hook_strength(text: str, topic: str) -> Dict:
    """0..10 score for an opening line, with the reasons (heuristic; not a retention prediction)."""
    s = text.strip()
    first = re.split(r"(?<=[.!?])\s+", s)[0] if s else ""
    words = len(first.split())
    score, why = 5.0, []
    if WEAK_OPENINGS.search(s):
        score -= 4
        why.append("starts with a generic opener (today / in this video / welcome)")
    if re.search(r"\byou(r)?\b", s, re.I):
        score += 1.5
        why.append("speaks to the viewer (+)")
    if "?" in s:
        score += 1.5
        why.append("poses a question (+)")
    if re.search(r"\d", s) or re.search(r"\b(hundred|thousand|million|billion|every (second|day|night))\b", s, re.I):
        score += 1
        why.append("concrete number / scale (+)")
    if re.search(r"\b(but|yet|actually|secret|never|strange|weird|surpris|impossible|why)\b", s, re.I):
        score += 1
        why.append("tension / mystery word (+)")
    if words > 20:
        score -= 2
        why.append(f"first sentence is long ({words} words)")
    topic_words = {w for w in re.findall(r"[a-z]{4,}", topic.lower()) if w not in ("does", "your", "what", "actually",
                                                                                    "everything", "work", "they")}
    if topic_words and not any(w[:5] in s.lower() for w in topic_words):
        score -= 2
        why.append("does not mention the topic")
    return {"score": round(max(0.0, min(10.0, score)), 1), "first_sentence": first, "reasons": why}


def mini_hooks_in(texts: Sequence[str]) -> List[str]:
    return [m.group(0) for t in texts for m in _MINI.finditer(t)]
