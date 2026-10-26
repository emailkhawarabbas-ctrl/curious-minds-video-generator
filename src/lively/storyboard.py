"""Switch a classic (topic-mode) storyboard to the lively style."""
from __future__ import annotations

from src.content.models import Storyboard
from src.lively.transitions import lively_kind


def to_lively(sb: Storyboard, loop_to_start: bool = False) -> Storyboard:
    """Quick transitions everywhere; the renderer then composes every scene with the lively look."""
    for sc in sb.scenes:
        sc.transition_in = lively_kind(sc.transition_in)
        sc.transition_out = lively_kind(sc.transition_out)
    if loop_to_start and sb.scenes[-1].transition_out == "cut":
        sb.scenes[-1].transition_out = "zoom_through"
    sb.style = "lively"
    sb.loop_to_start = loop_to_start
    return sb
