"""Pre-render storytelling and visual review (an internal checklist, not a retention prediction).

Run on the script + storyboard before rendering. Produces ``review/storytelling_<fmt>.json``
and is merged into the per-video quality report. Real retention can only come from platform
analytics (see ``src/analytics``); nothing here claims to know it.

Storytelling checks: opening hook strength, curiosity questions (opened early, resolved later),
mini-hooks (present, not repetitive), discoveries/surprises, educational payoff (facts used,
ending resolves the opening), unnecessary narration (near-duplicate sentences, filler).

Visual / pacing checks: visual change rate, long static sequences, repeated compositions,
repeated backgrounds/transitions, asset relevance to narration, niche identity, missing assets,
character consistency, text-heavy scenes.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Optional

from src.animation import registry as R
from src.animation.asset_manager import get_asset_manager
from src.animation.themes import THEMES, resolve_theme
from src.content.models import Script, Storyboard
from src.content.story_engine import assign_roles, hook_strength, mini_hooks_in
from src.content.visual_selector import VisualSelector

FILLER = re.compile(r"\b(basically|literally|you know what i mean|as i said|like i said|needless to say|"
                    r"it is important to note|let'?s dive in|without further ado)\b", re.I)
_TOK = re.compile(r"[a-z']+")
STOP = set("the a an and or but of to in on at is are was were be been it its this that these those for with as by "
           "from your you we our they their there here so if then than when what why how which who can could "
           "would should will just about into over more most very also not no yes do does did".split())


def _content(text: str) -> set:
    return {w for w in _TOK.findall(text.lower()) if w not in STOP and len(w) > 2}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _chk(name: str, level: str, detail: str, area: str) -> Dict:
    return {"check": name, "level": level, "passed": level != "fail", "detail": detail, "area": area}


def review_story(script: Script) -> Dict:
    beats = script.beats
    roles = assign_roles(script)
    texts = [b.narration for b in beats]
    checks: List[Dict] = []
    hook = hook_strength(texts[0] if texts else "", script.topic)
    lvl = "pass" if hook["score"] >= 6 else ("warn" if hook["score"] >= 4 else "fail")
    checks.append(_chk("opening_hook", lvl, f"score {hook['score']}/10: {'; '.join(hook['reasons']) or 'ok'}", "story"))
    # curiosity: questions asked early, resolved by a later discovery/ending
    q_idx = [i for i, t in enumerate(texts) if "?" in t]
    early_q = [i for i in q_idx if i <= max(2, len(texts) // 5)]
    resolved = False
    if early_q:
        q_words = _content(" ".join(texts[i] for i in early_q))
        late = " ".join(texts[len(texts) // 2:])
        resolved = len(q_words & _content(late)) >= 2
    checks.append(_chk("curiosity_gap", "pass" if early_q and resolved else ("warn" if q_idx else "fail"),
                       f"{len(q_idx)} questions ({len(early_q)} in the opening); "
                       f"{'resolved later' if resolved else 'not clearly resolved'}", "story"))
    minis = mini_hooks_in(texts)
    rep = [m for m, c in Counter(x.lower() for x in minis).items() if c > 1]
    want = 1 if script.format == "short" else 3
    lvl = "fail" if rep else ("pass" if len(minis) >= want else "warn")
    checks.append(_chk("mini_hooks", lvl, f"{len(minis)} mini-hooks{'; repeated: ' + ', '.join(rep) if rep else ''}",
                       "story"))
    disc = [b.id for b in beats if roles[b.id] in ("discovery", "surprise", "insight")]
    checks.append(_chk("discoveries", "pass" if len(disc) >= (2 if script.format == "short" else 5) else "warn",
                       f"{len(disc)} discovery/surprise beats", "story"))
    # payoff: facts cited + ending connects back to the opening
    cited = {f for b in beats for f in b.fact_ids}
    end_link = _jaccard(_content(texts[0]), _content(" ".join(texts[-2:]))) if len(texts) > 2 else 0
    grounded = bool(cited) or script.source == "curated"
    checks.append(_chk("educational_payoff", "pass" if grounded and end_link > 0.04 else "warn",
                       f"{len(cited)} research facts cited{' (curated, source-reviewed pack)' if script.source == 'curated' else ''}; "
                       f"ending↔opening overlap {end_link:.2f}", "story"))
    # unnecessary narration
    sents = [s for t in texts for s in re.split(r"(?<=[.!?])\s+", t) if len(s.split()) > 3]
    dups = []
    for i in range(len(sents)):
        for j in range(i + 1, len(sents)):
            if _jaccard(_content(sents[i]), _content(sents[j])) > 0.6:
                dups.append((sents[i][:50], sents[j][:50]))
    filler = [m.group(0) for t in texts for m in FILLER.finditer(t)]
    lvl = "fail" if len(dups) > 1 else ("warn" if dups or filler else "pass")
    checks.append(_chk("no_repetition_or_filler", lvl,
                       f"{len(dups)} near-duplicate sentences, filler: {', '.join(filler) or 'none'}", "story"))
    return {"roles": roles, "hook": hook, "questions": [texts[i] for i in q_idx], "mini_hooks": minis,
            "discoveries": disc, "checks": checks}


def review_visuals(script: Script, sb: Storyboard, scene_durations: Optional[Dict[str, float]] = None) -> Dict:
    am = get_asset_manager()
    theme = THEMES.get(sb.theme) or resolve_theme(script.niche, script.topic)
    sel = VisualSelector(theme, script.topic, script.niche, am)
    checks: List[Dict] = []
    scenes = sb.scenes
    dur = {s.scene_id: (scene_durations or {}).get(s.scene_id) or s.duration or s.est_duration for s in scenes}
    # visual change rate & static sequences
    events = {s.scene_id: len(s.objects) + len(s.items) + len(s.text_overlays) + (4 if s.demo else 0)
              + (3 if s.chart else 0) + len(s.character.cues) + (1 if s.camera.move not in ("static",) else 0)
              for s in scenes}
    static = [f"{s.scene_id} ({dur[s.scene_id]:.1f}s, {events[s.scene_id]} visual events)" for s in scenes
              if dur[s.scene_id] / max(1, events[s.scene_id]) > (4.5 if sb.format == "short" else 6.5)]
    total = sum(dur.values())
    rate = len(scenes) / total * 60 if total else 0
    checks.append(_chk("visual_change_rate", "pass" if rate >= (8 if sb.format == "short" else 5) else "warn",
                       f"{rate:.1f} scene changes per minute", "pacing"))
    checks.append(_chk("no_long_static_scenes", "pass" if not static else ("warn" if len(static) <= 2 else "fail"),
                       "; ".join(static[:5]) or "every scene has steady visual activity", "pacing"))
    # repetition
    runs, run = [], 1
    for a, b in zip(scenes, scenes[1:]):
        run = run + 1 if a.layout == b.layout else 1
        if run >= 3:
            runs.append(b.scene_id)
    checks.append(_chk("composition_variety", "fail" if runs else "pass",
                       f"{len(set(s.layout for s in scenes))} compositions; 3-in-a-row at {runs or 'none'}", "pacing"))
    tr = [s.transition_out for s in scenes[:-1] if s.transition_out != "cut"]
    tr_rep = [a for a, b in zip(tr, tr[1:]) if a == b]
    checks.append(_chk("transition_variety", "warn" if tr_rep else "pass",
                       f"{len(set(tr))} transition styles; back-to-back repeats: {len(tr_rep)}", "pacing"))
    bg_counts = Counter(s.background for s in scenes)
    checks.append(_chk("background_variety", "pass" if len(bg_counts) >= min(4, len(scenes) // 2) else "warn",
                       f"{len(bg_counts)} environments: {dict(bg_counts.most_common(4))}", "visuals"))
    # relevance & identity
    rel_rows, low = [], []
    for s in scenes:
        for o in s.objects:
            r = sel.relevance(o.asset, f"{s.narration} {script.topic}")
            rel_rows.append(r)
            if r < 0.3:
                low.append(f"{s.scene_id}:{o.asset}")
    mean_rel = sum(rel_rows) / len(rel_rows) if rel_rows else 1.0
    checks.append(_chk("topic_specific_visuals", "pass" if mean_rel >= 0.6 and len(low) <= 2 else
                       ("warn" if mean_rel >= 0.45 else "fail"),
                       f"mean asset relevance {mean_rel:.2f}; weak picks: {', '.join(low[:6]) or 'none'}", "visuals"))
    niche_bgs = {b for opts in theme.backgrounds.values() for b in opts}
    share_bg = sum(1 for s in scenes if s.background in niche_bgs) / len(scenes)
    cats = Counter(am.record(o.asset).category for s in scenes for o in s.objects if am.exists(o.asset))
    share_cat = (sum(cats[c] for c in theme.asset_categories[:1]) / sum(cats.values())) if cats else 0
    demos = [s.demo.kind for s in scenes if s.demo]
    checks.append(_chk("niche_identity", "pass" if share_bg >= 0.6 and (share_cat >= 0.35 or demos) else "warn",
                       f"theme {theme.name}: {share_bg:.0%} niche environments, {share_cat:.0%} niche assets, "
                       f"{len(demos)} animated demonstrations {sorted(set(demos))}", "visuals"))
    explain = [s for s in scenes if s.purpose in ("explain", "process", "discovery")]
    visual_expl = [s for s in explain if s.demo or s.chart or s.layout in ("object_focus", "diagram_flow", "comparison",
                                                                            "full_illustration", "network", "timeline")]
    checks.append(_chk("visual_explanations", "pass" if not explain or len(visual_expl) / len(explain) >= 0.6 else "warn",
                       f"{len(visual_expl)}/{len(explain)} explanation scenes use a diagram, demo or labelled "
                       "illustration", "visuals"))
    missing = [o.asset for s in scenes for o in s.objects if not am.exists(o.asset)]
    checks.append(_chk("no_missing_assets", "fail" if missing else "pass", ", ".join(missing) or "all assets exist",
                       "visuals"))
    chars = {s.character.character for s in scenes if s.character.present}
    checks.append(_chk("character_consistency", "pass" if len(chars) <= 1 else "warn",
                       f"mascot(s): {sorted(chars)}", "visuals"))
    passive = [s.scene_id for s in scenes if s.character.present and not s.character.cues
               and s.character.action in ("talk", "idle") and dur[s.scene_id] > 6]
    checks.append(_chk("character_participation", "pass" if len(passive) <= len(scenes) // 5 else "warn",
                       f"{len(passive)} long scenes where Milo only talks: {passive[:5]}", "visuals"))
    heavy = [s.scene_id for s in scenes if sum(len(o.text) for o in s.text_overlays) + sum(len(i.text) for i in s.items) > 150]
    checks.append(_chk("not_text_heavy", "pass" if not heavy else "warn", f"text-heavy scenes: {heavy or 'none'}",
                       "visuals"))
    return {"theme": theme.name, "mean_asset_relevance": round(mean_rel, 2), "demos": demos, "checks": checks}


def review(script: Script, sb: Storyboard, scene_durations: Optional[Dict[str, float]] = None) -> Dict:
    story = review_story(script)
    visuals = review_visuals(script, sb, scene_durations)
    checks = story["checks"] + visuals["checks"]
    return {"passed": not any(c["level"] == "fail" for c in checks), "story": story, "visuals": visuals,
            "checks": checks, "note": "Heuristic pre-render checklist; actual audience retention is only known "
                                      "from platform analytics."}
