"""Script -> Storyboard conversion (separate storyboards per orientation).

Each script beat becomes one scene. The beat's visual hint (from the writer / LLM /
curated pack) is honoured where valid; everything not specified is filled in by
deterministic direction rules (layout inference, asset search, background rotation,
character acting from the text's sentiment, camera variety, sound design and
section-aware transitions). Every scene is validated with Pydantic; invalid scenes are
repaired by progressively simpler fallbacks and the repair is recorded.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from pydantic import ValidationError

from src.animation import registry as R
from src.animation.asset_manager import AssetManager, get_asset_manager
from src.config.settings import RenderProfile
from src.content.models import Scene, Script, ScriptBeat, Storyboard, VisualHint
from src.content.script_generator import WORDS_PER_SECOND
from src.utils.text import word_count

log = logging.getLogger(__name__)

TOPIC_BACKGROUNDS = [
    (r"dream|sleep|night|rem|nightmare|bed|tired|yawn", ["bedroom_night", "dreamscape", "night_sky", "brain_space"]),
    (r"brain|neuron|memory|mind|think|emotion|psycholog|habit|attention", ["brain_space", "paper", "lab"]),
    (r"space|planet|star|moon|sun|galaxy|rocket", ["space", "night_sky"]),
    (r"cell|dna|blood|heart|body|lung|stomach|organ|muscle|bone", ["lab", "paper"]),
    (r"weather|rain|cloud|tree|nature|plant|animal", ["sunny_outdoors", "paper"]),
    (r"city|car|bus|phone|computer|technology", ["city", "paper"]),
]
NEUTRAL_BACKGROUNDS = ["paper", "lab", "chalkboard", "sunny_outdoors"]
SECTION_TRANSITIONS = ["circle_wipe", "doodle_swipe", "star_zoom", "slide", "dots", "blinds"]
CAMERA_ROTATION = ["drift", "zoom_in", "pan_right", "drift", "zoom_out", "pan_left"]


def _sentiment(text: str) -> Tuple[str, str]:
    """(action, expression) suggested by the narration."""
    t = text.lower()
    if re.search(r"\b(nightmare|scary|scared|fear|afraid|threat|danger)", t):
        return "talk", "worried"
    if re.search(r"\b(sad|lonely|cry)", t):
        return "talk", "sad"
    if re.search(r"\b(wow|amazing|incredible|surprising|believe it|whoa|crazy)", t):
        return "surprised", "surprised"
    if re.search(r"\b(imagine|picture this|what if)", t):
        return "think", "curious"
    if "?" in text:
        return "think", "curious"
    if re.search(r"\b(theory|idea|scientists think|hypothes|maybe|might)", t):
        return "explain", "thinking"
    if text.strip().endswith("!"):
        return "excited", "excited"
    return "talk", "happy"


class StoryboardGenerator:
    def __init__(self, assets: Optional[AssetManager] = None):
        self.am = assets or get_asset_manager()

    # ------------------------------------------------------------------ helpers
    def _backgrounds_for(self, script: Script) -> List[str]:
        text = (script.topic + " " + script.niche).lower()
        for pat, bgs in TOPIC_BACKGROUNDS:
            if re.search(pat, text):
                return bgs + [b for b in NEUTRAL_BACKGROUNDS if b not in bgs]
        return NEUTRAL_BACKGROUNDS

    def _assets_for(self, beat: ScriptBeat, script: Script, n: int = 3) -> List[str]:
        hint = beat.visual
        found = [a for a in hint.assets if self.am.exists(a)]
        if len(found) < n:
            query = " ".join(hint.keywords) + " " + beat.narration
            for a in self.am.search(query, n + 2):
                if a not in found:
                    found.append(a)
        if not found:
            found = self.am.search(script.topic, n) or ["lightbulb"]
        return found[:max(n, len(hint.assets))]

    @staticmethod
    def _infer_layout(beat: ScriptBeat, idx: int, total: int, prev: Optional[str]) -> str:
        t = beat.narration.lower()
        v = beat.visual
        if idx == 0:
            return "hook_title"
        if idx == total - 1:
            return "outro"
        if v.number is not None:
            return "fact_card"
        if v.chart is not None:
            return "chart"
        if len(v.items) >= 2:
            return "list_reveal"
        if re.search(r"\b(versus|vs\.?|compared|unlike|whereas|while .* is)\b", t):
            return "comparison"
        if re.search(r"\b(imagine|dream about|picture)\b", t):
            return "thought_bubble"
        if t.strip().endswith("?"):
            return "question"
        cycle = ["character_explains", "object_focus", "network", "character_explains", "diagram_flow"]
        choice = cycle[idx % len(cycle)]
        return "character_explains" if choice == prev else choice

    # ------------------------------------------------------------------ scene building
    def _scene_dict(self, beat: ScriptBeat, section: str, idx: int, total: int, script: Script, profile: RenderProfile,
                    prev_layout: Optional[str], bg_cycle: List[str], section_idx: int) -> Dict:
        v: VisualHint = beat.visual
        layout = v.layout or self._infer_layout(beat, idx, total, prev_layout)
        assets = self._assets_for(beat, script)
        act, expr = _sentiment(beat.narration)
        action = v.action or act
        expression = v.expression or expr
        labels = list(v.labels)
        objects: List[Dict] = []
        items = [i.model_dump(exclude_none=True) for i in v.items]
        overlays: List[Dict] = []
        if layout in ("character_explains", "object_focus", "story_scene", "thought_bubble", "fact_card", "hook_title",
                      "question"):
            main_role = "main"
            for k, a in enumerate(assets[: (3 if layout == "thought_bubble" else 2)]):
                o = {"asset": a, "role": main_role if k == 0 else "secondary"}
                if k == 0 and labels and layout in ("character_explains",):
                    o["label"] = labels[0][:R.MAX_LABEL_CHARS]
                if layout == "thought_bubble":
                    o["role"] = "main" if k == 0 else "item"
                objects.append(o)
            if layout == "object_focus":
                overlays += [{"text": lab[:R.MAX_LABEL_CHARS], "style": "label"} for lab in labels[:4]]
        elif layout in ("diagram_flow", "network", "comparison"):
            need = {"diagram_flow": 3, "network": 4, "comparison": 2}[layout]
            pool = (v.assets or assets)
            if len(pool) < need:
                pool = pool + [a for a in self.am.search(script.topic + " " + beat.narration, need + 3) if a not in pool]
            pool = pool[:need] if layout == "comparison" else pool[:max(need, min(len(v.assets), 5))]
            for k, a in enumerate(pool):
                o = {"asset": a, "role": "main" if k == 0 else "item"}
                lab_idx = k - 1 if layout == "network" else k
                if 0 <= lab_idx < len(labels):
                    o["label"] = labels[lab_idx][:R.MAX_LABEL_CHARS]
                objects.append(o)
        if layout == "story_scene" and not objects:
            objects.append({"asset": assets[0], "role": "main"})
        if v.title:
            overlays.insert(0, {"text": v.title[:R.MAX_TITLE_CHARS], "style": "title"})
        if v.bubble:
            overlays.append({"text": v.bubble[:R.MAX_BUBBLE_CHARS], "style": "bubble"})
        if layout == "outro":
            overlays.append({"text": (script.cta or "Follow for more!")[:R.MAX_TITLE_CHARS], "style": "cta"})
            action, expression = (v.action or "wave"), (v.expression or "happy")
        if layout == "hook_title" and not v.title:
            overlays.insert(0, {"text": script.topic[:R.MAX_TITLE_CHARS], "style": "title"})

        # backgrounds: keep one per section for continuity, rotate across sections
        bg = v.background or bg_cycle[section_idx % len(bg_cycle)]
        if layout in ("hook_title", "fact_card", "question") and not v.background:
            bg = ["burst_purple", "burst_teal", "burst_orange"][idx % 3]
        if layout == "outro" and not v.background:
            bg = "burst_teal"

        # character
        position = "left" if (idx % 4) in (0, 1) else "right"
        if layout in ("list_reveal", "thought_bubble", "chart", "wave_monitor", "story_scene"):
            position = "left"
        cues = []
        est = word_count(beat.narration) / WORDS_PER_SECOND
        if est > 7 and action in ("talk", "explain"):
            cues.append({"at": 0.55, "action": "point" if layout in ("character_explains", "object_focus", "chart",
                                                                      "network", "wave_monitor") else "explain",
                         "expression": expression})
        if action == "surprised" and est > 4:
            cues.append({"at": 0.4, "action": "talk", "expression": "excited"})
        if action == "think" and est > 4:
            cues.append({"at": 0.5, "action": "explain", "expression": "happy"})
        if action == "excited" and est > 4:
            cues.append({"at": 0.45, "action": "talk", "expression": "happy"})
        character = {"position": position, "action": action, "expression": expression,
                     "entrance": "pop" if idx == 0 else ("walk" if idx % 7 == 3 else "none"), "cues": cues}
        if layout in ("character_explains", "object_focus") and action == "talk":
            character["look_at"] = "main"

        # camera / sound / doodles
        camera = {"move": v.camera or CAMERA_ROTATION[idx % len(CAMERA_ROTATION)], "intensity": 0.6}
        if layout == "hook_title":
            camera = {"move": "punch_in", "intensity": 0.8}
        elif layout == "fact_card":
            camera = {"move": "zoom_in", "intensity": 0.9}
        elif action == "surprised":
            camera = {"move": "shake", "intensity": 0.6}
        sfx = [{"name": n, "at": 0.0} for n in v.sfx]
        if idx == 0 and not sfx:
            sfx.append({"name": "magic", "at": 0.0})
        doodles: List[str] = []
        low = beat.narration.lower()
        if re.search(r"dream|imagin|magic|night", low) and layout not in ("outro",):
            doodles.append("twinkle_field" if bg in ("bedroom_night", "night_sky", "dreamscape", "brain_space", "space")
                           else "sparkles")
        if re.search(r"sleep|snooz|asleep|bed", low) and layout in ("story_scene", "character_explains"):
            doodles.append("zzz")
        if layout in ("character_explains", "object_focus") and idx % 3 == 1:
            doodles.append("circle_main")
        if layout == "character_explains" and idx % 3 == 2:
            doodles.append("arrow_to_main")
        if layout == "fact_card":
            doodles.append("stars")
        if re.search(r"\b(idea|discover|amazing|wow)", low):
            doodles.append("sparkles")
        doodles = list(dict.fromkeys(doodles))

        notes_ill = (f"{R.LAYOUTS[layout]} Main visual: {', '.join(o['asset'] for o in objects) or 'mascot only'}. "
                     f"Background: {R.BACKGROUNDS[bg]}")
        notes_anim = [f"Milo {action} ({expression})"] + [f"at {int(c['at'] * 100)}%: {c['action']}" for c in cues]
        notes_anim += [f"doodle: {d}" for d in doodles]
        d = {
            "scene_id": f"{'v' if profile.is_vertical else 'h'}{idx + 1:03d}",
            "section": section, "beat_id": beat.id, "narration": beat.narration,
            "est_duration": round(max(1.5, est + 0.75), 2), "layout": layout, "background": bg,
            "character": character, "objects": objects, "items": items, "text_overlays": overlays,
            "doodles": doodles, "illustration_notes": notes_ill, "animation_notes": notes_anim,
            "camera": camera, "sfx": sfx,
        }
        if v.number is not None:
            d["number"] = v.number.model_dump()
        if v.chart is not None:
            d["chart"] = v.chart.model_dump()
        return d

    def _validate_or_repair(self, d: Dict, notes: List[str]) -> Scene:
        try:
            return Scene.model_validate(d)
        except ValidationError as exc:
            first = str(exc).splitlines()[0:3]
            notes.append(f"{d['scene_id']}: repaired invalid scene ({' '.join(first)})")
            log.warning("scene %s invalid, repairing: %s", d["scene_id"], exc.errors()[0].get("msg"))
        # repair 1: drop unknown pieces, keep layout
        d2 = dict(d)
        d2["objects"] = [o for o in d["objects"] if self.am.exists(o["asset"])]
        d2["doodles"] = [x for x in d["doodles"] if x in R.DOODLE_KINDS]
        d2["sfx"] = [s for s in d["sfx"] if s["name"] in R.SFX]
        d2["text_overlays"] = [o for o in d["text_overlays"] if len(o["text"]) <= R.MAX_LABEL_CHARS
                               or o["style"] not in ("label",)]
        try:
            return Scene.model_validate(d2)
        except ValidationError:
            pass
        # repair 2: fall back to the most robust layout
        main = next((o["asset"] for o in d2["objects"]), None) or self.am.best_match(d["narration"])
        d3 = dict(d2, layout="character_explains", objects=[{"asset": main, "role": "main"}], items=[],
                  chart=None, number=None,
                  text_overlays=[o for o in d2["text_overlays"] if o["style"] in ("title", "bubble")][:1])
        d3["character"] = dict(d["character"], cues=[], action="talk", expression="happy")
        return Scene.model_validate(d3)

    # ------------------------------------------------------------------ public
    def build(self, script: Script, profile: RenderProfile, music_mood: Optional[str] = None) -> Storyboard:
        beats: List[Tuple[str, int, ScriptBeat]] = [(sec.title, si, b) for si, sec in enumerate(script.sections)
                                                    for b in sec.beats]
        total = len(beats)
        bg_cycle = self._backgrounds_for(script)
        notes: List[str] = []
        scenes: List[Scene] = []
        prev_layout: Optional[str] = None
        for idx, (sec_title, si, beat) in enumerate(beats):
            d = self._scene_dict(beat, sec_title, idx, total, script, profile, prev_layout, bg_cycle, si)
            sc = self._validate_or_repair(d, notes)
            scenes.append(sc)
            prev_layout = sc.layout
        # transitions: bigger wipes at section boundaries, snappy cuts within (shorts cut faster)
        k = 0
        for i in range(len(scenes) - 1):
            a, b = scenes[i], scenes[i + 1]
            new_section = a.section != b.section
            if new_section or (script.format == "long" and i % 4 == 3) or (script.format == "short" and i % 3 == 2):
                kind = SECTION_TRANSITIONS[k % len(SECTION_TRANSITIONS)]
                k += 1
            elif a.background != b.background:
                kind = "dip_cream" if script.format == "long" else "slide"
            else:
                kind = "cut"
            a.transition_out = kind
            b.transition_in = kind
        mood = music_mood or ("dreamy" if re.search(r"dream|sleep|night", script.topic.lower()) else "curious")
        return Storyboard(topic=script.topic, title=script.title, format=script.format,
                          orientation="vertical" if profile.is_vertical else "horizontal",
                          width=profile.width, height=profile.height, fps=profile.fps, music_mood=mood,
                          scenes=scenes, generator=f"rules+{script.source}-hints", notes=notes)
