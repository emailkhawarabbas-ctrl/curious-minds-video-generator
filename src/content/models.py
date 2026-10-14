"""Pydantic schemas for research packs, scripts and storyboards.

These models are the contract between every stage. LLM output is parsed into them,
curated content packs are validated by them, and the renderer consumes only
validated objects. Validators check vocabulary (layouts, poses, expressions, assets,
transitions, sound effects), text lengths and durations.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.animation import registry as R

Format = Literal["short", "long"]
Orientation = Literal["vertical", "horizontal"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# =========================================================================== research
class Source(Strict):
    id: str
    title: str
    url: str
    publisher: str = ""
    published: Optional[str] = None            # ISO date if the provider reports one
    accessed: str = Field(default_factory=lambda: date.today().isoformat())
    provider: str
    tier: Literal["authoritative", "peer_reviewed", "reference", "general"] = "general"
    snippet: str = ""

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not re.match(r"^https?://", v):
            raise ValueError(f"source url must be http(s): {v!r}")
        return v


class Fact(Strict):
    id: str
    text: str
    source_ids: List[str] = Field(min_length=1)
    status: Literal["established", "hypothesis", "disputed", "uncertain"] = "uncertain"
    numbers: List[str] = Field(default_factory=list)
    note: str = ""


class ResearchPack(Strict):
    topic: str
    niche: str
    created: str = Field(default_factory=_now)
    status: Literal["ok", "partial", "unavailable"]
    providers: Dict[str, str] = Field(default_factory=dict)   # provider -> ok / error message
    queries: List[str] = Field(default_factory=list)
    sources: List[Source] = Field(default_factory=list)
    facts: List[Fact] = Field(default_factory=list)
    uncertain_claims: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _refs(self) -> "ResearchPack":
        ids = {s.id for s in self.sources}
        for f in self.facts:
            missing = [s for s in f.source_ids if s not in ids]
            if missing:
                raise ValueError(f"fact {f.id} cites unknown sources {missing}")
        return self

    def source(self, sid: str) -> Optional[Source]:
        return next((s for s in self.sources if s.id == sid), None)


# =========================================================================== visuals (shared)
class ItemSpec(Strict):
    text: str = Field(max_length=R.MAX_ITEM_CHARS)
    asset: Optional[str] = None
    cue: Optional[str] = None          # word/phrase in the narration that triggers this item


class ChartSpec(Strict):
    kind: Literal["line", "step", "bar"]
    points: List[List[float]] = Field(default_factory=list)   # line/step: [[x,y],...] in 0..1
    values: List[float] = Field(default_factory=list)          # bar
    labels: List[str] = Field(default_factory=list)            # bar labels / y-axis level labels
    x_labels: List[str] = Field(default_factory=list)
    highlight_level: Optional[int] = None
    value_suffix: str = ""

    @model_validator(mode="after")
    def _data(self) -> "ChartSpec":
        if self.kind == "bar" and not self.values:
            raise ValueError("bar chart needs values")
        if self.kind in ("line", "step"):
            if len(self.points) < 2 or any(len(p) != 2 for p in self.points):
                raise ValueError("line/step chart needs >= 2 [x,y] points")
            if any(not (0 <= c <= 1) for p in self.points for c in p):
                raise ValueError("chart points must be normalised to 0..1")
        return self


class NumberSpec(Strict):
    value: float
    prefix: str = ""
    suffix: str = Field("", max_length=16)
    decimals: int = Field(0, ge=0, le=2)
    label: str = Field("", max_length=R.MAX_LABEL_CHARS + 10)


class VisualHint(Strict):
    """Visual direction attached to a script beat (by the writer / LLM / curator)."""
    layout: Optional[str] = None
    assets: List[str] = Field(default_factory=list)
    labels: List[str] = Field(default_factory=list)
    items: List[ItemSpec] = Field(default_factory=list)
    title: Optional[str] = None
    bubble: Optional[str] = None
    number: Optional[NumberSpec] = None
    chart: Optional[ChartSpec] = None
    background: Optional[str] = None
    action: Optional[str] = None
    expression: Optional[str] = None
    sfx: List[str] = Field(default_factory=list)
    camera: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)

    @field_validator("layout")
    @classmethod
    def _layout(cls, v):
        if v is not None and v not in R.LAYOUTS:
            raise ValueError(f"unknown layout {v!r}")
        return v

    @field_validator("background")
    @classmethod
    def _bg(cls, v):
        if v is not None and v not in R.BACKGROUNDS:
            raise ValueError(f"unknown background {v!r}")
        return v


# =========================================================================== script
class ScriptBeat(Strict):
    id: str
    narration: str = Field(min_length=3)
    visual: VisualHint = Field(default_factory=VisualHint)
    fact_ids: List[str] = Field(default_factory=list)


class ScriptSection(Strict):
    title: str = Field(max_length=60)
    beats: List[ScriptBeat] = Field(min_length=1)


class Script(Strict):
    topic: str
    niche: str
    format: Format
    title: str
    hook: str
    sections: List[ScriptSection] = Field(min_length=1)
    cta: str = ""
    source: Literal["llm", "curated", "offline"] = "curated"
    research_fact_ids: List[str] = Field(default_factory=list)
    created: str = Field(default_factory=_now)
    notes: List[str] = Field(default_factory=list)

    @property
    def beats(self) -> List[ScriptBeat]:
        return [b for s in self.sections for b in s.beats]

    @property
    def full_text(self) -> str:
        return " ".join(b.narration for b in self.beats)

    @property
    def word_count(self) -> int:
        return len(re.findall(r"[A-Za-z0-9']+", self.full_text))

    @model_validator(mode="after")
    def _unique(self) -> "Script":
        ids = [b.id for b in self.beats]
        dup = {i for i in ids if ids.count(i) > 1}
        if dup:
            raise ValueError(f"duplicate beat ids {sorted(dup)}")
        if self.format == "short" and len(self.sections) > 4:
            raise ValueError("short scripts should have at most 4 sections")
        if self.format == "long" and len(self.sections) < 3:
            raise ValueError("long scripts need at least 3 sections")
        return self


# =========================================================================== storyboard
class CharacterCueSpec(Strict):
    at: float = Field(ge=0, le=1)          # fraction of the scene
    action: str
    expression: str

    @model_validator(mode="after")
    def _vocab(self) -> "CharacterCueSpec":
        _check_action(self.action)
        _check_expression(self.expression)
        return self


class CharacterDirection(Strict):
    character: str = "milo"
    present: bool = True
    position: Literal["left", "right", "center", "corner_left", "corner_right"] = "left"
    action: str = "talk"
    expression: str = "happy"
    pose: str = "stand"
    entrance: Literal["none", "walk", "run", "pop", "slide"] = "pop"
    cues: List[CharacterCueSpec] = Field(default_factory=list)
    look_at: Optional[Literal["main", "viewer", "up", "down"]] = None

    @model_validator(mode="after")
    def _vocab(self) -> "CharacterDirection":
        _check_action(self.action)
        _check_expression(self.expression)
        _check_pose(self.pose)
        from src.animation.character_rig import available_characters
        if self.character not in available_characters():
            raise ValueError(f"unknown character {self.character!r}")
        return self


class ObjectSpec(Strict):
    asset: str
    role: Literal["main", "secondary", "item", "prop"] = "main"
    label: Optional[str] = Field(None, max_length=R.MAX_LABEL_CHARS)
    highlight: List[str] = Field(default_factory=list)       # part-* group names
    entrance: Literal["pop", "elastic", "bounce", "draw", "fade", "slide_up", "spin", "none"] = "pop"
    idle: Literal["float", "pulse", "wiggle", "spin", "none"] = "float"
    cue: Optional[str] = None

    @field_validator("asset")
    @classmethod
    def _asset(cls, v: str) -> str:
        from src.animation.asset_manager import get_asset_manager
        if not get_asset_manager().exists(v):
            raise ValueError(f"unknown asset {v!r}")
        return v


class TextOverlay(Strict):
    text: str = Field(min_length=1, max_length=R.MAX_BUBBLE_CHARS)
    style: Literal["title", "label", "bubble", "fact", "cta", "note"] = "title"
    cue: Optional[str] = None

    @model_validator(mode="after")
    def _len(self) -> "TextOverlay":
        limit = {"title": R.MAX_TITLE_CHARS, "label": R.MAX_LABEL_CHARS, "cta": R.MAX_TITLE_CHARS}.get(
            self.style, R.MAX_BUBBLE_CHARS)
        if len(self.text) > limit:
            raise ValueError(f"{self.style} overlay too long ({len(self.text)} > {limit}): {self.text!r}")
        return self


class SfxCue(Strict):
    name: str
    at: float = Field(0.0, ge=0, le=1)     # fraction of the scene
    cue: Optional[str] = None              # or: when this word is spoken
    gain_db: float = Field(0.0, ge=-24, le=6)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if v not in R.SFX:
            raise ValueError(f"unknown sound effect {v!r}")
        return v


class CameraSpec(Strict):
    move: Literal["static", "zoom_in", "zoom_out", "pan_left", "pan_right", "drift", "punch_in", "shake"] = "drift"
    intensity: float = Field(0.5, ge=0, le=1)


class Scene(Strict):
    scene_id: str
    section: str = ""
    beat_id: str = ""
    narration: str = Field(min_length=1)
    est_duration: float = Field(gt=0, le=60)
    duration: Optional[float] = Field(None, gt=0, le=90)      # actual, set after TTS
    layout: str
    background: str
    character: CharacterDirection = Field(default_factory=CharacterDirection)
    objects: List[ObjectSpec] = Field(default_factory=list)
    items: List[ItemSpec] = Field(default_factory=list, max_length=5)
    text_overlays: List[TextOverlay] = Field(default_factory=list, max_length=4)
    number: Optional[NumberSpec] = None
    chart: Optional[ChartSpec] = None
    doodles: List[str] = Field(default_factory=list)
    illustration_notes: str = ""
    animation_notes: List[str] = Field(default_factory=list)
    camera: CameraSpec = Field(default_factory=CameraSpec)
    sfx: List[SfxCue] = Field(default_factory=list)
    transition_in: str = "cut"
    transition_out: str = "cut"

    @field_validator("layout")
    @classmethod
    def _layout(cls, v):
        if v not in R.LAYOUTS:
            raise ValueError(f"unknown layout {v!r}")
        return v

    @field_validator("background")
    @classmethod
    def _bg(cls, v):
        if v not in R.BACKGROUNDS:
            raise ValueError(f"unknown background {v!r}")
        return v

    @field_validator("transition_in", "transition_out")
    @classmethod
    def _tr(cls, v):
        if v not in R.TRANSITIONS:
            raise ValueError(f"unknown transition {v!r}")
        return v

    @field_validator("doodles")
    @classmethod
    def _doodles(cls, v):
        bad = [d for d in v if d not in R.DOODLE_KINDS]
        if bad:
            raise ValueError(f"unknown doodle kinds {bad}")
        return v

    @model_validator(mode="after")
    def _layout_requirements(self) -> "Scene":
        mains = [o for o in self.objects if o.role == "main"]
        L = self.layout
        if L in ("character_explains", "object_focus") and not mains:
            raise ValueError(f"layout {L} needs a main object")
        if L == "fact_card" and self.number is None:
            raise ValueError("fact_card needs a number")
        if L == "chart" and self.chart is None:
            raise ValueError("chart layout needs chart data")
        if L in ("list_reveal", "timeline") and len(self.items) < 2:
            raise ValueError(f"{L} needs at least 2 items")
        if L == "diagram_flow" and len(self.objects) < 2:
            raise ValueError("diagram_flow needs at least 2 objects")
        if L == "comparison" and len(self.objects) != 2:
            raise ValueError("comparison needs exactly 2 objects")
        if L == "network" and len(self.objects) < 3:
            raise ValueError("network needs a main object and >= 2 satellites")
        if self.duration is not None and self.duration < 1.0:
            raise ValueError("scene shorter than 1 s")
        return self


class Storyboard(Strict):
    topic: str
    title: str
    format: Format
    orientation: Orientation
    width: int
    height: int
    fps: int = 30
    music_mood: Literal["curious", "dreamy", "upbeat", "calm"] = "curious"
    character: str = "milo"
    scenes: List[Scene] = Field(min_length=1)
    created: str = Field(default_factory=_now)
    generator: str = "rules"
    notes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _checks(self) -> "Storyboard":
        ids = [s.scene_id for s in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate scene ids")
        for a, b in zip(self.scenes, self.scenes[1:]):
            if a.transition_out != b.transition_in:
                raise ValueError(f"transition mismatch between {a.scene_id} ({a.transition_out}) "
                                 f"and {b.scene_id} ({b.transition_in})")
        if self.scenes[0].transition_in != "cut":
            raise ValueError("first scene must start with a cut")
        if (self.orientation == "vertical") != (self.height > self.width):
            raise ValueError("orientation does not match dimensions")
        limit = R.MAX_SCENE_WORDS[self.format]
        for s in self.scenes:
            n = len(re.findall(r"[A-Za-z0-9']+", s.narration))
            if n > limit:
                raise ValueError(f"scene {s.scene_id} narration too long ({n} words > {limit})")
        return self

    @property
    def total_est_duration(self) -> float:
        return sum(s.duration or s.est_duration for s in self.scenes)


# =========================================================================== vocab helpers
def _check_action(a: str) -> None:
    from src.animation.character_engine import ACTIONS
    if a not in ACTIONS:
        raise ValueError(f"unknown character action {a!r}")


def _check_expression(e: str) -> None:
    from src.animation.expression_engine import load_expressions
    if e not in load_expressions():
        raise ValueError(f"unknown expression {e!r}")


def _check_pose(p: str) -> None:
    from src.animation.character_rig import load_pose_library
    if p not in load_pose_library():
        raise ValueError(f"unknown pose {p!r}")
