"""Time-based character animation: actions, gesture cycles, lip sync, blinking, IK.

A :class:`CharacterAnimator` turns storyboard character directions (action +
expression + optional target) into a pose / face / placement for any time ``t``
within a scene, then draws it through the rig.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cairo

from src.animation.character_rig import (CharacterStyle, Placement, Skeleton, blend_poses, draw_character,
                                         load_character, make_pose)
from src.animation.easing import clamp, ease_in_out_sine, ease_out_back, ease_out_cubic
from src.animation.expression_engine import FaceState, blend, blink_amount, expression_state, with_overrides

ACTIONS = ("idle", "talk", "explain", "walk", "run", "point", "think", "wave", "surprised", "excited",
           "happy", "sad", "hold", "look_at", "interact", "yawn", "shrug", "present", "thumbs_up",
           "celebrate", "sleep")
ENTRANCES = ("none", "walk", "run", "pop", "slide")

GESTURES = ("explain", "present", "explain_alt", "relaxed", "point_up", "explain", "stand")
POSE_BLEND = 0.32


@dataclass
class CharacterCue:
    action: str = "talk"
    expression: str = "happy"
    start: float = 0.0
    end: float = 1e9
    target: Optional[Tuple[float, float]] = None   # world px (point / look_at / interact)
    walk_to: Optional[Tuple[float, float]] = None  # world ground point for walk/run cues

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"unknown character action {self.action!r}; valid: {ACTIONS}")
        expression_state(self.expression)  # raises on unknown expression


def _hash01(*vals: float) -> float:
    h = 0
    for v in vals:
        h = (h * 1000003 + int(v * 1000) + 0x9E3779B1) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 2246822519) & 0xFFFFFFFF
    h ^= h >> 13
    return (h & 0xFFFF) / 0xFFFF


@dataclass
class CharacterAnimator:
    place: Placement
    cues: List[CharacterCue]
    char_id: str = "milo"
    envelope: Optional[Sequence[float]] = None     # lip-sync amplitude per frame (0..1)
    fps: int = 30
    seed: int = 1
    entrance: str = "pop"
    entrance_from: str = "left"                    # left | right
    talks: bool = True
    held: Optional[Callable[[cairo.Context, Skeleton, float], None]] = None
    style: CharacterStyle = field(init=False)

    def __post_init__(self) -> None:
        self.style = load_character(self.char_id)
        if self.entrance not in ENTRANCES:
            raise ValueError(f"unknown entrance {self.entrance!r}")
        if not self.cues:
            self.cues = [CharacterCue()]
        self.cues.sort(key=lambda c: c.start)

    # ------------------------------------------------------------------ helpers
    def _cue_at(self, t: float) -> Tuple[int, CharacterCue]:
        idx = 0
        for i, c in enumerate(self.cues):
            if c.start <= t:
                idx = i
        return idx, self.cues[idx]

    def mouth_level(self, t: float) -> float:
        if not self.envelope or not self.talks:
            return 0.0
        i = int(t * self.fps)
        if 0 <= i < len(self.envelope):
            return float(self.envelope[i])
        return 0.0

    def _ground_x_at(self, t: float) -> float:
        """Character x including walk/run cues (the walk path is cumulative)."""
        x = self.place.x
        for c in self.cues:
            if c.action in ("walk", "run") and c.walk_to is not None and t >= c.start:
                dur = max(0.1, min(c.end, 1e6) - c.start)
                speed = 520 if c.action == "walk" else 1100
                travel_time = min(dur, abs(c.walk_to[0] - x) / speed + 0.2)
                p = ease_in_out_sine(clamp((t - c.start) / travel_time))
                x = x + (c.walk_to[0] - x) * p
        return x

    def _moving(self, t: float) -> Tuple[bool, float, int]:
        """(is_moving, speed_factor, direction) for walk/run cues."""
        x_prev, x_now = self._ground_x_at(t - 1 / self.fps), self._ground_x_at(t)
        v = (x_now - x_prev) * self.fps
        return abs(v) > 25, abs(v), (1 if v >= 0 else -1)

    # ------------------------------------------------------------------ poses
    def _action_pose(self, cue: CharacterCue, t: float, place: Placement) -> Dict:
        lt = t - cue.start
        a = cue.action
        breath = math.sin(t * 2 * math.pi / 3.2 + self.seed)
        base_bob = 3.0 * breath
        if a in ("talk", "explain"):
            period = 1.9 if a == "talk" else 1.5
            k = int(lt / period)
            names = GESTURES if a == "talk" else ("explain", "explain_alt", "present", "explain")
            g1 = names[int(_hash01(k, self.seed) * len(names))]
            g0 = names[int(_hash01(k - 1, self.seed) * len(names))] if k > 0 else "stand"
            f = clamp((lt - k * period) / 0.45)
            pose = blend_poses(make_pose(g0), make_pose(g1), ease_in_out_sine(f))
            m = self.mouth_level(t)
            pose["head_tilt"] = pose.get("head_tilt", 0) + 4 * math.sin(lt * 1.7) + 3 * m
            pose["torso_bob"] = base_bob - 3 * m
            # beat gestures: forearms flick with speech energy
            pose["arm_r_el"] = pose.get("arm_r_el", 0) + 10 * m
            pose["arm_l_el"] = pose.get("arm_l_el", 0) - 6 * m
            return pose
        if a == "idle":
            p = make_pose("relaxed", torso_bob=base_bob, head_tilt=2 * math.sin(t * 0.8))
            p["arm_r_el"] -= 4 * breath
            p["arm_l_el"] += 4 * breath
            return p
        if a in ("walk", "run"):
            return make_pose("stand", torso_bob=base_bob)  # legs handled by locomotion overlay
        if a in ("point", "interact") and cue.target is not None:
            tx, ty = place.to_rig(self.style, cue.target)
            if a == "interact":
                tap = 0.5 - 0.5 * math.cos(lt * 2 * math.pi / 1.4)
                sx, sy = self.style.rig["shoulder_r"]
                tx, ty = sx + (tx - sx) * (0.75 + 0.25 * tap), sy + (ty - sy) * (0.75 + 0.25 * tap)
            sx, sy = self.style.rig["shoulder_r"]
            reach = self.style.rig["upper_arm"] + self.style.rig["forearm"] + 20
            dx, dy = tx - sx, ty - sy
            d = math.hypot(dx, dy) or 1
            if d > reach:
                tx, ty = sx + dx / d * reach, sy + dy / d * reach
            pose = make_pose("stand", torso_bob=base_bob, hand_r="point" if a == "point" else "open")
            pose["ik_r"] = (tx, ty)
            pose["torso_lean"] = clamp(dx / 60, -1, 1) * 4
            pose["head_turn"] = 0.45
            pose["look_x"] = 0.8
            pose["look_y"] = clamp(dy / 300, -1, 1)
            return pose
        if a == "point":
            return make_pose("point_forward", torso_bob=base_bob)
        if a == "think":
            p = make_pose("think", torso_bob=base_bob)
            p["head_tilt"] += 3 * math.sin(lt * 1.3)
            p["look_x"] = 0.6 + 0.3 * math.sin(lt * 0.9)
            return p
        if a == "wave":
            p = make_pose("wave", torso_bob=base_bob)
            p["arm_r_el"] = 25 + 28 * math.sin(lt * 10)
            return p
        if a == "surprised":
            jump = math.sin(clamp(lt / 0.45) * math.pi) * 34 if lt < 0.45 else 0.0
            p = make_pose("surprised", body_y=-jump, torso_bob=base_bob * 0.5)
            return p
        if a in ("excited", "celebrate"):
            hop = abs(math.sin(lt * math.pi * 1.6)) * 32
            p = make_pose("excited", body_y=-hop)
            p["arm_r_sh"] += 8 * math.sin(lt * 9)
            p["arm_l_sh"] -= 8 * math.sin(lt * 9 + 1)
            return p
        if a == "happy":
            bounce = abs(math.sin(lt * math.pi * 1.2)) * 10
            return make_pose("thumbs_up" if int(lt / 2.5) % 2 == 0 else "present", body_y=-bounce,
                             torso_bob=base_bob)
        if a == "sad":
            return make_pose("sad", torso_bob=base_bob * 0.6, head_tilt=10 + 2 * math.sin(lt))
        if a == "hold":
            return make_pose("hold", torso_bob=base_bob)
        if a == "look_at":
            p = make_pose("relaxed", torso_bob=base_bob)
            if cue.target is not None:
                tx, ty = place.to_rig(self.style, cue.target)
                p["head_turn"] = clamp(tx / 400, -1, 1) * 0.6
                p["look_x"] = clamp(tx / 250, -1, 1)
                p["look_y"] = clamp((ty + 120) / 300, -1, 1)
            return p
        if a == "yawn":
            f = math.sin(clamp(lt / 2.2) * math.pi)
            return blend_poses(make_pose("relaxed"), make_pose("yawn"), f)
        if a == "shrug":
            p = make_pose("shrug", torso_bob=base_bob)
            p["body_y"] = -4 * abs(math.sin(lt * 4)) if lt < 0.6 else 0
            return p
        if a == "present":
            return make_pose("present", torso_bob=base_bob)
        if a == "thumbs_up":
            return make_pose("thumbs_up", torso_bob=base_bob)
        if a == "sleep":
            return make_pose("relaxed", torso_bob=4 * math.sin(t * 2 * math.pi / 4.5), head_tilt=12)
        return make_pose("stand", torso_bob=base_bob)

    def _locomotion(self, pose: Dict, t: float, speed: float, running: bool) -> Dict:
        freq = 2.0 if not running else 3.2
        ph = t * freq * 2 * math.pi
        amp = 26 if not running else 40
        p = dict(pose)
        p["leg_l_hip"] = amp * math.sin(ph)
        p["leg_r_hip"] = -amp * math.sin(ph)
        p["leg_l_knee"] = -max(0.0, math.sin(ph + 1.2)) * (35 if not running else 70)
        p["leg_r_knee"] = -max(0.0, math.sin(ph + 1.2 + math.pi)) * (35 if not running else 70)
        p["foot_l"] = -10 * math.sin(ph)
        p["foot_r"] = 10 * math.sin(ph)
        p["arm_l_sh"] = -amp * 0.8 * math.sin(ph) - 8
        p["arm_r_sh"] = amp * 0.8 * math.sin(ph) + 8
        p["arm_l_el"] = 25 if not running else 80
        p["arm_r_el"] = 25 if not running else 80
        p.pop("ik_l", None)
        p.pop("ik_r", None)
        p["body_y"] = -abs(math.sin(ph)) * (8 if not running else 18)
        p["torso_lean"] = 4 if not running else 12
        p["head_turn"] = 0.5
        p["look_x"] = 0.7
        return p

    def _face(self, cue: CharacterCue, prev: Optional[CharacterCue], t: float, pose: Dict) -> FaceState:
        face = expression_state(cue.expression)
        if prev is not None and t - cue.start < 0.3:
            face = blend(expression_state(prev.expression), face, (t - cue.start) / 0.3)
        m = self.mouth_level(t)
        viseme = _hash01(int(t * 8), self.seed)
        blink = 0.0 if face.eye_shape in ("closed", "arc") else blink_amount(t, self.seed)
        return with_overrides(face, mouth_open=m if cue.action != "sleep" else 0.0, viseme=viseme,
                              blink=blink, look_x=pose.get("look_x", face.look_x),
                              look_y=pose.get("look_y", face.look_y), head_turn=pose.get("head_turn", 0.0))

    # ------------------------------------------------------------------ public
    def state_at(self, t: float, scene_duration: float) -> Tuple[Dict, FaceState, Placement, float]:
        idx, cue = self._cue_at(t)
        prev = self.cues[idx - 1] if idx > 0 else None
        x = self._ground_x_at(t)
        moving, speed, direction = self._moving(t)
        facing = self.place.facing
        if moving:
            facing = direction
        elif cue.target is not None and cue.action in ("point", "interact", "look_at"):
            facing = 1 if cue.target[0] >= x else -1
        place = Placement(x, self.place.y, self.place.height, facing)
        pose = self._action_pose(cue, t, place)
        if prev is not None and t - cue.start < POSE_BLEND:
            prev_pose = self._action_pose(prev, t, place)
            pose = blend_poses(prev_pose, pose, ease_in_out_sine((t - cue.start) / POSE_BLEND))
        if moving:
            pose = self._locomotion(pose, t, speed, cue.action == "run")
        alpha = 1.0
        # entrance
        ent_d = 0.55
        if self.entrance == "pop" and t < ent_d:
            k = ease_out_back(clamp(t / ent_d), 2.2)
            place = Placement(place.x, place.y, place.height * max(0.01, k), place.facing)
        elif self.entrance in ("walk", "run", "slide"):
            ent_d = 1.1 if self.entrance == "walk" else 0.6
            if t < ent_d:
                off = (self.place.height * 0.9 + 200) * (1 if self.entrance_from == "right" else -1)
                p = ease_out_cubic(clamp(t / ent_d))
                place = Placement(place.x + off * (1 - p), place.y, place.height,
                                  -1 if self.entrance_from == "right" else 1)
                if self.entrance != "slide":
                    pose = self._locomotion(pose, t, 400, self.entrance == "run")
        face = self._face(cue, prev, t, pose)
        return pose, face, place, alpha

    def draw(self, ctx: cairo.Context, t: float, scene_duration: float) -> Skeleton:
        pose, face, place, alpha = self.state_at(t, scene_duration)
        held = None
        if self.held is not None:
            cb = self.held

            def held(c: cairo.Context, sk: Skeleton) -> None:
                cb(c, sk, t)
        self.last_place = place
        return draw_character(ctx, self.style, pose, face, place, alpha, held)

    def head_top_world(self, t: float, scene_duration: float) -> Tuple[float, float]:
        pose, face, place, _ = self.state_at(t, scene_duration)
        from src.animation.character_rig import compute_skeleton
        sk = compute_skeleton(self.style, pose)
        return place.to_world(self.style, sk.head_top)
