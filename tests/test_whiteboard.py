"""Whiteboard look: calm camera, stroke-by-stroke drawing, the drawing hand, handwriting, host actions."""
import math
from pathlib import Path

import cairo
import numpy as np

from src.animation.asset_manager import get_asset_manager
from src.animation.character_engine import CharacterAnimator, CharacterCue
from src.animation.character_rig import Placement, compute_skeleton, hand_world
from src.lively.camera import LivelyCamera
from src.lively.drawing import (DrawingHand, DrawnSvg, HandText, _area, decorative, outline_asset, outline_eligible,
                                stroke_order)
from src.lively.style import get_style, load_style
from src.script_mode.builder import build_storyboard, whiteboard_action
from src.script_mode.schema import UserScene, load_user_script

SAMPLE = Path(__file__).resolve().parents[1] / "scripts" / "sample_24_hours_awake.yaml"


def _write(tmp_path, text, name="s.yaml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _seg_dist(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    L2 = (bx - ax) ** 2 + (by - ay) ** 2
    k = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / L2))
    return math.hypot(px - ax - k * (bx - ax), py - ay - k * (by - ay))


def _frame(comp, W, H, t):
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    comp.draw(cairo.Context(s), t)
    s.flush()
    return np.frombuffer(s.get_data(), np.uint8).reshape(H, -1, 4)[:, :W, :3].astype(int)


def test_whiteboard_camera_is_calm():
    cfg = get_style().whiteboard.camera
    cam = LivelyCamera("zoom_in", 5.0, 1080, 1920, cfg, punches=[1.0, 2.0, 3.0])
    assert len(cam.punches) == 1                                     # one key word per scene at most
    scales = [cam.at(t).scale for t in np.arange(0, 5.01, 0.1)]
    base = cam.at(0.0).scale
    assert cam.at(5.0).scale - base <= 0.05                          # 3-5 % slow zoom
    assert max(scales) - base <= 0.05 + 0.08                         # punch is small
    assert max(abs(b - a) for a, b in zip(scales, scales[1:])) < 0.03   # smooth, no jolts
    pan = LivelyCamera("pan_left", 5.0, 1080, 1920, cfg)
    assert abs(pan.at(0).dx - pan.at(5).dx) < 1.0                    # no constant panning
    assert cam.at(2.0).rot == 0.0


def test_partial_whiteboard_camera_override_keeps_calm_defaults(tmp_path):
    p = tmp_path / "style.yaml"
    p.write_text("whiteboard:\n  camera:\n    zoom: 0.03\n", encoding="utf-8")
    st = load_style(p)
    assert st.whiteboard.camera.zoom == 0.03 and st.whiteboard.camera.max_punches == 1
    assert st.camera.zoom == 0.16                                    # the lively camera is untouched


def test_stroke_order_draws_big_shapes_first():
    asset = outline_asset(get_asset_manager().get("brain"))
    order = stroke_order(asset)
    areas = [_area(asset.shapes[r.shape]) for r in order]
    assert areas[0] == max(areas)
    biggest = max(areas)
    tiers = [0 if a >= 0.2 * biggest else (1 if a >= 0.03 * biggest else 2) for a in areas]
    assert tiers == sorted(tiers)                                    # big -> medium -> details


def test_fill_only_shapes_get_an_outline_but_shadows_do_not():
    am = get_asset_manager()
    found = False
    for aid in am.ids():
        a = am.get(aid)
        out = outline_asset(a)
        for sh, sh2 in zip(a.shapes, out.shapes):
            if outline_eligible(sh, a):
                assert sh2.stroke is not None
                found = True
            if decorative(sh):
                assert sh2.stroke is None
    assert found


def test_drawing_takes_its_time_then_fills():
    d = DrawnSvg(asset=get_asset_manager().get("car"), center=(540, 700), height=600, fill_s=0.5).plan(0.2, 3.0)
    assert abs(d.t_last - 3.2) < 1e-6 and abs(d.done_at - 3.7) < 1e-6
    assert all(s.t1 >= s.t0 for s in d.strokes)
    assert all(b.t0 >= a.t1 - 1e-9 for a, b in zip(d.strokes, d.strokes[1:]))   # one stroke at a time


