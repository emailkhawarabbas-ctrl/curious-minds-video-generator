import math

import cairo
import numpy as np
import pytest

from src.animation.character_engine import ACTIONS, CharacterAnimator, CharacterCue
from src.animation.character_rig import (Placement, available_characters, compute_skeleton, draw_character,
                                         load_character, make_pose, pose_names, solve_two_bone_ik)
from src.animation.expression_engine import blink_amount, expression_names, expression_state

REQUIRED_POSES = {"stand", "point_forward", "think", "explain", "surprised", "sad", "excited", "hold", "wave"}
REQUIRED_EXPRESSIONS = {"happy", "sad", "surprised", "excited", "thinking", "curious", "neutral"}
REQUIRED_ACTIONS = {"idle", "walk", "run", "talk", "point", "think", "explain", "surprised", "happy", "sad",
                    "excited", "hold", "look_at", "interact"}


def test_libraries_complete():
    assert REQUIRED_POSES <= set(pose_names())
    assert REQUIRED_EXPRESSIONS <= set(expression_names())
    assert REQUIRED_ACTIONS <= set(ACTIONS)
    assert {"milo", "zoe"} <= set(available_characters())


def test_proportions_locked():
    """Character consistency: proportions come from the locked spec, identical for every pose."""
    st = load_character("milo")
    assert st.rig["upper_arm"] == 92 and st.rig["thigh"] == 92
    assert st.height_units == pytest.approx(722)
    for name in pose_names():
        sk = compute_skeleton(st, make_pose(name))
        for side in ("l", "r"):
            if "ik_" + side in make_pose(name):
                continue
            upper = math.dist(sk.shoulders[side], sk.elbows[side])
            fore = math.dist(sk.elbows[side], sk.wrists[side])
            assert upper == pytest.approx(92, abs=1e-6) and fore == pytest.approx(86, abs=1e-6)


def test_ik_reaches_target():
    up, rel = solve_two_bone_ik((0, 0), (100, 50), 92, 86)
    ex = 92 * math.sin(math.radians(up)), 92 * math.cos(math.radians(up))
    a2 = up + rel
    wx, wy = ex[0] + 86 * math.sin(math.radians(a2)), ex[1] + 86 * math.cos(math.radians(a2))
    assert (wx, wy) == pytest.approx((100, 50), abs=0.5)


def test_supporting_character_recoloured_not_reshaped():
    milo, zoe = load_character("milo"), load_character("zoe")
    assert milo.rig == zoe.rig
    assert milo.colors["sleeve"] != zoe.colors["sleeve"]
    assert zoe.backpack is None


def test_draw_all_poses_and_expressions_non_empty():
    st = load_character("milo")
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 260)
    ctx = cairo.Context(surf)
    for p in pose_names():
        for e in ("happy", "surprised", "sad"):
            ctx.set_operator(cairo.OPERATOR_CLEAR)
            ctx.paint()
            ctx.set_operator(cairo.OPERATOR_OVER)
            draw_character(ctx, st, make_pose(p), expression_state(e), Placement(100, 250, 230))
            surf.flush()
            alpha = np.frombuffer(surf.get_data(), np.uint8)[3::4]
            assert (alpha > 0).mean() > 0.08, (p, e)


def test_blinking_is_periodic_and_brief():
    vals = [blink_amount(i / 30, seed=1) for i in range(30 * 20)]
    closed = sum(v > 0.5 for v in vals)
    assert 5 <= closed <= 60


def test_animator_moves_over_time():
    an = CharacterAnimator(Placement(100, 250, 230), [CharacterCue("walk", "happy", 0, 2, walk_to=(300, 250)),
                                                      CharacterCue("talk", "happy", 2)],
                           envelope=[0.5] * 120, entrance="none")
    p0 = an.state_at(0.0, 4)[2].x
    p1 = an.state_at(1.9, 4)[2].x
    assert p1 > p0 + 100
    _, face, _, _ = an.state_at(3.0, 4)
    assert face.mouth_open == pytest.approx(0.5)


def test_unknown_action_rejected():
    with pytest.raises(ValueError):
        CharacterCue("moonwalk", "happy")
