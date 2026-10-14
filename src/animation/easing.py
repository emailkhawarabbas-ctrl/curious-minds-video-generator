"""Easing curves and timing helpers (all functions map [0,1] -> ~[0,1])."""
from __future__ import annotations

import math
from typing import Callable, Dict

Ease = Callable[[float], float]


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def progress(t: float, start: float, duration: float) -> float:
    """Normalised progress of an animation that starts at `start` and lasts `duration`."""
    if duration <= 0:
        return 1.0 if t >= start else 0.0
    return clamp((t - start) / duration)


def linear(x: float) -> float:
    return clamp(x)


def ease_in_quad(x: float) -> float:
    x = clamp(x)
    return x * x


def ease_out_quad(x: float) -> float:
    x = clamp(x)
    return 1 - (1 - x) * (1 - x)


def ease_in_out_quad(x: float) -> float:
    x = clamp(x)
    return 2 * x * x if x < 0.5 else 1 - (-2 * x + 2) ** 2 / 2


def ease_out_cubic(x: float) -> float:
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_cubic(x: float) -> float:
    x = clamp(x)
    return x ** 3


def ease_in_out_cubic(x: float) -> float:
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_in_out_sine(x: float) -> float:
    x = clamp(x)
    return -(math.cos(math.pi * x) - 1) / 2


def ease_out_back(x: float, s: float = 1.70158) -> float:
    x = clamp(x)
    c3 = s + 1
    return 1 + c3 * (x - 1) ** 3 + s * (x - 1) ** 2


def ease_in_back(x: float, s: float = 1.70158) -> float:
    x = clamp(x)
    return (s + 1) * x ** 3 - s * x ** 2


def ease_out_elastic(x: float) -> float:
    x = clamp(x)
    if x in (0.0, 1.0):
        return x
    c4 = (2 * math.pi) / 3
    return 2 ** (-10 * x) * math.sin((x * 10 - 0.75) * c4) + 1


def ease_out_bounce(x: float) -> float:
    x = clamp(x)
    n1, d1 = 7.5625, 2.75
    if x < 1 / d1:
        return n1 * x * x
    if x < 2 / d1:
        x -= 1.5 / d1
        return n1 * x * x + 0.75
    if x < 2.5 / d1:
        x -= 2.25 / d1
        return n1 * x * x + 0.9375
    x -= 2.625 / d1
    return n1 * x * x + 0.984375


EASINGS: Dict[str, Ease] = {
    "linear": linear,
    "in_quad": ease_in_quad,
    "out_quad": ease_out_quad,
    "in_out_quad": ease_in_out_quad,
    "in_cubic": ease_in_cubic,
    "out_cubic": ease_out_cubic,
    "in_out_cubic": ease_in_out_cubic,
    "in_out_sine": ease_in_out_sine,
    "out_back": ease_out_back,
    "in_back": ease_in_back,
    "out_elastic": ease_out_elastic,
    "out_bounce": ease_out_bounce,
}


def get_ease(name: str) -> Ease:
    try:
        return EASINGS[name]
    except KeyError as exc:
        raise KeyError(f"unknown easing {name!r}; valid: {sorted(EASINGS)}") from exc


def pulse(t: float, period: float, phase: float = 0.0) -> float:
    """Smooth 0..1..0 oscillation."""
    return 0.5 - 0.5 * math.cos(2 * math.pi * (t / period + phase))


def wobble(t: float, seed: float, amount: float = 1.0, speed: float = 1.0) -> float:
    """Deterministic organic jitter (sum of incommensurate sines) in [-amount, amount]."""
    v = (math.sin(t * 2.1 * speed + seed * 1.7) * 0.5 + math.sin(t * 3.7 * speed + seed * 4.1) * 0.3
         + math.sin(t * 6.3 * speed + seed * 2.3) * 0.2)
    return v * amount
