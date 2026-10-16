"""Niche-aware visual selection: which illustrations and demonstrations explain *this* beat?

The old planner ranked assets by raw keyword overlap, so any beat could end up with a star,
a rocket or a planet. The selector instead works from a **concept ontology**: each concept
(heart, circulation, light scattering, overthinking, threat response ...) knows the
narration patterns that evoke it, the assets that depict it (best first), the animated
demonstration that explains it, and its home niche.

For a beat it scores candidate assets by:
  +10  depicts a concept the beat talks about (ordered by how well it depicts it)
  + 4  depicts a concept of the topic itself
  + 2  keyword overlap with the beat (id / title / tags)
  + 3 / +1  belongs to the theme's first / second preferred asset category
  − 6  generic filler (star, rocket, planet, trophy ...) not explicitly evoked
  − 5  off-niche asset with no concept match in the beat
  − 3  per previous use in this video (novelty), − 8 if used in the previous scene

Every pick carries its reasons, and :meth:`relevance` scores any asset against any text for
the visual review in the quality report.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.animation.asset_manager import AssetManager, get_asset_manager
from src.animation.themes import NicheTheme

_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Concept:
    name: str
    pattern: str
    assets: Tuple[str, ...]
    demo: Optional[str] = None
    niche: str = "any"

    def hits(self, text: str) -> int:
        return len(re.findall(self.pattern, text, re.I))


C = Concept
CONCEPTS: Tuple[Concept, ...] = (
    # ---------------------------------------------------------------- human body
    C("heart", r"\bheart(?!felt)|cardiac|heartbeat|\bbeats?\b|chambers?|ventricle|atri(um|a)", (
        "heart_cutaway", "heart", "pulse_monitor", "stethoscope"), "heart_pump", "human_body"),
    C("circulation", r"circulat|blood (flow|vessel|stream)|arter(y|ies)|\bveins?\b|capillar|around (your|the) body|"
                     r"bloodstream|whole body", ("body_circulation", "blood_vessel", "red_blood_cell"),
      "circulation_loop", "human_body"),
    C("blood", r"\bblood\b|red blood|plasma", ("red_blood_cell", "blood_cells", "blood_vessel"), None, "human_body"),
    C("oxygen", r"oxygen|\bo2\b|carbon dioxide", ("oxygen_o2", "lungs", "red_blood_cell"), "circulation_loop",
      "human_body"),
    C("lungs", r"\blungs?\b|breath|inhale|exhale|respirat", ("lungs", "oxygen_o2"), None, "human_body"),
    C("heart_rhythm", r"electric(al)? (signal|spark|impulse|pulse)|pacemaker|sinoatrial|\brhythm|beats per minute|"
                      r"heart rate|\becg\b|\bekg\b|spark", ("pulse_monitor", "lightning", "heart"), "ecg_heartbeat",
      "human_body"),
    C("immune", r"immun|germs?|infection|white blood|defen[cs]e|antibod", ("white_blood_cell", "blood_cells"), None,
      "human_body"),
    C("doctor", r"doctor|check-?up|stethoscope|hospital|medical", ("stethoscope", "pulse_monitor"), None, "human_body"),
    C("muscle", r"muscle|exercise|workout|strength", ("muscle",), None, "human_body"),
    C("bones", r"\bbones?\b|skeleton", ("bone",), None, "human_body"),
    C("digestion", r"stomach|digest|\bfood\b|\bgut\b", ("stomach",), None, "human_body"),
    C("eye", r"\beyes?\b|vision|\bsight\b|retina", ("eye",), None, "any"),
    C("ear", r"\bears?\b|hearing", ("ear", "wave_sound"), None, "human_body"),
    C("cells", r"\bcells?\b|\bdna\b|\bgenes?\b", ("cell", "dna"), None, "human_body"),
    # ---------------------------------------------------------------- science
    C("sunlight", r"sunlight|sun'?s light|white light|light from the sun|\bthe sun\b|\bsun\b", (
        "sun", "prism"), "light_scattering", "science"),
    C("scattering", r"scatter|bounc(e|es|ing) (off|around)|rayleigh|in every direction|all directions", (
        "nitrogen_n2", "light_wave", "observer_kid"), "light_scattering", "science"),
    C("wavelength", r"wavelength|short(er)? waves?|long(er)? waves?|frequenc|\bwaves? of light", (
        "light_wave", "prism"), "wavelength_compare", "science"),
    C("colours", r"\bcolou?rs?\b|rainbow|spectrum|violet|indigo", ("prism", "light_wave"), None, "science"),
    C("sky", r"\bsky\b|\bskies\b", ("atmosphere_layers", "observer_kid", "sun"), "light_scattering", "science"),
    C("atmosphere", r"atmospher|\bair\b|\bgas(es)?\b|nitrogen|molecul", (
        "atmosphere_layers", "nitrogen_n2", "oxygen_o2", "molecule"), None, "science"),
    C("sunset", r"sunsets?|sunrises?|red sky|orange sky|evening|dusk|horizon", ("sunset_scene", "sun"),
      "sunset_path", "science"),
    C("space", r"\bspace\b|universe|cosmos|astronaut", ("galaxy", "planet_saturn", "rocket", "star"), None,
      "science"),
    C("black_hole", r"black holes?|event horizon|gravity|gravitational", ("black_hole", "galaxy"), None, "science"),
    C("planets", r"planets?|saturn|solar system|\borbit", ("planet_saturn", "earth", "sun"), None, "science"),
    C("moon", r"\bmoon\b|lunar", ("moon",), None, "science"),
    C("earth", r"\bearth\b|our planet|\bglobe\b", ("earth", "atmosphere_layers"), None, "science"),
    C("electricity", r"electric|lightning|\benergy\b|\bvolts?\b", ("lightning", "atom"), None, "science"),
    C("magnet", r"magnet", ("magnet",), None, "science"),
    C("atoms", r"\batoms?\b|nucleus|electrons?|protons?", ("atom", "molecule"), None, "science"),
    C("chemistry", r"chemi|reaction|experiment|\blab\b", ("flask", "molecule", "microscope"), None, "science"),
    C("weather", r"weather|\brain\b|clouds?|storm", ("weather_cloud_rain", "thermometer"), None, "science"),
    C("nature", r"\bplants?\b|\btrees?\b|flowers?|photosynth|ocean", ("tree", "flower"), None, "science"),
    C("observe", r"telescope|astronom|observ|scientists? (looked|measured)", ("telescope", "observer_kid"), None,
      "science"),
    C("sound", r"\bsound|vibrat|\bnoise", ("wave_sound",), None, "science"),
    C("history", r"\b1[6-9]\d\d\b|\bcentury\b|physicist|scientist named", ("books_stack", "telescope", "microscope"),
      None, "any"),
    # ---------------------------------------------------------------- psychology
    C("overthinking", r"overthink|ruminat|over and over|replay|can'?t stop thinking|what if|what-if|racing thoughts", (
        "overthinking_head", "thought_spiral", "person_thinking"), "thought_loop", "psychology"),
    C("thought_loop", r"\bloops?\b|spiral|\bstuck\b|again and again|round and round|repeat", (
        "thought_spiral", "overthinking_head"), "thought_loop", "psychology"),
    C("worry", r"\bworr|anxi|nervous|\bstress|uneasy|tense", ("worried_face", "emotion_scared"), None, "psychology"),
    C("threat", r"threat|danger|alarm|amygdala|fight or flight|surviv|predator|protect you", (
        "amygdala_alarm", "emotion_scared"), "alarm_response", "psychology"),
    C("decision", r"decid|decision|choices?|choos|options?|dilemma", ("decision_signpost", "balance_scale"),
      "decision_tree", "psychology"),
    C("weighing", r"pros and cons|weigh|trade-?off", ("balance_scale",), None, "psychology"),
    C("social", r"\btext(ed|s)?\b|message|conversation|friends?|what (they|she|he) (said|meant)|social|awkward", (
        "chat_bubbles", "phone"), None, "psychology"),
    C("thinking", r"\bthink|thoughts?\b|\bmind\b|ponder|brain does", ("person_thinking", "thought_cloud", "brain"),
      None, "psychology"),
    C("brain", r"\bbrains?\b|neuro|cortex", ("brain", "brain_activity", "neuron"), None, "any"),
    C("neurons", r"neurons?|synaps|\bnerves?\b|signals? (travel|jump)|pathway", ("neuron", "nervous_system"),
      "neural_signal", "any"),
    C("memory", r"memor|remember|recall|\blearn", ("memory_photos", "brain", "neuron"), "neural_signal",
      "psychology"),
    C("emotion", r"emotions?|feelings?", ("emotion_happy", "emotion_sad", "emotion_surprised"), None, "psychology"),
    C("calm", r"\bcalm|relief|relax|breathe slowly|peace", ("emotion_happy",), None, "psychology"),
    C("sad", r"\bsad\b|unhappy|lonely", ("emotion_sad",), None, "psychology"),
    C("fear", r"\bfear|afraid|scared|scary|panic", ("emotion_scared", "amygdala_alarm"), None, "psychology"),
    C("attention", r"attention|focus|concentrat|distract", ("attention_target",), None, "psychology"),
    C("habit", r"\bhabits?\b|routine", ("habit_loop",), None, "psychology"),
    C("insight", r"\bidea\b|insight|realiz|eureka|solution|solve", ("lightbulb", "puzzle_piece"), None, "any"),
    C("sleep", r"\bsleep|asleep|\bbed\b|tired|insomnia", ("sleeping_person", "moon_sleepy", "bed"), None,
      "psychology"),
    C("dream", r"\bdream", ("dream_cloud", "thought_cloud"), None, "psychology"),
    C("night", r"\bnight|\b(2|3) ?a\.?m\.?|midnight|late", ("moon_sleepy", "clock"), None, "psychology"),
    C("time", r"\bminutes?\b|\bhours?\b|\bclock\b", ("clock", "alarm_clock"), None, "any"),
    C("phone", r"\bphones?\b|scroll|notification|screen", ("phone",), None, "any"),
    C("question", r"\bwhy\b|\bhow come\b|mystery|\bpuzzle", ("question_mark",), None, "any"),
)

GENERIC_FILLERS = {"star", "rocket", "planet_saturn", "gift_box", "trophy", "lightbulb", "question_mark", "earth",
                   "moon", "puzzle_piece", "magnifying_glass", "books_stack"}


@dataclass
class Pick:
    asset: str
    score: float
    reasons: List[str] = field(default_factory=list)


class VisualSelector:
    def __init__(self, theme: NicheTheme, topic: str, niche: str, assets: Optional[AssetManager] = None):
        self.am = assets or get_asset_manager()
        self.theme, self.topic, self.niche = theme, topic, niche
        self.topic_concepts = self.concepts_in(topic)
        self.used: Dict[str, int] = {}
        self.prev_scene: set = set()

    # ------------------------------------------------------------------ analysis
    @staticmethod
    def concepts_in(text: str) -> List[Tuple[Concept, int]]:
        found = [(c, c.hits(text)) for c in CONCEPTS]
        return sorted([(c, h) for c, h in found if h], key=lambda ch: -ch[1])

    def analyze(self, text: str) -> Dict:
        """What a beat is about: concepts, body parts / emotions / objects it needs, and a demo if any."""
        cs = self.concepts_in(text)
        return {"concepts": [c.name for c, _ in cs],
                "required_assets": list(dict.fromkeys(a for c, _ in cs for a in c.assets[:2] if self.am.exists(a))),
                "demo": self.demo_for(text)}

    # ------------------------------------------------------------------ scoring
    def _tag_overlap(self, asset: str, words: set) -> int:
        r = self.am.record(asset)
        ids = set(_WORD.findall(asset.replace("_", " ")))
        tags = set(w for t in r.tags for w in _WORD.findall(t))
        return 3 * len(words & ids) + len(words & tags)

    def score(self, asset: str, text: str, beat_concepts: Sequence[Tuple[Concept, int]]) -> Pick:
        r = self.am.record(asset)
        s, why = 0.0, []
        for c, h in beat_concepts:
            if asset in c.assets:
                w = 10 - 2 * c.assets.index(asset)
                s += w + min(h, 3)
                why.append(f"depicts '{c.name}' (+{w})")
                break
        for c, _ in self.topic_concepts:
            if asset in c.assets:
                s += 4
                why.append(f"topic concept '{c.name}' (+4)")
                break
        words = set(_WORD.findall(text.lower()))
        words |= {w[:-1] for w in words if w.endswith("s") and len(w) > 3}
        ov = self._tag_overlap(asset, words)
        if ov:
            s += min(6, 2 * ov)
            why.append(f"keyword overlap (+{min(6, 2 * ov)})")
        cats = self.theme.asset_categories
        if r.category == cats[0]:
            s += 3
            why.append(f"{self.theme.name} identity (+3)")
        elif len(cats) > 1 and r.category == cats[1]:
            s += 1
        concept_match = any(asset in c.assets for c, _ in beat_concepts)
        if asset in GENERIC_FILLERS and not concept_match:
            s -= 6
            why.append("generic filler (-6)")
        if r.category not in cats[:2] and not concept_match:
            s -= 5
            why.append("off-niche (-5)")
        n = self.used.get(asset, 0)
        if n:
            s -= 3 * n
            why.append(f"used {n}x (-{3 * n})")
        if asset in self.prev_scene:
            s -= 8
            why.append("in previous scene (-8)")
        return Pick(asset, round(s, 2), why)

    def select_assets(self, text: str, n: int = 3, keywords: Iterable[str] = (), prefer: Sequence[str] = (),
                      exclude: Iterable[str] = (), min_score: float = 4.0) -> List[Pick]:
        query = f"{text} {' '.join(keywords)}"
        beat_concepts = self.concepts_in(query)
        cand = {a for c, _ in beat_concepts for a in c.assets} | {a for c, _ in self.topic_concepts for a in c.assets}
        cand |= set(self.am.search(query, 12))
        cand = {a for a in cand if self.am.exists(a)} - set(exclude)
        picks = [self.score(a, query, beat_concepts) for a in cand]
        for p in picks:
            if p.asset in prefer:
                p.score += 12
                p.reasons.insert(0, "requested by script (+12)")
        picks.sort(key=lambda p: (-p.score, p.asset))
        good = [p for p in picks if p.score >= min_score]
        if not good and picks:
            good = picks[:1]
        return good[:n]

    def commit(self, assets: Iterable[str]) -> None:
        """Record what a scene used (novelty bookkeeping)."""
        cur = set(assets)
        for a in cur:
            self.used[a] = self.used.get(a, 0) + 1
        self.prev_scene = cur

    def demo_for(self, text: str) -> Optional[str]:
        best: Optional[Tuple[int, str]] = None
        for c, h in self.concepts_in(text):
            if not c.demo:
                continue
            home = c.niche in ("any", self.theme.name)
            score = h * (2 if home else 1)
            if best is None or score > best[0]:
                best = (score, c.demo)
        return best[1] if best else None

    def relevance(self, asset: str, text: str) -> float:
        """0..1: how well an asset fits a text (for the visual review)."""
        if not self.am.exists(asset):
            return 0.0
        beat_concepts = self.concepts_in(text)
        if any(asset in c.assets for c, _ in beat_concepts):
            return 1.0
        if any(asset in c.assets for c, _ in self.topic_concepts):
            return 0.75
        words = set(_WORD.findall(text.lower()))
        ov = self._tag_overlap(asset, words)
        return min(0.6, 0.2 * ov) if ov else (0.1 if asset not in GENERIC_FILLERS else 0.0)
