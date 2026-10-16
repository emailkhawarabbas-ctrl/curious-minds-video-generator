"""Narration direction: every sentence gets a delivery intention before it is spoken.

A flat TTS read sounds robotic mostly because every sentence is delivered the same way:
same pace, same pause, same energy. The director classifies each sentence by its job in
the story (hook, question, explanation, surprising fact, discovery, ending, ...) and turns
that into concrete, provider-neutral performance parameters:

* ``speed``      — tempo multiplier (a surprising fact slows down slightly, a hook is brisk)
* ``pause_before`` / ``pause_after`` — dramatic beats before reveals, room after questions
* ``gain_db``    — small emphasis offsets applied after loudness normalisation (never > +1.5 dB)
* ``instruction``— a spoken-style direction for providers that accept one (OpenAI TTS)
* ``style``      — 0..1 expressiveness for providers with a style control (ElevenLabs)

The voice profile's ``expressiveness`` scales how far deliveries deviate from neutral, so a
calm documentary profile varies less than the energetic one. Text is also lightly shaped for
speech (dashes become breathing commas, ellipses become a real pause) without changing the
words that appear in captions.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Sequence

INTENTS = ("hook", "question", "relatable", "explanation", "transition", "surprise", "discovery", "ending")


@dataclass(frozen=True)
class Delivery:
    intent: str
    speed: float = 1.0
    pause_before: float = 0.0
    pause_after: float = 0.24
    gain_db: float = 0.0
    style: float = 0.35
    instruction: str = ""

    def to_json(self) -> Dict:
        return asdict(self)


# Neutral-profile reference deliveries (expressiveness 0.6). Values were tuned by ear against
# Kokoro am_michael: small speed changes (±5 %) read as intent; larger ones sound processed.
_BASE: Dict[str, Delivery] = {
    "hook": Delivery("hook", 1.03, 0.0, 0.42, 0.8, 0.7,
                     "Open with genuine excitement and curiosity, like sharing a mind-blowing secret. "
                     "Lift the energy, smile while speaking."),
    "question": Delivery("question", 0.98, 0.05, 0.46, 0.3, 0.55,
                         "Ask this as a real, intriguing question with a curious rising tone, then let it hang."),
    "relatable": Delivery("relatable", 1.01, 0.0, 0.28, 0.0, 0.45,
                          "Warm and conversational, as if talking to a friend about something they have felt."),
    "explanation": Delivery("explanation", 1.0, 0.0, 0.24, 0.0, 0.3,
                            "Confident, clear and informative, like a great science teacher. Steady pace."),
    "transition": Delivery("transition", 0.97, 0.12, 0.3, 0.5, 0.6,
                           "Build anticipation: something interesting is about to be revealed."),
    "surprise": Delivery("surprise", 0.95, 0.3, 0.38, 1.0, 0.75,
                         "Deliver this surprising fact with emphasis and a sense of wonder. Slightly slower."),
    "discovery": Delivery("discovery", 1.02, 0.08, 0.32, 0.6, 0.65,
                          "Enthusiastic, like revealing the answer to a mystery. Energetic but clear."),
    "ending": Delivery("ending", 0.97, 0.12, 0.0, 0.3, 0.5,
                       "Friendly, warm and memorable conclusion. Slightly slower, with a smile."),
}

MINI_HOOK = re.compile(
    r"^(but )?(here'?s|here is) (the|where|what)|something (even )?(stranger|weirder|more surprising)|"
    r"this is where (it|things) get|and that'?s not all|plot twist|now here'?s the (twist|thing|catch)|"
    r"but wait|so what('?s| is) (really )?going on", re.I)
SURPRISE = re.compile(
    r"\b(surpris\w*|incredibl\w*|astonish\w*|wild|believe it or not|strange(st)?|weird(est)?|actually|"
    r"in fact|mind-?blowing|shocking|unexpected\w*|amazing|no less than|more than|every single)\b", re.I)
DISCOVERY = re.compile(
    r"\b(discover\w*|found that|turns out|the answer|that'?s why|this is why|the secret|the reason|"
    r"so that'?s|which explains|scientists (now )?(know|think|found|believe)|researchers found)\b", re.I)
RELATABLE = re.compile(r"^(imagine|picture|think about|you know|ever|we'?ve all|you'?ve|you have)\b|\b(you|your)\b",
                       re.I)


def classify(sentence: str, *, first_in_video: bool, last_scene: bool, last_in_scene: bool,
             role: Optional[str] = None, first_in_scene: bool = False) -> str:
    """Delivery intent for one sentence. ``role`` is the story role of the beat, if known."""
    s = sentence.strip()
    words = len(s.split())
    if first_in_video:
        return "hook"
    if last_scene:
        return "ending"
    if role in ("ending", "conclusion") and last_in_scene:
        return "ending"
    if MINI_HOOK.search(s):
        return "transition" if words <= 9 else "surprise"
    if s.endswith("?"):
        return "question"
    if role in ("hook", "opening_mystery") and first_in_scene:
        return "hook"
    if role in ("surprise", "insight", "unexpected_discovery") and first_in_scene:
        return "surprise"
    if role in ("discovery", "payoff", "resolution") and first_in_scene:
        return "discovery"
    if DISCOVERY.search(s):
        return "discovery"
    if SURPRISE.search(s):
        return "surprise"
    if role in ("relatable", "scenario") or RELATABLE.search(s):
        return "relatable"
    return "explanation"


def delivery_for(intent: str, expressiveness: float = 0.6) -> Delivery:
    """Scale a reference delivery by the profile's expressiveness (0 = neutral read, 1 = most expressive)."""
    base = _BASE.get(intent, _BASE["explanation"])
    k = max(0.0, min(1.0, expressiveness)) / 0.6
    return Delivery(
        intent=intent,
        speed=round(1.0 + (base.speed - 1.0) * k, 4),
        pause_before=round(base.pause_before * (0.6 + 0.4 * k), 3),
        pause_after=round(base.pause_after * (0.75 + 0.25 * k), 3),
        gain_db=round(min(1.5, base.gain_db * k), 2),
        style=round(min(1.0, base.style * (0.7 + 0.3 * k)), 2),
        instruction=base.instruction,
    )


def shape_for_speech(text: str) -> str:
    """Light, meaning-preserving text shaping for natural phrasing (TTS input only)."""
    t = re.sub(r"\s*[—–]\s*", ", ", text)              # em/en dashes -> a breathing comma
    t = re.sub(r"\s*\.\.\.\s*", "... ", t)               # keep ellipses as a real pause
    t = re.sub(r"\(([^)]*)\)", r", \1,", t)               # parentheticals become a phrase
    t = re.sub(r"\s*,\s*,", ",", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = re.sub(r",\s*([.!?])", r"\1", t)
    return t


def direct_scene(sentences: Sequence[str], *, scene_index: int, scene_count: int, role: Optional[str],
                 expressiveness: float) -> List[Delivery]:
    out: List[Delivery] = []
    for i, s in enumerate(sentences):
        intent = classify(s, first_in_video=(scene_index == 0 and i == 0), last_scene=scene_index == scene_count - 1,
                          last_in_scene=i == len(sentences) - 1, role=role, first_in_scene=i == 0)
        out.append(delivery_for(intent, expressiveness))
    return out
