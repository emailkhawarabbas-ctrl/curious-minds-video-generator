"""Turn a user script into a storyboard: the whiteboard look (default), the lively look or the classic look.

Fields a scene leaves out get defaults that keep consecutive scenes different:
  visual     best tag match for the scene text in the asset library (never the previous scene's)
  animation  whiteboard: draw_on. lively: pop_in for the hook, then draw_on / pop_in / slide_in / bounce in turn
  camera     whiteboard: zoom_in / zoom_out in turn (calm). lively: zoom_in, pan_right, zoom_out, pan_left, ...
  host       left, right, center (waist-up close-up), corner_right, corner_left in turn
  pose       whiteboard: read from the text (see whiteboard_action). lively: think for questions,
             excited for exclamations, explain / point / present otherwise
  enter      whiteboard: the host walks in on scene 1
  transition whip_left, zoom_through, whip_up, ink_swipe, whip_right in turn
  headline   scene 1 shows the title (text on screen from the first frame)
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from src.animation import registry as R
from src.animation.asset_manager import get_asset_manager
from src.animation.themes import resolve_mascot
from src.config.settings import RenderProfile
from src.content.models import (CharacterCueSpec, CharacterDirection, LivelyDirection, ObjectSpec, Scene, SfxCue,
                                Script, ScriptBeat, ScriptSection, Storyboard, VisualHint)
from src.content.storyboard_generator import WORDS_PER_SECOND, StoryboardGenerator
from src.script_mode.schema import ScriptFileError, UserScene, UserScript, asset_id

ANIMATIONS = ("draw_on", "pop_in", "slide_in", "bounce")
CAMERAS = ("zoom_in", "pan_right", "zoom_out", "pan_left", "drift", "pan_up")
HOSTS = ("left", "right", "center", "corner_right", "corner_left")
TRANSITIONS = ("whip_left", "zoom_through", "whip_up", "ink_swipe", "whip_right")
WORRY = re.compile(r"\b(tired|drunk|worse|risk|danger|sick|slow|forget|crash|mistake|bad|fail|hurt|stress)", re.I)


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def _check_lengths(us: UserScript, path: str) -> None:
    limit = R.MAX_SCENE_WORDS[us.format]
    problems = [f"scene {i}: {_words(sc.spoken)} words is too long for one scene (max {limit}); split it in two"
                for i, sc in enumerate(us.scenes, 1) if _words(sc.spoken) > limit]
    if problems:
        raise ScriptFileError(path, problems)


def pick_visual(sc: UserScene, previous: Optional[str]) -> str:
    if sc.visual:
        return asset_id(sc.visual)
    am = get_asset_manager()
    for cand in am.search(sc.spoken, 6):
        if cand != previous:
            return cand
    return am.best_match(sc.spoken)


def host_pose(sc: UserScene, i: int) -> Tuple[str, str]:
    text = sc.spoken
    if sc.pose or sc.expression:
        return sc.pose or "explain", sc.expression or "happy"
    if text.rstrip().endswith("?"):
        return "think", "curious"
    if "!" in text:
        return "excited", "excited"
    if WORRY.search(text):
        return "explain", "worried"
    return ("explain", "point", "present", "talk")[i % 4], "happy"


QUESTION = re.compile(r"\?\s*$")
SHRUG = re.compile(r"\b(nobody knows|no one knows|maybe|might|not sure|unclear|mystery|who knows|depends)\b", re.I)
SMALL_NUMBER = re.compile(r"\b(one|two|three|first|second|third|twice|double|triple|[1-3])\b", re.I)
SHOCK = re.compile(r"!|\b(actually|even|huge|drunk|shocking|insane|crazy|never|blackout|amazing|surprising|"
                   r"weird|strange|secret)\b", re.I)
PROCESS = re.compile(r"\b(because|causes?|makes?|then|so|leads?|turns?|means|shifts?|struggles?|works|happens|"
                     r"process|when|until|after)\b", re.I)
WB_EXPRESSION = {"think": "thinking", "shrug": "confused", "count": "determined", "surprised": "surprised",
                 "draw": "happy", "hold_up": "excited", "explain": "happy", "point": "happy", "present": "happy"}
WB_CAMERAS = ("zoom_in", "zoom_out")


def whiteboard_action(sc: UserScene, i: int, history: List[str]) -> Tuple[str, str]:
    """The host's action for a scene, read from its text; actions are spread out over the video.

    question -> think, "nobody knows" -> shrug, a small number -> count on fingers, a shocking fact
    -> surprised, a process ("because", "then", "makes") -> draw the keyword, extra visuals -> hold
    one up, otherwise explain / point / present in turn."""
    if sc.pose:
        return sc.pose, sc.expression or WB_EXPRESSION.get(sc.pose, "happy")
    text = sc.spoken
    cands = []
    if QUESTION.search(text):
        cands.append("think")
    if SHRUG.search(text):
        cands.append("shrug")
    if SMALL_NUMBER.search(text):
        cands.append("count")
    if SHOCK.search(text):
        cands.append("surprised")
    if PROCESS.search(text):
        cands.append("draw")
    if sc.visuals:
        cands.append("hold_up")
    cands += [("explain", "point", "present")[(i + k) % 3] for k in range(3)]
    previous = history[-1] if history else None
    score = {a: k + 2.5 * history.count(a) for k, a in reversed(list(enumerate(cands)))}
    action = min((a for a in score if a != previous), key=lambda a: score[a])
    expression = sc.expression or ("worried" if action in ("explain", "point", "present") and WORRY.search(text)
                                   else WB_EXPRESSION.get(action, "happy"))
    return action, expression


def build_lively(us: UserScript, profile: RenderProfile, path: str = "script", layout: str = "spotlight") -> Storyboard:
    """``layout`` = spotlight (the lively look) or whiteboard (hand-drawn explainer, see src/lively/whiteboard.py)."""
    _check_lengths(us, path)
    wb = layout == "whiteboard"
    actions: List[str] = []
    host_char = us.character or resolve_mascot(us.niche, us.title, " ".join(s.spoken for s in us.scenes))
    n = len(us.scenes)
    scenes: List[Scene] = []
    prev_visual: Optional[str] = None
    prev_host = None
    for i, sc in enumerate(us.scenes):
        visual = pick_visual(sc, prev_visual)
        prev_visual = visual
        position = sc.host or HOSTS[i % len(HOSTS)]
        if position == prev_host and sc.host is None:
            position = HOSTS[(i + 1) % len(HOSTS)]
        action, expression = whiteboard_action(sc, i, actions) if wb else host_pose(sc, i)
        actions.append(action)
        if wb and sc.host is None and position == "center" and action in ("draw", "count", "hold_up"):
            position = "right" if prev_host == "left" else "left"     # these need the host's arms in view
        prev_host = position
        cues = []
        if not wb and sc.emphasis and action not in ("excited", "surprised"):
            cues.append(CharacterCueSpec(at=0.5, cue=sc.emphasis[0], action="excited" if "!" in sc.text else "point",
                                         expression="excited" if "!" in sc.text else expression, target="main"))
        headline = sc.headline or (us.title if i == 0 else None)
        if headline and len(headline) > R.MAX_TITLE_CHARS:
            headline = headline[:R.MAX_TITLE_CHARS - 1].rsplit(" ", 1)[0] + "…"
        t_in = "cut" if i == 0 else (us.scenes[i - 1].transition or TRANSITIONS[(i - 1) % len(TRANSITIONS)])
        last = i == n - 1
        t_out = (sc.transition or TRANSITIONS[i % len(TRANSITIONS)]) if (not last or us.loop_to_start) else "cut"
        if last and us.loop_to_start and t_out == "cut":
            t_out = "zoom_through"
        if wb:
            animation = sc.animation or "draw_on"
            camera = sc.camera or WB_CAMERAS[i % len(WB_CAMERAS)]
            entrance = sc.host_enter or ("walk" if i == 0 else "none")
        else:
            animation = sc.animation or ("pop_in" if i == 0 else ANIMATIONS[i % len(ANIMATIONS)])
            camera = sc.camera or CAMERAS[i % len(CAMERAS)]
            entrance = sc.host_enter or "pop"
        scenes.append(Scene(
            scene_id=f"s{i + 1:02d}", section="main", beat_id=f"b{i + 1}", narration=sc.spoken,
            est_duration=max(1.6, _words(sc.spoken) / WORDS_PER_SECOND + 0.75), layout=layout,
            background="doodle_paper", purpose="hook" if i == 0 else "explain",
            role="hook" if i == 0 else ("ending" if last else "explanation"),
            character=CharacterDirection(character=host_char, present=position != "none",
                                         position=position if position != "none" else "left", action=action,
                                         expression=expression, entrance=entrance,
                                         exit=sc.host_exit or "none", cues=cues),
            objects=[ObjectSpec(asset=visual, role="main")],
            sfx=[SfxCue(name=x, at=0.0) for x in sc.sfx_list],
            camera={"move": "drift", "intensity": 1.0},
            transition_in=t_in, transition_out=t_out,
            lively=LivelyDirection(animation=animation, camera=camera, emphasis=sc.emphasis,
                                   shake=sc.shake, headline=headline,
                                   visuals=[asset_id(v) for v in sc.visuals])))
    return Storyboard(topic=us.title, title=us.title, theme="whiteboard" if wb else "lively", format=us.format,
                      orientation="vertical" if profile.is_vertical else "horizontal", width=profile.width,
                      height=profile.height, fps=profile.fps, music_mood=us.music or "curious", character=host_char,
                      scenes=scenes, generator="script_mode", style="lively", loop_to_start=us.loop_to_start,
                      notes=[f"script mode, {n} scenes"])


def to_script(us: UserScript) -> Script:
    """The user script as a classic Script (for the old look / comparison renders)."""
    beats = []
    for i, sc in enumerate(us.scenes):
        assets = ([asset_id(sc.visual)] if sc.visual else []) + [asset_id(v) for v in sc.visuals]
        beats.append(ScriptBeat(id=f"b{i + 1}", role="hook" if i == 0 else ("ending" if i == len(us.scenes) - 1
                                                                            else None),
                                narration=sc.spoken, visual=VisualHint(assets=assets)))
    return Script(topic=us.title, niche=us.niche, format=us.format, title=us.title, hook=us.scenes[0].spoken,
                  sections=[ScriptSection(title="Main", beats=beats)], source="curated",
                  notes=["user script (script mode)"])


def build_classic(us: UserScript, profile: RenderProfile, path: str = "script") -> Storyboard:
    _check_lengths(us, path)
    sb = StoryboardGenerator().build(to_script(us), profile, music_mood=us.music, character=us.character)
    sb.generator = "script_mode_classic"
    return sb


def build_storyboard(us: UserScript, profile: RenderProfile, style: str = "whiteboard",
                     path: str = "script") -> Storyboard:
    if style == "whiteboard":
        return build_lively(us, profile, path, layout="whiteboard")
    if style == "lively":
        return build_lively(us, profile, path)
    return build_classic(us, profile, path)
