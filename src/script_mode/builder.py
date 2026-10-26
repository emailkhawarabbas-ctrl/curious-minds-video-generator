"""Turn a user script into a storyboard: the lively look (default) or the classic look.

Fields a scene leaves out get defaults that keep consecutive scenes different:
  visual     best tag match for the scene text in the asset library (never the previous scene's)
  animation  pop_in for the hook, then draw_on / pop_in / slide_in / bounce in turn
  camera     zoom_in, pan_right, zoom_out, pan_left, drift, pan_up in turn
  host       left, right, center (waist-up close-up), corner_right, corner_left in turn
  pose       think for questions, excited for exclamations, explain / point / present otherwise
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


def build_lively(us: UserScript, profile: RenderProfile, path: str = "script") -> Storyboard:
    _check_lengths(us, path)
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
        prev_host = position
        action, expression = host_pose(sc, i)
        cues = []
        if sc.emphasis and action not in ("excited", "surprised"):
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
        scenes.append(Scene(
            scene_id=f"s{i + 1:02d}", section="main", beat_id=f"b{i + 1}", narration=sc.spoken,
            est_duration=max(1.6, _words(sc.spoken) / WORDS_PER_SECOND + 0.75), layout="spotlight",
            background="doodle_paper", purpose="hook" if i == 0 else "explain",
            role="hook" if i == 0 else ("ending" if last else "explanation"),
            character=CharacterDirection(character=host_char, present=position != "none",
                                         position=position if position != "none" else "left", action=action,
                                         expression=expression, entrance="pop", cues=cues),
            objects=[ObjectSpec(asset=visual, role="main")],
            sfx=[SfxCue(name=x, at=0.0) for x in sc.sfx_list],
            camera={"move": "drift", "intensity": 1.0},
            transition_in=t_in, transition_out=t_out,
            lively=LivelyDirection(animation=sc.animation or ("pop_in" if i == 0 else ANIMATIONS[i % len(ANIMATIONS)]),
                                   camera=sc.camera or CAMERAS[i % len(CAMERAS)], emphasis=sc.emphasis,
                                   shake=sc.shake, headline=headline,
                                   visuals=[asset_id(v) for v in sc.visuals])))
    return Storyboard(topic=us.title, title=us.title, theme="lively", format=us.format,
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


def build_storyboard(us: UserScript, profile: RenderProfile, style: str = "lively", path: str = "script") -> Storyboard:
    if style == "lively":
        return build_lively(us, profile, path)
    return build_classic(us, profile, path)
