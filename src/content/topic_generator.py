"""Topic ideas balanced across the three content pillars, optionally steered by analytics.

Pillar mix (locked by the business plan): Science & Human Body 40 %, Psychology & Human
Behaviour 35 %, Amazing Science & Everyday Mysteries 25 %. Analytics (real imported
CSV data only) can boost pillars that perform better; without analytics the base mix
is used. Topics already produced (``generated/*``) are skipped.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from src.utils.text import slugify

PILLARS: Dict[str, float] = {"human_body": 0.40, "psychology": 0.35, "science": 0.25}

TOPIC_BANK: Dict[str, List[str]] = {
    "human_body": [
        "Why Do We Get Goosebumps?", "How Does Your Heart Never Get Tired?", "Why Do We Have Fingerprints?",
        "What Happens When You Crack Your Knuckles?", "Why Do We Hiccup?", "How Do Your Lungs Breathe?",
        "What Does Your Stomach Do All Day?", "Why Do Our Eyes Blink?", "How Do Muscles Get Stronger?",
        "What Is DNA, Really?", "Why Do We Sneeze?", "How Does Your Blood Travel?",
    ],
    "psychology": [
        "Why Do We Dream?", "How Does Your Brain Create Memories?", "Why Are Habits So Hard to Break?",
        "Why Do We Procrastinate?", "Why Do Songs Get Stuck in Your Head?", "Why Do We Feel Deja Vu?",
        "How Does Attention Work?", "Why Do We Get Nervous?", "Why Is Yawning Contagious?",
        "How Do Emotions Work?", "Why Do We Forget Things?", "What Makes Us Laugh?",
    ],
    "science": [
        "Why Is the Sky Blue?", "How Does Lightning Happen?", "Why Do Stars Twinkle?",
        "How Do Magnets Work?", "Why Does the Moon Change Shape?", "How Do Rainbows Form?",
        "What Is an Atom Made Of?", "Why Is Ice Slippery?", "How Do Rockets Fly in Space?",
        "Why Do Planets Have Rings?",
    ],
}


def produced_topics(generated_dir: Path) -> set:
    if not generated_dir.exists():
        return set()
    return {p.name for p in generated_dir.iterdir() if p.is_dir() and not p.name.startswith(".")}


def pillar_weights(performance: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Blend the locked mix with measured relative performance (e.g. avg completion rate)."""
    if not performance:
        return dict(PILLARS)
    mean = sum(performance.values()) / len(performance) or 1
    w = {p: base * (0.75 + 0.25 * (performance.get(p, mean) / mean)) for p, base in PILLARS.items()}
    s = sum(w.values())
    return {p: v / s for p, v in w.items()}


def suggest_topics(n: int, generated_dir: Path, performance: Optional[Dict[str, float]] = None) -> List[Dict]:
    done = produced_topics(generated_dir)
    weights = pillar_weights(performance)
    quota = {p: max(1, round(n * w)) for p, w in weights.items()}
    out: List[Dict] = []
    for p, k in sorted(quota.items(), key=lambda kv: -weights[kv[0]]):
        fresh = [t for t in TOPIC_BANK[p] if slugify(t) not in done]
        for t in fresh[:k]:
            out.append({"topic": t, "niche": p, "pillar_weight": round(weights[p], 3),
                        "reason": "pillar quota" + (" adjusted by analytics" if performance else " (base mix)")})
    return out[:n]
