"""Niche visual identities: Human Body, Science, Psychology.

Each niche has its own host character (``mascot``: ``human_body`` / ``science`` / ``psychology``,
designed from the art in ``characters/``) plus its own world: environments chosen per scene
*purpose*, accent palettes for labels and diagrams, particle / doodle vocabulary,
transition families, camera temperament, music mood, foreground depth props and the
asset categories the visual selector prefers.

A theme is chosen from the requested niche; ``mixed`` resolves to the niche whose concept
vocabulary best matches the topic (see :func:`resolve_theme`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

DEFAULT_MASCOT = "milo"                       # base rig; each niche theme sets its own host

# Scene purposes the storyboard assigns (see src/content/story_engine.py)
PURPOSES = ("hook", "question", "relatable", "explain", "process", "comparison", "discovery", "surprise",
            "environment", "ending")


@dataclass(frozen=True)
class NicheTheme:
    name: str
    label: str
    # environments per scene purpose (rotated within a purpose to avoid repeats)
    backgrounds: Dict[str, Tuple[str, ...]]
    accents: Tuple[str, ...]                  # palette names for labels / cards / pathways, in order
    label_color: str
    particles: Tuple[str, ...]                # ambient Particles kinds used for atmosphere
    doodles: Tuple[str, ...]                  # doodle kinds that suit the niche
    transitions: Tuple[str, ...]              # section transitions, in rotation
    soft_transition: str                      # within-section background change
    camera: Dict[str, str]                    # purpose -> camera move
    music_mood: str
    asset_categories: Tuple[str, ...]         # preferred asset folders, best first
    foreground: str                           # foreground depth-prop set (drawn by scene_engine)
    title_colors: Tuple[str, ...] = ("yellow", "white", "white", "teal_light")
    mascot: str = DEFAULT_MASCOT              # character id under assets/characters/
    keywords: Tuple[str, ...] = field(default_factory=tuple)

    def background_for(self, purpose: str, k: int = 0) -> str:
        opts = self.backgrounds.get(purpose) or self.backgrounds["explain"]
        return opts[k % len(opts)]


HUMAN_BODY = NicheTheme(
    name="human_body", label="Human Body — medical cartoon",
    backgrounds={
        "hook": ("bloodstream", "body_lab"), "question": ("anatomy_blueprint", "body_lab"),
        "relatable": ("body_lab", "sunny_outdoors"), "explain": ("body_lab", "anatomy_blueprint", "cell_world"),
        "process": ("bloodstream", "anatomy_blueprint", "cell_world"), "comparison": ("anatomy_blueprint", "body_lab"),
        "discovery": ("cell_world", "bloodstream"), "surprise": ("bloodstream", "cell_world"),
        "environment": ("body_lab", "cell_world"), "ending": ("body_lab",)},
    accents=("coral", "teal", "blue", "pink", "orange"), label_color="coral",
    particles=("bubbles", "float_up"), doodles=("circle_main", "arrow_to_main", "sparkles"),
    transitions=("circle_wipe", "blinds", "slide", "dots"), soft_transition="dip_cream",
    camera={"hook": "punch_in", "process": "focus", "explain": "focus", "comparison": "static",
            "discovery": "zoom_in", "surprise": "punch_in", "environment": "pan_right", "ending": "zoom_out"},
    music_mood="curious", asset_categories=("human_body", "objects", "science"), foreground="medical", mascot="human_body",
    title_colors=("white", "yellow", "white", "pink_light"),
    keywords=("heart", "blood", "body", "lung", "breath", "cell", "organ", "muscle", "bone", "brain", "nerve",
              "stomach", "digest", "immune", "germ", "skin", "eye", "ear", "dna", "gene", "pulse", "vein",
              "artery", "oxygen", "hormone", "sleep", "goosebump", "hiccup", "sneeze", "yawn"))

SCIENCE = NicheTheme(
    name="science", label="Science — exploration & discovery",
    backgrounds={
        "hook": ("sky_day", "space"), "question": ("sky_day", "night_sky"), "relatable": ("sunny_outdoors", "sky_day"),
        "explain": ("science_grid", "lab", "sky_day"), "process": ("atmosphere_view", "science_grid", "space"),
        "comparison": ("science_grid", "lab"), "discovery": ("lab", "space"), "surprise": ("sunset_sky", "space"),
        "environment": ("sky_day", "sunset_sky", "night_sky", "underwater"), "ending": ("sunset_sky", "sky_day")},
    accents=("blue", "orange", "teal", "purple", "yellow"), label_color="blue",
    particles=("twinkle", "float_up"), doodles=("sparkles", "circle_main", "arrow_to_main"),
    transitions=("star_zoom", "slide", "circle_wipe", "doodle_swipe"), soft_transition="slide",
    camera={"hook": "punch_in", "process": "follow", "explain": "focus", "comparison": "static",
            "discovery": "zoom_in", "surprise": "shake", "environment": "pan_left", "ending": "zoom_out"},
    music_mood="upbeat", asset_categories=("science", "objects", "human_body"), foreground="science", mascot="science",
    title_colors=("yellow", "white", "sky_light", "white"),
    keywords=("sky", "light", "sun", "star", "planet", "space", "moon", "earth", "atom", "molecule", "energy",
              "electric", "magnet", "gravity", "black hole", "galaxy", "wave", "sound", "color", "rainbow",
              "weather", "rain", "cloud", "volcano", "ocean", "plant", "chemical", "physics", "universe", "water", "ice",
              "freez", "liquid", "lake"))

PSYCHOLOGY = NicheTheme(
    name="psychology", label="Psychology — mind & behaviour storytelling",
    backgrounds={
        "hook": ("mind_maze", "thought_room"), "question": ("thought_room", "mind_maze"),
        "relatable": ("thought_room", "city"), "explain": ("brain_space", "emotion_waves", "mind_maze"),
        "process": ("brain_space", "mind_maze"), "comparison": ("emotion_waves", "paper"),
        "discovery": ("emotion_waves", "brain_space"), "surprise": ("mind_maze", "dreamscape"),
        "environment": ("thought_room", "city", "bedroom_night"), "ending": ("emotion_waves",)},
    accents=("purple", "pink", "teal", "orange", "yellow"), label_color="purple",
    particles=("bubbles", "twinkle"), doodles=("sparkles", "circle_main", "morph"),
    transitions=("doodle_swipe", "dots", "circle_wipe", "blinds"), soft_transition="dip_cream",
    camera={"hook": "punch_in", "process": "focus", "explain": "drift", "comparison": "static",
            "discovery": "zoom_in", "surprise": "punch_in", "environment": "pan_right", "ending": "zoom_out"},
    music_mood="calm", asset_categories=("psychology", "objects", "human_body"), foreground="mind", mascot="psychology",
    title_colors=("white", "pink_light", "yellow", "white"),
    keywords=("think", "thought", "mind", "emotion", "feel", "fear", "anxiety", "worry", "memory", "remember",
              "dream", "habit", "decision", "choice", "attention", "focus", "motivation", "happy", "sad",
              "stress", "social", "friend", "behavior", "behaviour", "overthink", "procrastinat", "brain",
              "personality", "learn", "bias"))

THEMES: Dict[str, NicheTheme] = {t.name: t for t in (HUMAN_BODY, SCIENCE, PSYCHOLOGY)}


def theme_scores(text: str) -> Dict[str, int]:
    t = text.lower()
    return {name: sum(1 for k in th.keywords if re.search(rf"\b{re.escape(k)}", t)) for name, th in THEMES.items()}


def resolve_theme(niche: str, topic: str = "", extra_text: str = "") -> NicheTheme:
    """The niche's theme; for ``mixed`` the theme whose vocabulary best matches the topic."""
    if niche in THEMES:
        return THEMES[niche]
    scores = theme_scores(f"{topic} {topic} {extra_text}")
    best = max(scores.items(), key=lambda kv: (kv[1], kv[0] == "science"))
    return THEMES[best[0]] if best[1] > 0 else SCIENCE


def resolve_mascot(niche: str, topic: str = "", extra_text: str = "") -> str:
    """The host character for a video: the mascot of the video's theme.

    ``mixed`` uses the mascot of the best-matching theme; a topic that matches no niche
    vocabulary (and any unknown niche) gets the science host, like its theme.
    """
    return resolve_theme(niche, topic, extra_text).mascot


def all_theme_backgrounds() -> List[str]:
    return sorted({b for th in THEMES.values() for opts in th.backgrounds.values() for b in opts})