def test_hand_follows_the_pen_and_lifts_between_strokes():
    d = DrawnSvg(asset=get_asset_manager().get("eye"), center=(540, 700), height=600).plan(0.0, 3.0)
    hand = DrawingHand(drawings=[d], W=1080, H=1920, size=450)
    s = d.strokes[len(d.strokes) // 2]
    t = (s.t0 + s.t1) / 2
    (x, y), lift = hand.tip_at(t)
    assert lift == 0.0
    assert min(_seg_dist((x, y), a, b) for a, b in zip(s.pts, s.pts[1:])) < 1.0
    gap = next((a, b) for a, b in zip(d.strokes, d.strokes[1:]) if b.t0 - a.t1 > 0.03)
    assert hand.tip_at((gap[0].t1 + gap[1].t0) / 2)[1] > 0.5            # pen lifted while moving to the next stroke
    assert hand.tip_at(d.t_last + 5.0) is None                           # leaves the frame when done


def test_handwriting_traces_each_letter():
    ht = HandText(text="SLEEP", center=(540, 900), size=90, underline=(1, 0.3, 0.4)).plan(0.0, 1.0)
    groups = {s.group for s in ht.strokes if s.group >= 0}
    kinds = [[int(k) for k, _ in g] for g in ht.glyphs]          # Cairo path element types per letter
    assert len(groups) == 5 and len(ht.glyphs) == 5, f"glyph path elements: {kinds}"
    assert ht.strokes[-1].group == -1                                    # the underline comes last
    two = HandText(text="TWO\nLINES", center=(540, 900), size=90)
    ys = [p[1] for s in two.strokes for p in s.pts]
    assert max(ys) - min(ys) > 90                                        # really on two lines


def _scene(text, **kw):
    return UserScene(text=text, **kw)


def test_host_action_is_read_from_the_text():
    assert whiteboard_action(_scene("Why do we dream?"), 0, [])[0] == "think"
    assert whiteboard_action(_scene("There are two kinds of sleep."), 0, [])[0] == "count"
    assert whiteboard_action(_scene("Your brain acts drunk!"), 0, [])[0] == "surprised"
    assert whiteboard_action(_scene("The heart pumps because muscles squeeze."), 0, [])[0] == "draw"
    assert whiteboard_action(_scene("Coffee and a clock.", visuals=["clock.svg"]), 0, [])[0] == "hold_up"
    assert whiteboard_action(_scene("Scientists still argue, nobody knows."), 0, [])[0] == "shrug"
    assert whiteboard_action(_scene("Why?"), 1, ["think"])[0] != "think"      # never the same twice in a row
    assert whiteboard_action(_scene("Why?", pose="wave"), 0, [])[0] == "wave"  # the script wins


def test_sample_builds_whiteboard_with_varied_hosts(settings):
    sb = build_storyboard(load_user_script(SAMPLE), settings.profile("vertical"))
    assert all(sc.layout == "whiteboard" for sc in sb.scenes)
    assert all(sc.lively.animation == "draw_on" for sc in sb.scenes)
    acts = [sc.character.action for sc in sb.scenes]
    assert all(a != b for a, b in zip(acts, acts[1:])) and len(set(acts)) >= 4
    assert sb.scenes[0].character.entrance == "walk"
    assert not any(sc.lively.shake for sc in sb.scenes)


def test_draw_action_puts_the_marker_on_the_pen():
    place = Placement(300, 1600, 800, 1)
    target = (560, 980)
    ca = CharacterAnimator(place=place, cues=[CharacterCue("draw", "happy", 0.0, target_fn=lambda t: target)],
                           char_id="science", entrance="none")
    pose, _, pl, _ = ca.state_at(1.0, 5.0)
    assert pose["hand_r"] == "marker"
    sk = compute_skeleton(ca.style, pose)
    nib = hand_world(ca.style, pl, sk, "r", reach=106)                 # anchor-tip of hand_marker.svg
    assert math.hypot(nib[0] - target[0], nib[1] - target[1]) < 0.08 * place.height


def test_count_raises_one_two_three_fingers():
    ca = CharacterAnimator(place=Placement(300, 1600, 800, 1), cues=[CharacterCue("count", "happy", 0.0, count=3)],
                           entrance="none", count_step=0.5)
    hands = [ca.state_at(t, 5.0)[0]["hand_r"] for t in (0.2, 0.7, 1.2, 2.5)]
    assert hands == ["one", "two", "three", "three"]


def _wb_comp(action="draw", first=True, duration=6.0):
    from src.animation.scene_engine import LayoutContext, WordTiming
    from src.content.models import Scene
    from src.lively.composer import compose_lively
    text = "Your brain starts acting like it is drunk because it is tired and slow."
    words = [WordTiming(w, 0.3 + i * 0.33, 0.6 + i * 0.33) for i, w in enumerate(text.split())]
    sc = Scene(scene_id="s1", narration=text, est_duration=duration, layout="whiteboard", background="doodle_paper",
               objects=[{"asset": "brain"}], character={"character": "science", "position": "left", "action": action},
               lively={"animation": "draw_on", "headline": "24 HOURS", "emphasis": ["drunk"], "camera": "zoom_in"},
               transition_out="whip_left")
    W, H = 270, 480
    L = LayoutContext(W=W, H=H, vertical=True, safe_top=58, safe_bottom=105, safe_left=18, safe_right=38,
                      caption_top=300, caption_bottom=360, duration=duration, words=words, speech_start=0.3,
                      speech_end=duration - 0.4, seed=3)
    return compose_lively(sc, L, envelope=[0.5] * 400, first=first), W, H


def test_whiteboard_scene_draws_for_most_of_the_scene_and_never_stalls():
    comp, W, H = _wb_comp()
    main = next(e for e in comp.elements if isinstance(e, DrawnSvg))
    assert 0.45 * comp.duration <= main.done_at <= 0.75 * comp.duration
    hand = next(e for e in comp.elements if isinstance(e, DrawingHand))
    assert hand.tip_at(main.t_first + 0.5) is not None
    label = next(e for e in comp.elements if isinstance(e, HandText) and e.text == "DRUNK")
    assert label.by_host                                                  # the drawing host writes it
    frames = [_frame(comp, W, H, t) for t in np.arange(0.3, 5.6, 0.5)]
    changes = [(np.abs(frames[i + 3] - frames[i]) > 12).mean() for i in range(len(frames) - 3)]
    assert min(changes) > 0.002                                           # something changes every ~1.5 s
    assert any(name == "scribble" for _, name in comp.events)


def test_whiteboard_hook_frame_is_already_moving_with_text():
    comp, W, H = _wb_comp(action="explain")
    a, b = _frame(comp, W, H, 0.45), _frame(comp, W, H, 0.6)
    assert (np.abs(a - b) > 20).mean() > 0.001                            # the pen is writing the headline
    head = next(e for e in comp.elements if isinstance(e, HandText) and "24" in e.text)
    assert head.t_first == 0.0


def test_whiteboard_is_the_script_mode_default(tmp_path, settings):
    p = _write(tmp_path, 'title: "Tiny"\nscenes:\n  - text: "Hello brain, why?"\n')
    sb = build_storyboard(load_user_script(p), settings.profile("vertical"))
    assert sb.scenes[0].layout == "whiteboard" and sb.scenes[0].character.action == "think"
