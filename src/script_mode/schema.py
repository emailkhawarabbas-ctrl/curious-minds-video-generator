"""The script file you write yourself (scripts/*.yaml or *.json), with clear error messages.

    title: "What Happens If You Don't Sleep for 24 Hours"
    format: short              # short = 1080x1920, long = 1920x1080
    loop_to_start: true
    scenes:
      - text: "Skip *one* night of sleep and your brain acts drunk."
        visual: brain.svg
        animation: draw_on
        camera: zoom_in
        sfx: whoosh

Every scene field except ``text`` is optional; missing ones get sensible defaults
(see builder.py). Words wrapped in *asterisks* get a camera punch-in.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.animation import registry as R

HOST_POSITIONS = ("left", "right", "center", "corner_left", "corner_right", "none")
HOST_POSES = ("talk", "explain", "point", "think", "wave", "surprised", "excited", "happy", "sad", "shrug",
              "present", "thumbs_up", "celebrate", "yawn", "sleep", "draw", "count", "hold_up")
HOST_ENTERS = ("walk", "pop", "none")
HOST_EXITS = ("walk", "none")


class ScriptFileError(ValueError):
    """Raised with a list of human-readable problems in a script file."""

    def __init__(self, path: Union[str, Path], problems: List[str]):
        self.path, self.problems = str(path), problems
        super().__init__(f"{path}: {len(problems)} problem(s)\n" + "\n".join(f"  - {p}" for p in problems))


def asset_id(name: str) -> str:
    """'brain.svg' / 'assets/objects/brain.svg' / 'brain' -> 'brain'."""
    return Path(str(name).strip()).name.rsplit(".svg", 1)[0].strip()


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserScene(_S):
    text: str = Field(min_length=2, max_length=400)
    visual: Optional[str] = None                  # main SVG (asset id or file name); auto-picked if missing
    visuals: List[str] = Field(default_factory=list, max_length=3)   # extra SVGs revealed during the scene
    animation: Optional[str] = None               # draw_on | pop_in | bounce | slide_in | spin_in | fade_in
    camera: Optional[str] = None                  # zoom_in | zoom_out | pan_left | pan_right | pan_up | pan_down | drift | static
    sfx: Union[str, List[str], None] = None       # one or more sound effects, played as the scene starts
    headline: Optional[str] = Field(None, max_length=R.MAX_TITLE_CHARS)   # big text sticker
    shake: bool = False                           # small camera shake for a dramatic line
    host: Optional[str] = None                    # host position: left | right | center | corner_left | corner_right | none
    pose: Optional[str] = None                    # host action: draw | count | hold_up | think | surprised | shrug | ...
    expression: Optional[str] = None              # host face: happy | excited | surprised | worried | sleepy | ...
    transition: Optional[str] = None              # transition into the next scene
    host_enter: Optional[str] = None              # walk (walks in) | pop | none
    host_exit: Optional[str] = None               # walk (walks out at the end) | none

    @field_validator("host_enter")
    @classmethod
    def _enter(cls, v):
        if v is not None and v not in HOST_ENTERS:
            raise ValueError(_choice("host_enter", v, HOST_ENTERS))
        return v

    @field_validator("host_exit")
    @classmethod
    def _exit(cls, v):
        if v is not None and v not in HOST_EXITS:
            raise ValueError(_choice("host_exit", v, HOST_EXITS))
        return v

    @field_validator("visual")
    @classmethod
    def _visual(cls, v):
        if v is not None:
            _check_asset(v)
        return v

    @field_validator("visuals")
    @classmethod
    def _visuals(cls, v):
        for n in v:
            _check_asset(n)
        return v

    @field_validator("animation")
    @classmethod
    def _anim(cls, v):
        if v is not None and v not in R.LIVELY_ANIMATIONS:
            raise ValueError(_choice("animation", v, R.LIVELY_ANIMATIONS))
        return v

    @field_validator("camera")
    @classmethod
    def _cam(cls, v):
        if v is not None and v not in R.LIVELY_CAMERAS:
            raise ValueError(_choice("camera", v, R.LIVELY_CAMERAS))
        return v

    @field_validator("sfx")
    @classmethod
    def _sfx(cls, v):
        names = [v] if isinstance(v, str) else (v or [])
        for n in names:
            if n not in R.SFX:
                raise ValueError(_choice("sfx", n, R.SFX))
        return v

    @field_validator("host")
    @classmethod
    def _host(cls, v):
        if v is not None and v not in HOST_POSITIONS:
            raise ValueError(_choice("host", v, HOST_POSITIONS))
        return v

    @field_validator("pose")
    @classmethod
    def _pose(cls, v):
        if v is not None and v not in HOST_POSES:
            raise ValueError(_choice("pose", v, HOST_POSES))
        return v

    @field_validator("expression")
    @classmethod
    def _expr(cls, v):
        from src.animation.expression_engine import load_expressions
        names = [k for k in load_expressions() if not k.startswith("_")]
        if v is not None and v not in names:
            raise ValueError(_choice("expression", v, names))
        return v

    @field_validator("transition")
    @classmethod
    def _tr(cls, v):
        if v is not None and v not in R.LIVELY_TRANSITIONS + ("cut",):
            raise ValueError(_choice("transition", v, R.LIVELY_TRANSITIONS + ("cut",)))
        return v

    @property
    def sfx_list(self) -> List[str]:
        return [self.sfx] if isinstance(self.sfx, str) else list(self.sfx or [])

    @property
    def spoken(self) -> str:
        """Narration without the *emphasis* markers."""
        return re.sub(r"\*([^*]+)\*", r"\1", self.text).strip()

    @property
    def emphasis(self) -> List[str]:
        return [m.strip() for m in re.findall(r"\*([^*]+)\*", self.text) if m.strip()]


class UserScript(_S):
    title: str = Field(min_length=3, max_length=100)
    format: Literal["short", "long"] = "short"
    voice_language: Literal["en"] = "en"
    voice: Optional[str] = None                   # voice profile (friendly / energetic / documentary) or Kokoro voice
    niche: Literal["science", "psychology", "human_body", "mixed"] = "mixed"   # picks the host character
    character: Optional[str] = None               # force a host character id (e.g. milo, science)
    music: Optional[Literal["curious", "dreamy", "upbeat", "calm"]] = None
    subtitles: bool = True
    loop_to_start: bool = False
    scenes: List[UserScene] = Field(min_length=1, max_length=40)

    @field_validator("voice_language", mode="before")
    @classmethod
    def _lang(cls, v):
        if v is not None and str(v).lower() != "en":
            raise ValueError("only English narration is supported (voice_language: en)")
        return "en"

    @field_validator("character")
    @classmethod
    def _character(cls, v):
        from src.animation.character_rig import available_characters
        if v is not None and v not in available_characters():
            raise ValueError(_choice("character", v, sorted(available_characters())))
        return v


def _check_asset(name: str) -> None:
    from src.animation.asset_manager import get_asset_manager
    am = get_asset_manager()
    a = asset_id(name)
    if not am.exists(a):
        close = difflib.get_close_matches(a, am.ids(), n=3, cutoff=0.6)
        hint = f" Did you mean {', '.join(c + '.svg' for c in close)}?" if close else ""
        raise ValueError(f"'{name}' not found in assets/.{hint} (new SVGs go in assets/<category>/, then run "
                         f"'python -m src.main assets index')")


def _choice(field: str, value: Any, allowed) -> str:
    names = list(allowed)
    close = difflib.get_close_matches(str(value), names, n=1, cutoff=0.5)
    hint = f" Did you mean '{close[0]}'?" if close else ""
    return f"unknown {field} '{value}'.{hint} Use one of: {', '.join(names)}"


def _friendly(err: ValidationError) -> List[str]:
    out = []
    fields = {"scene": list(UserScene.model_fields), "script": list(UserScript.model_fields)}
    for e in err.errors():
        loc = list(e.get("loc", ()))
        where = "script"
        if len(loc) >= 2 and loc[0] == "scenes" and isinstance(loc[1], int):
            where = f"scene {loc[1] + 1}"
            loc = loc[2:]
        name = str(loc[-1]) if loc else ""
        msg = e.get("msg", "").removeprefix("Value error, ")
        if e.get("type") == "extra_forbidden":
            pool = fields["scene" if where.startswith("scene") else "script"]
            close = difflib.get_close_matches(name, pool, n=1, cutoff=0.5)
            hint = f" Did you mean '{close[0]}'?" if close else ""
            out.append(f"{where}: unknown field '{name}'.{hint}")
        elif e.get("type") == "missing":
            out.append(f"{where}: required field '{name}' is missing")
        else:
            out.append(f"{where}: {name + ': ' if name else ''}{msg}")
    return out


def load_user_script(path: Union[str, Path]) -> UserScript:
    p = Path(path)
    if not p.exists():
        raise ScriptFileError(p, [f"script file not found: {p}"])
    text = p.read_text(encoding="utf-8")
    try:
        data = json.loads(text) if p.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ScriptFileError(p, [f"could not parse the file: {exc}"]) from exc
    if not isinstance(data, dict):
        raise ScriptFileError(p, ["the file must contain a mapping with 'title' and 'scenes'"])
    try:
        return UserScript.model_validate(data)
    except ValidationError as exc:
        raise ScriptFileError(p, _friendly(exc)) from exc
