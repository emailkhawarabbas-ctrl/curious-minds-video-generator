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


# --------------------------------------------------------------------------- per-niche hosts
NICHE_HOSTS = ("human_body", "science", "psychology")


@pytest.mark.parametrize("char_id", NICHE_HOSTS)
def test_niche_hosts_rig_like_milo_and_draw_every_pose(char_id):
    st, milo = load_character(char_id), load_character("milo")
    for k in ("shoulder_l", "shoulder_r", "upper_arm", "forearm", "thigh", "shin", "eye_l", "eye_r", "mouth"):
        assert st.rig[k] == milo.rig[k], k                   # same skeleton -> every pose / lip sync works
    assert st.backpack is None and st.spec["niche"] == char_id
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 260)
    ctx = cairo.Context(surf)
    for p in pose_names():
        ctx.set_operator(cairo.OPERATOR_CLEAR)
        ctx.paint()
        ctx.set_operator(cairo.OPERATOR_OVER)
        draw_character(ctx, st, make_pose(p), expression_state("happy"), Placement(100, 250, 230))
        surf.flush()
        alpha = np.frombuffer(surf.get_data(), np.uint8)[3::4]
        assert (alpha > 0).mean() > 0.08, p


def test_host_follows_niche():
    from src.animation.themes import resolve_mascot
    for niche in NICHE_HOSTS:
        assert resolve_mascot(niche, "anything at all") == niche
    assert resolve_mascot("mixed", "Why Does Your Heart Beat Faster?") == "human_body"
    assert resolve_mascot("mixed", "Why Do We Overthink Everything?") == "psychology"
    assert resolve_mascot("mixed", "Why Is the Sky Blue?") == "science"
    assert resolve_mascot("mixed", "Who Invented the Paperclip?") == "science"   # unmatched -> new host, never Milo


def test_storyboard_uses_niche_host_unless_forced(settings):
    from src.content.models import Script
    from src.content.storyboard_generator import StoryboardGenerator
    script = Script.model_validate({"topic": "Why Is the Sky Blue?", "niche": "science", "format": "short",
                                    "title": "Why Is the Sky Blue?", "hook": "Why is the sky blue?",
                                    "sections": [{"title": "A", "beats": [
                                        {"id": "b0", "narration": "Why is the sky blue and not purple?"},
                                        {"id": "b1", "narration": "Sunlight hits tiny air molecules."},
                                        {"id": "b2", "narration": "Stay curious!"}]}]})
    prof = settings.profile("vertical")
    sb = StoryboardGenerator().build(script, prof)
    assert sb.character == "science" and all(s.character.character == "science" for s in sb.scenes)
    forced = StoryboardGenerator().build(script, prof, character="milo")
    assert forced.character == "milo" and all(s.character.character == "milo" for s in forced.scenes)


def test_thumbnail_art_cutout_and_fallback(monkeypatch):
    from src.animation import character_art
    from PIL import Image
    img = Image.new("RGB", (60, 100), (255, 255, 255))
    for x in range(20, 40):                                   # an ink-outlined white "coat" inside a coloured body
        for y in range(20, 90):
            img.putpixel((x, y), (43, 45, 66) if x in (20, 39) or y in (20, 89) else
                         ((255, 255, 255) if 30 <= y <= 60 else (46, 196, 182)))
    out = character_art._cutout(img)
    assert out.size == (20, 70)                               # cropped to the character
    a = np.asarray(out.getchannel("A"))
    assert a.min() == 255                                     # interior white survives, background is gone
    character_art.load_character_art.cache_clear()
    monkeypatch.setattr(character_art, "PROJECT_ROOT", character_art.PROJECT_ROOT / "does-not-exist")
    assert character_art.load_character_art("science") is None   # missing art -> vector rig is used
    assert character_art.load_character_art("milo") is None      # no art configured
    character_art.load_character_art.cache_clear()
