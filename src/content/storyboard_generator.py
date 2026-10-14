"""Script -> Storyboard conversion (separate storyboards per orientation).

Each script beat becomes one scene. The beat's visual hint (from the writer / LLM / curated
pack) is honoured where valid; everything not specified is directed by rules that now know
the **niche theme** and the **story**:

* story roles -> scene purposes (hook, question, relatable, explain, process, discovery,
  surprise, environment, ending), which pick the theme's environment, camera temperament and
  the narrator's delivery;
* the niche-aware :class:`~src.content.visual_selector.VisualSelector` picks topic-specific
  illustrations (no generic fillers) and an animated **demonstration** whenever the narration
  explains a process it knows how to show;
* composition variety rules (no layout three times in a row, close-ups used sparingly,
  demonstrations spaced out) and non-repeating transition families;
* Milo acts sentence by sentence: thinks on questions, reacts to surprises, points at the
  active part of a diagram when it is mentioned, explains with gestures, waves at the end —
  each cue fires on the spoken word that triggers it.

Every scene is validated with Pydantic; invalid scenes are repaired by progressively simpler
fallbacks and the repair is recorded.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple

from pydantic import ValidationError

from src.animation import registry as R
from src.animation.asset_manager import AssetManager, get_asset_manager
from src.animation.demos import STAGE_COUNT
from src.animation.themes import NicheTheme, resolve_theme
from src.audio.narration_director import classify
from src.config.settings import RenderProfile
from src.content.models import Scene, Script, ScriptBeat, Storyboard, VisualHint
from src.content.story_engine import assign_roles, purpose_for
from src.content.visual_selector import VisualSelector
from src.utils.text import split_sentences, word_count

log = logging.getLogger(__name__)

WORDS_PER_SECOND = 2.85        # planning estimate only; real durations come from the narration audio
COMPOSITION_POOL = ("character_explains", "object_focus", "full_illustration", "network", "diagram_flow",
                    "story_scene", "thought_bubble")
LARGE_ILLUSTRATIONS = {"sunset_scene", "atmosphere_layers", "body_circulation", "blood_vessel", "light_wave",
                       "prism", "pulse_monitor", "heart_cutaway", "galaxy", "black_hole", "overthinking_head",
                       "person_thinking", "decision_signpost"}


def _sentiment(text: str) -> Tuple[str, str]:
    """(action, expression) suggested by the narration."""
    t = text.lower()
    if re.search(r"\b(nightmare|scary|scared|fear|afraid|threat|danger|panic)", t):
        return "talk", "worried"
    if re.search(r"\b(sad|lonely|cry)", t):
        return "talk", "sad"
    if re.search(r"\b(wow|amazing|incredible|surprising|believe it|whoa|crazy|wild)", t):
        return "surprised", "surprised"
    if re.search(r"\b(imagine|picture this|what if)", t):
        return "think", "curious"
    if "?" in text:
        return "think", "curious"
    if re.search(r"\b(theory|idea|scientists think|hypothes|maybe|might)", t):
        return "explain", "thinking"
    if text.strip().endswith("!"):
        return "excited", "excited"
    return "explain", "happy"


def _cue_word(sentence: str) -> Optional[str]:
    words = re.findall(r"[A-Za-z0-9']+", sentence)
    return " ".join(words[:2]) if words else None


class StoryboardGenerator:
    def __init__(self, assets: Optional[AssetManager] = None):
        self.am = assets or get_asset_manager()

    # ------------------------------------------------------------------ layout direction
    def _layout(self, beat: ScriptBeat, idx: int, total: int, purpose: str, demo: Optional[str],
                history: List[str], assets: List[str], fmt: str) -> str:
        v = beat.visual
        t = beat.narration.lower()
        if v.layout:
            return v.layout
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
        if demo:
            return "demonstration"
        recent = history[-3:]
        if purpose == "relatable" and "character_closeup" not in recent and history.count("character_closeup") < (
                2 if fmt == "short" else 5):
            return "character_closeup"
        if re.search(r"\b(versus|vs\.?|compared|unlike|whereas)\b", t) and len(assets) >= 2:
            return "comparison"
        if purpose in ("question",) and "question" not in recent:
            return "question"
        if re.search(r"\b(imagine|dream about|picture)\b", t) and "thought_bubble" not in recent:
            return "thought_bubble"
        big = [a for a in assets if a in LARGE_ILLUSTRATIONS]
        if big and "full_illustration" not in recent[-2:]:
            return "full_illustration"
        for choice in COMPOSITION_POOL[idx % len(COMPOSITION_POOL):] + COMPOSITION_POOL:
            if choice in recent[-2:]:
                continue
            if choice in ("network",) and len(assets) < 3:
                continue
            if choice == "diagram_flow" and len(assets) < 2:
                continue
            if choice == "full_illustration" and not big:
                continue
            return choice
        return "character_explains"

    def _parts_named(self, asset: str, labels: List[str]) -> List[str]:
        """SVG part groups that a label names ("One-way valves" -> valves), so they glow when mentioned."""
        parts = {g for sh in self.am.get(asset).shapes for g in sh.groups}
        out = []
        for lab in labels:
            words = re.findall(r"[a-z]+", lab.lower())
            for p in parts:
                if any(w[:5] == q[:5] for w in words for q in p.split("_") if len(w) > 3 and len(q) > 3):
                    out.append(p)
        return list(dict.fromkeys(out))[:2] if len(out) <= 2 else []

    # ------------------------------------------------------------------ character acting
    def _character(self, beat: ScriptBeat, idx: int, total: int, layout: str, role: str, v: VisualHint,
                   section_start: bool) -> Dict:
        sentences = split_sentences(beat.narration) or [beat.narration]
        act, expr = _sentiment(sentences[0])
        action = v.action or act
        expression = v.expression or expr
        cues: List[Dict] = []
        has_target = layout in ("character_explains", "object_focus", "demonstration", "full_illustration", "chart",
                                "network", "wave_monitor", "diagram_flow", "comparison")
        point_turn = 0
        for k, s in enumerate(sentences[1:], start=1):
            intent = classify(s, first_in_video=False, last_scene=idx == total - 1, last_in_scene=k == len(sentences) - 1,
                              role=role, first_in_scene=False)
            cue = _cue_word(s)
            at = round(min(0.9, k / len(sentences)), 2)
            if intent == "question":
                cues.append({"at": at, "cue": cue, "action": "think", "expression": "curious"})
            elif intent in ("surprise", "transition"):
                cues.append({"at": at, "cue": cue, "action": "surprised", "expression": "surprised"})
            elif intent == "discovery":
                cues.append({"at": at, "cue": cue, "action": "point" if has_target else "excited",
                             "expression": "excited", **({"target": "demo" if layout == "demonstration" else "main"}
                                                         if has_target else {})})
            elif intent == "ending":
                cues.append({"at": at, "cue": cue, "action": "wave", "expression": "happy"})
            elif intent == "relatable":
                cues.append({"at": at, "cue": cue, "action": "shrug" if "?" not in s and k % 2 else "talk",
                             "expression": "happy"})
            else:
                if has_target and point_turn % 2 == 0:
                    cues.append({"at": at, "cue": cue, "action": "point", "expression": "happy",
                                 "target": "demo" if layout == "demonstration" else "main"})
                else:
                    cues.append({"at": at, "cue": cue, "action": "explain", "expression": "happy"})
                point_turn += 1
        if not cues and has_target and word_count(beat.narration) / WORDS_PER_SECOND > 4.5:
            cues.append({"at": 0.5, "action": "point", "expression": expression,
                         "target": "demo" if layout == "demonstration" else "main"})
        if action == "surprised" and not cues:
            cues.append({"at": 0.4, "action": "talk", "expression": "excited"})
        position = "left" if (idx % 4) in (0, 1) else "right"
        if layout in ("list_reveal", "thought_bubble", "chart", "wave_monitor", "story_scene"):
            position = "left"
        if layout == "character_closeup":
            position = "closeup"
        if layout == "demonstration":
            position = "corner_right" if idx % 2 else "corner_left"
        entrance = "pop" if idx == 0 else ("walk" if section_start and idx % 3 == 1 else
                                           "run" if section_start and idx % 3 == 2 else
                                           "slide" if section_start else "none")
        d = {"position": position, "action": action, "expression": expression, "entrance": entrance, "cues": cues}
        if layout in ("character_explains", "object_focus", "full_illustration") and action in ("talk", "explain"):
            d["look_at"] = "main"
        if layout == "demonstration":
            d["look_at"] = "demo"
        if layout == "full_illustration" and idx % 3 == 0:
            d["present"] = False                # let the illustration own the frame now and then
        return d

    # ------------------------------------------------------------------ scene building
    def _scene_dict(self, beat: ScriptBeat, section: str, idx: int, total: int, script: Script, profile: RenderProfile,
                    theme: NicheTheme, sel: VisualSelector, role: str, history: List[str], state: Dict,
                    section_start: bool) -> Dict:
        v: VisualHint = beat.visual
        # ---- demo + purpose
        demo = v.demo.model_dump() if v.demo else None
        if demo is None and not v.layout and 0 < idx < total - 1 and v.number is None and v.chart is None \
                and len(v.items) < 2:
            kind = sel.demo_for(beat.narration)
            cap = 3 if script.format == "short" else 9
            if kind and state["demo_count"][kind] < (1 if script.format == "short" else 2) \
                    and sum(state["demo_count"].values()) < cap and state["since_demo"] >= 1:
                demo = {"kind": kind, "labels": [], "stage_cues": []}
        purpose = purpose_for(role, demo is not None)
        # ---- assets
        picks = sel.select_assets(beat.narration, 4, keywords=v.keywords, prefer=v.assets)
        requested = [a for a in v.assets if self.am.exists(a)]
        assets = list(dict.fromkeys(requested + [p.asset for p in picks]))
        layout = self._layout(beat, idx, total, purpose, demo["kind"] if demo else None, history, assets,
                              script.format)
        if layout == "demonstration" and demo is None:
            kind = sel.demo_for(beat.narration + " " + script.topic) or "neural_signal"
            demo = {"kind": kind, "labels": [], "stage_cues": []}
        if demo is not None and layout != "demonstration":
            demo = None
        if demo:
            state["demo_count"][demo["kind"]] += 1
            state["since_demo"] = 0
            if not demo["stage_cues"]:
                sents = split_sentences(beat.narration)
                n = STAGE_COUNT.get(demo["kind"], 3)
                # stage 0 at the start; later stages on sentence starts / evenly through the words
                words = re.findall(r"[A-Za-z0-9']+", beat.narration)
                cues = []
                for k in range(1, n):
                    if k < len(sents):
                        cues.append(_cue_word(sents[k]))
                    elif words:
                        cues.append(words[min(len(words) - 1, int(len(words) * k / n))])
                demo["stage_cues"] = [c for c in cues if c][:n - 1]
            if not demo["labels"] and v.labels:
                demo["labels"] = [lab[:R.MAX_LABEL_CHARS] for lab in v.labels[:5]]
        else:
            state["since_demo"] += 1
        labels = list(v.labels)
        objects: List[Dict] = []
        items = [i.model_dump(exclude_none=True) for i in v.items]
        overlays: List[Dict] = []
        if layout in ("character_explains", "object_focus", "story_scene", "thought_bubble", "fact_card", "hook_title",
                      "question", "full_illustration", "character_closeup", "demonstration"):
            n_obj = {"thought_bubble": 3, "full_illustration": 1, "character_closeup": 1, "demonstration": 0}.get(layout, 2)
            if requested and layout not in ("thought_bubble",):
                n_obj = min(n_obj, len(requested))
            if layout == "full_illustration":
                big = [a for a in assets if a in LARGE_ILLUSTRATIONS] or assets
                assets = big + [a for a in assets if a not in big]
            for k, a in enumerate(assets[:n_obj]):
                o = {"asset": a, "role": "main" if k == 0 else "secondary"}
                if k == 0 and labels and layout in ("character_explains",):
                    o["label"] = labels[0][:R.MAX_LABEL_CHARS]
                if layout == "thought_bubble":
                    o["role"] = "main" if k == 0 else "item"
                objects.append(o)
            if layout in ("object_focus", "full_illustration"):
                overlays += [{"text": lab[:R.MAX_LABEL_CHARS], "style": "label"} for lab in labels[:4]]
                if objects:
                    objects[0]["highlight"] = self._parts_named(objects[0]["asset"], labels)
        elif layout in ("diagram_flow", "network", "comparison"):
            need = {"diagram_flow": 3, "network": 4, "comparison": 2}[layout]
            pool = (v.assets or assets)
            if len(pool) < need:
                pool = pool + [p.asset for p in sel.select_assets(beat.narration + " " + script.topic, need + 3,
                                                                    min_score=-99) if p.asset not in pool]
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
        if layout == "hook_title" and not v.title:
            overlays.insert(0, {"text": script.topic[:R.MAX_TITLE_CHARS], "style": "title"})
        sel.commit([o["asset"] for o in objects])

        # ---- environment: the theme's backgrounds for this purpose, rotated, never the same as last scene
        if v.background:
            bg = v.background
        else:
            k = state["bg_turn"][purpose]
            bg = theme.background_for(purpose, k)
            if bg == state["prev_bg"] and not (state["prev_section"] == section and purpose == state["prev_purpose"]):
                bg = theme.background_for(purpose, k + 1)
            state["bg_turn"][purpose] += 1
        state["prev_bg"], state["prev_section"], state["prev_purpose"] = bg, section, purpose

        character = self._character(beat, idx, total, layout, role, v, section_start)
        if layout == "outro":
            character["action"], character["expression"] = (v.action or "wave"), (v.expression or "happy")

        # ---- camera, sound, doodles
        move = v.camera or theme.camera.get(purpose, "drift")
        if layout == "demonstration":
            move = "follow" if demo and demo["kind"] in ("light_scattering", "circulation_loop") else "focus"
        elif layout == "full_illustration":
            move = "reveal"
        elif layout == "character_closeup":
            move = "punch_in"
        elif layout == "hook_title":
            move = "punch_in"
        elif layout == "fact_card":
            move = "zoom_in"
        camera = {"move": move, "intensity": 0.7 if move in ("focus", "follow", "reveal") else 0.6}
        sfx = [{"name": n, "at": 0.0} for n in v.sfx]
        if idx == 0 and not sfx:
            sfx.append({"name": "magic", "at": 0.0})
        doodles: List[str] = []
        low = beat.narration.lower()
        ambient = {"bubbles": "bubbles", "twinkle": "twinkle_field", "float_up": "float_up"}
        if layout not in ("outro", "demonstration", "chart") and idx % 2 == 0:
            doodles.append(ambient.get(theme.particles[idx // 2 % len(theme.particles)], "sparkles"))
        if re.search(r"sleep|snooz|asleep|bed", low) and layout in ("story_scene", "character_explains"):
            doodles.append("zzz")
        if layout in ("character_explains", "object_focus") and idx % 3 == 1 and "circle_main" in theme.doodles:
            doodles.append("circle_main")
        if layout == "character_explains" and idx % 3 == 2 and "arrow_to_main" in theme.doodles:
            doodles.append("arrow_to_main")
        if layout == "fact_card":
            doodles.append("stars" if theme.name == "science" else "burst")
        if role in ("discovery", "surprise", "insight") and layout not in ("demonstration",):
            doodles.append("sparkles")
        doodles = list(dict.fromkeys(doodles))

        notes_ill = (f"[{theme.name} · {purpose}] {R.LAYOUTS[layout]} Main visual: "
                     f"{', '.join(o['asset'] for o in objects) or (demo['kind'] if demo else 'mascot only')}. "
                     f"Environment: {R.BACKGROUNDS[bg]}")
        notes_anim = [f"Milo {character['action']} ({character['expression']}) at {character['position']}"]
        notes_anim += [f"on '{c.get('cue') or int(c['at'] * 100)}': {c['action']}" for c in character["cues"]]
        if demo:
            notes_anim.append(f"demo {demo['kind']} stages on {demo['stage_cues']}")
        notes_anim += [f"doodle: {d}" for d in doodles] + [f"camera: {move}"]
        est = word_count(beat.narration) / WORDS_PER_SECOND
        d = {
            "scene_id": f"{'v' if profile.is_vertical else 'h'}{idx + 1:03d}",
            "section": section, "beat_id": beat.id, "narration": beat.narration,
            "est_duration": round(max(1.5, est + 0.75), 2), "layout": layout, "background": bg,
            "purpose": purpose, "role": role, "theme": theme.name,
            "character": character, "objects": objects, "items": items, "text_overlays": overlays,
            "doodles": doodles, "illustration_notes": notes_ill, "animation_notes": notes_anim,
            "camera": camera, "sfx": sfx,
        }
        if demo:
            d["demo"] = demo
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
                  chart=None, number=None, demo=None,
                  text_overlays=[o for o in d2["text_overlays"] if o["style"] in ("title", "bubble")][:1])
        d3["character"] = dict(d["character"], cues=[], action="talk", expression="happy", position="left")
        return Scene.model_validate(d3)

    # ------------------------------------------------------------------ public
    def build(self, script: Script, profile: RenderProfile, music_mood: Optional[str] = None) -> Storyboard:
        beats: List[Tuple[str, int, ScriptBeat]] = [(sec.title, si, b) for si, sec in enumerate(script.sections)
                                                    for b in sec.beats]
        total = len(beats)
        theme = resolve_theme(script.niche, script.topic, script.hook)
        sel = VisualSelector(theme, script.topic, script.niche, self.am)
        roles = assign_roles(script)
        notes: List[str] = [f"theme: {theme.label}"]
        scenes: List[Scene] = []
        history: List[str] = []
        state = {"demo_count": Counter(), "since_demo": 9, "bg_turn": Counter(), "prev_bg": None,
                 "prev_section": None, "prev_purpose": None}
        prev_section = None
        for idx, (sec_title, si, beat) in enumerate(beats):
            d = self._scene_dict(beat, sec_title, idx, total, script, profile, theme, sel, roles[beat.id], history,
                                 state, section_start=sec_title != prev_section)
            sc = self._validate_or_repair(d, notes)
            scenes.append(sc)
            history.append(sc.layout)
            prev_section = sec_title
        # transitions: the theme's family at section boundaries / rhythm points, never the same twice in a row
        k = 0
        last = None
        for i in range(len(scenes) - 1):
            a, b = scenes[i], scenes[i + 1]
            new_section = a.section != b.section
            if new_section or (script.format == "long" and i % 4 == 3) or (script.format == "short" and i % 3 == 2):
                kind = theme.transitions[k % len(theme.transitions)]
                k += 1
                if kind == last:
                    kind = theme.transitions[k % len(theme.transitions)]
                    k += 1
            elif a.background != b.background:
                kind = theme.soft_transition if last != theme.soft_transition else "cut"
            else:
                kind = "cut"
            a.transition_out = kind
            b.transition_in = kind
            if kind != "cut":
                last = kind
        mood = music_mood or ("dreamy" if re.search(r"dream|sleep|night", script.topic.lower()) else theme.music_mood)
        return Storyboard(topic=script.topic, title=script.title, format=script.format, theme=theme.name,
                          orientation="vertical" if profile.is_vertical else "horizontal",
                          width=profile.width, height=profile.height, fps=profile.fps, music_mood=mood,
                          scenes=scenes, generator=f"rules+{script.source}-hints", notes=notes)
