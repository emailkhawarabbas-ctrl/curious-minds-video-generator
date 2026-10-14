"""Add / refresh asset metadata on SVG roots: data-subcategory, data-style, data-animations.

Every library SVG must describe itself (name, category = folder, subcategory, keywords,
visual style, licence, supported animation types) so the niche-aware visual selector can
reason about it. Run after adding SVGs, then `python -m src.main assets index`:

    python scripts/annotate_assets.py            # fill missing fields only
    python scripts/annotate_assets.py --force    # overwrite with the table below
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "assets"

STYLE = {"human_body": "medical_cartoon", "science": "science_explorer", "psychology": "mind_storybook",
         "objects": "everyday_doodle"}

SUBCATEGORY = {
    # human body
    "blood_cells": "blood", "red_blood_cell": "blood", "white_blood_cell": "immune", "blood_vessel": "circulation",
    "heart": "cardiovascular", "heart_cutaway": "cardiovascular", "body_circulation": "circulation",
    "oxygen_o2": "respiration", "lungs": "respiration", "stethoscope": "medical_tools", "pulse_monitor": "medical_tools",
    "bone": "skeletal", "muscle": "muscular", "brain": "nervous", "neuron": "nervous", "nervous_system": "nervous",
    "eye": "senses", "ear": "senses", "stomach": "digestive", "cell": "cellular", "dna": "cellular",
    # science
    "atom": "physics", "magnet": "physics", "lightning": "energy", "wave_sound": "waves", "light_wave": "waves",
    "prism": "light", "sun": "space", "moon": "space", "earth": "space", "planet_saturn": "space", "star": "space",
    "rocket": "space", "telescope": "instruments", "microscope": "instruments", "flask": "chemistry",
    "molecule": "chemistry", "nitrogen_n2": "chemistry", "flower": "nature", "tree": "nature",
    "weather_cloud_rain": "weather", "thermometer": "weather", "black_hole": "space", "galaxy": "space",
    "atmosphere_layers": "atmosphere", "observer_kid": "observation", "sunset_scene": "atmosphere",
    # psychology
    "alarm_clock": "sleep", "dream_cloud": "dreams", "moon_sleepy": "sleep", "nightmare_monster": "dreams",
    "sheep": "sleep", "sleeping_person": "sleep", "zzz": "sleep", "eeg_wave": "brain_activity",
    "brain_activity": "brain_activity", "attention_target": "attention", "habit_loop": "habits",
    "lightbulb": "insight", "memory_photos": "memory", "puzzle_piece": "problem_solving",
    "question_mark": "curiosity", "thought_cloud": "thoughts", "emotion_angry": "emotions",
    "emotion_happy": "emotions", "emotion_sad": "emotions", "emotion_scared": "emotions",
    "emotion_surprised": "emotions", "overthinking_head": "thoughts", "thought_spiral": "thoughts",
    "decision_signpost": "decisions", "person_thinking": "behavior", "worried_face": "emotions",
    "chat_bubbles": "social", "balance_scale": "decisions", "calm_breath": "wellbeing", "amygdala_alarm": "brain_activity",
    # objects
    "backpack": "school", "book": "school", "books_stack": "school", "building": "places", "house": "places",
    "bus": "transport", "car": "transport", "calendar": "time", "clock": "time", "chart_bars": "data",
    "chart_line": "data", "coffee_cup": "food", "computer": "technology", "phone": "technology",
    "gift_box": "rewards", "trophy": "rewards", "magnifying_glass": "exploration", "map": "exploration",
    "bed": "home", "pillow": "home",
}

ANIMATIONS = {
    "cardiovascular": "draw,pop,beat,pulse,highlight", "circulation": "draw,flow,pulse",
    "blood": "pop,float,flow", "immune": "pop,float,wiggle", "respiration": "draw,breathe,pulse,highlight",
    "nervous": "draw,pulse,signal,highlight", "brain_activity": "pop,pulse,signal", "space": "pop,float,spin,orbit",
    "light": "draw,shine,pop", "waves": "draw,flow", "atmosphere": "draw,fade,pan", "emotions": "pop,wiggle,bounce",
    "thoughts": "pop,float,spin", "decisions": "pop,wiggle,draw", "sleep": "pop,float,wiggle",
    "dreams": "pop,float", "medical_tools": "pop,draw,pulse",
}
DEFAULT_ANIM = "pop,float,draw"


def annotate(path: Path, force: bool) -> bool:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"<svg\b[^>]*>", text, re.S)
    if not m:
        return False
    tag = m.group(0)
    cat, aid = path.parent.name, path.stem
    sub = SUBCATEGORY.get(aid, "general")
    want = {"data-subcategory": sub, "data-style": STYLE.get(cat, "everyday_doodle"),
            "data-animations": ANIMATIONS.get(sub, DEFAULT_ANIM)}
    new = tag
    for k, v in want.items():
        if re.search(rf'\s{k}="[^"]*"', new):
            if force:
                new = re.sub(rf'\s{k}="[^"]*"', f' {k}="{v}"', new)
        else:
            new = new[:-1].rstrip() + f' {k}="{v}">'
    if new != tag:
        path.write_text(text.replace(tag, new, 1), encoding="utf-8")
        return True
    return False


def main(argv=None) -> int:
    force = "--force" in (argv or sys.argv[1:])
    n = 0
    for cat in STYLE:
        for f in sorted((ROOT / cat).glob("*.svg")):
            n += annotate(f, force)
    print(f"annotated {n} SVG files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
