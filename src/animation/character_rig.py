"""Hierarchical 2D character rig built from SVG parts.

Skeleton (rig units, y down, hip centre at the origin):

    root ─ torso (lean, bob) ─ neck ─ head (tilt, turn, face)
         │                    ├ shoulder_l ─ upper arm ─ forearm ─ hand (shape)
         │                    └ shoulder_r ─ upper arm ─ forearm ─ hand (shape)
         ├ hip_l ─ thigh ─ shin ─ shoe
         └ hip_r ─ thigh ─ shin ─ shoe

Angle convention: a limb with angle ``a`` points along ``(sin a, cos a)``; 0 = down,
90 = towards the facing direction, 180 = up. Child angles are relative to the parent.
Limbs are drawn as outlined capsules (sleeve / skin / trouser colours from the spec);
head, torso, backpack, hands and shoes are SVG parts. The whole character is mirrored
for ``facing = -1``.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cairo

from src.animation.expression_engine import FaceRenderer, FaceState
from src.animation.palette import hex_to_rgb
from src.animation.svg_loader import SvgAsset, load_svg

CHAR_ROOT = Path(__file__).resolve().parents[2] / "assets" / "characters"
POSES_FILE = CHAR_ROOT / "poses.json"
Point = Tuple[float, float]

POSE_KEYS_NUM = ("arm_l_sh", "arm_l_el", "arm_r_sh", "arm_r_el", "leg_l_hip", "leg_l_knee",
                 "leg_r_hip", "leg_r_knee", "foot_l", "foot_r", "torso_lean", "torso_bob",
                 "head_tilt", "head_turn", "look_x", "look_y", "body_y", "body_x", "squash")
HAND_SHAPES = ("open", "fist", "point", "thumbs_up", "hold")
POSE_DEFAULTS: Dict[str, float] = {k: 0.0 for k in POSE_KEYS_NUM}
POSE_DEFAULTS.update({"squash": 1.0, "leg_l_hip": -3.0, "leg_r_hip": 3.0})


@lru_cache(maxsize=1)
def load_pose_library() -> Dict[str, Dict]:
    data = json.loads(POSES_FILE.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def pose_names() -> Tuple[str, ...]:
    return tuple(sorted(load_pose_library()))


def make_pose(name: str = "stand", **overrides) -> Dict:
    lib = load_pose_library()
    if name not in lib:
        raise KeyError(f"unknown pose {name!r}; valid: {sorted(lib)}")
    p: Dict = dict(POSE_DEFAULTS)
    p.update({"hand_l": "open", "hand_r": "open"})
    p.update(lib[name])
    p.update(overrides)
    return p


def blend_poses(a: Dict, b: Dict, t: float) -> Dict:
    t = max(0.0, min(1.0, t))
    out = dict(a)
    for k in POSE_KEYS_NUM:
        out[k] = a.get(k, POSE_DEFAULTS[k]) + (b.get(k, POSE_DEFAULTS[k]) - a.get(k, POSE_DEFAULTS[k])) * t
    for k in ("hand_l", "hand_r"):
        out[k] = b.get(k, "open") if t >= 0.5 else a.get(k, "open")
    for side in ("l", "r"):
        ka, kb = a.get(f"ik_{side}"), b.get(f"ik_{side}")
        if ka is not None and kb is not None:
            out[f"ik_{side}"] = (ka[0] + (kb[0] - ka[0]) * t, ka[1] + (kb[1] - ka[1]) * t)
        elif ka is not None or kb is not None:
            # resolve the IK side to angles so it can be interpolated against FK angles
            sa, sb = _fk_angles(a, side), _fk_angles(b, side)
            out[f"arm_{side}_sh"] = sa[0] + (sb[0] - sa[0]) * t
            out[f"arm_{side}_el"] = sa[1] + (sb[1] - sa[1]) * t
            out.pop(f"ik_{side}", None)
    return out


def _fk_angles(pose: Dict, side: str) -> Tuple[float, float]:
    target = pose.get(f"ik_{side}")
    if target is None:
        return pose.get(f"arm_{side}_sh", 0.0), pose.get(f"arm_{side}_el", 0.0)
    rig = load_character("milo").rig
    sh = tuple(rig[f"shoulder_{side}"])
    bend = pose.get(f"ik_bend_{side}", 1.0 if side == "r" else -1.0)
    return solve_two_bone_ik(sh, tuple(target), rig["upper_arm"], rig["forearm"] + 28, bend)


# --------------------------------------------------------------------------- style
def _recolor(asset: SvgAsset, mapping: Dict[str, str]) -> SvgAsset:
    if not mapping:
        return asset
    m = {tuple(round(c, 3) for c in hex_to_rgb(k)): hex_to_rgb(v) for k, v in mapping.items()}
    for sh in asset.shapes:
        for attr in ("fill", "stroke"):
            col = getattr(sh, attr)
            if col is None:
                continue
            key = tuple(round(c, 3) for c in col[:3])
            if key in m:
                setattr(sh, attr, (*m[key], col[3]))
    return asset


@dataclass
class CharacterStyle:
    char_id: str
    name: str
    spec: Dict
    rig: Dict
    colors: Dict[str, str]
    head: SvgAsset
    torso: SvgAsset
    backpack: Optional[SvgAsset]
    shoe: SvgAsset
    hands: Dict[str, SvgAsset]
    face: FaceRenderer = field(init=False)

    def __post_init__(self) -> None:
        self.face = FaceRenderer(self.rig, self.colors)

    @property
    def height_units(self) -> float:
        return float(self.rig["ground_offset"] - self.rig["head_top"])


@lru_cache(maxsize=8)
def load_character(char_id: str = "milo") -> CharacterStyle:
    d = CHAR_ROOT / char_id
    spec = json.loads((d / "character.json").read_text())
    base_id = spec.get("base")
    if base_id:
        base = json.loads((CHAR_ROOT / base_id / "character.json").read_text())
        merged = dict(base)
        merged.update({k: v for k, v in spec.items() if k not in ("colors", "parts", "rig")})
        merged["colors"] = {**base["colors"], **spec.get("colors", {})}
        merged["parts"] = {**base["parts"], **spec.get("parts", {})}
        merged["rig"] = {**base["rig"], **spec.get("rig", {})}
        spec = merged
    recolor = spec.get("recolor", {})
    hide = set(spec.get("hide_parts", []))

    def part(fname: str) -> SvgAsset:
        own = d / fname
        src = own if own.exists() else CHAR_ROOT / (base_id or char_id) / fname
        asset = load_svg(src, f"{char_id}:{Path(fname).stem}")
        # parts that the character overrides itself are already authored in its colours
        return asset if own.exists() and base_id else _recolor(asset, recolor)

    parts = spec["parts"]
    return CharacterStyle(
        char_id=char_id, name=spec.get("name", char_id), spec=spec, rig=spec["rig"],
        colors=spec["colors"], head=part(parts["head"]), torso=part(parts["torso"]),
        backpack=None if "backpack" in hide else part(parts["backpack"]),
        shoe=part(parts["shoe"]), hands={k: part(v) for k, v in parts["hands"].items()})


def available_characters() -> List[str]:
    return sorted(p.name for p in CHAR_ROOT.iterdir() if (p / "character.json").exists())


# --------------------------------------------------------------------------- math
def _dir(angle_deg: float) -> Point:
    a = math.radians(angle_deg)
    return math.sin(a), math.cos(a)


def _rot(p: Point, deg: float) -> Point:
    a = math.radians(deg)
    return (p[0] * math.cos(a) - p[1] * math.sin(a), p[0] * math.sin(a) + p[1] * math.cos(a))


def solve_two_bone_ik(origin: Point, target: Point, l1: float, l2: float,
                      bend: float = 1.0) -> Tuple[float, float]:
    """Return (shoulder_angle, elbow_relative_angle) reaching `target` from `origin`.

    `bend` = +1 / -1 selects which side the elbow bends to.
    """
    dx, dy = target[0] - origin[0], target[1] - origin[1]
    d = math.hypot(dx, dy)
    d = max(abs(l1 - l2) + 1e-3, min(l1 + l2 - 1e-3, d))
    base = math.degrees(math.atan2(dx, dy))  # our convention: (sin a, cos a)
    cos_a = (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)
    alpha = math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))
    upper = base + bend * alpha
    ex = origin[0] + l1 * math.sin(math.radians(upper))
    ey = origin[1] + l1 * math.cos(math.radians(upper))
    fore = math.degrees(math.atan2(target[0] - ex, target[1] - ey))
    rel = (fore - upper + 180) % 360 - 180
    return upper, rel


@dataclass
class Placement:
    x: float            # world x of the ground point between the feet
    y: float            # world y of the ground
    height: float       # on-screen height in px (feet to top of hair)
    facing: int = 1     # 1 = right, -1 = left

    def scale(self, style: CharacterStyle) -> float:
        return self.height / style.height_units

    def to_world(self, style: CharacterStyle, p: Point) -> Point:
        s = self.scale(style)
        return (self.x + p[0] * s * self.facing, self.y + (p[1] - style.rig["ground_offset"]) * s)

    def to_rig(self, style: CharacterStyle, p: Point) -> Point:
        s = self.scale(style)
        return ((p[0] - self.x) / (s * self.facing), (p[1] - self.y) / s + style.rig["ground_offset"])


@dataclass
class Skeleton:
    """Joint positions in rig units for a pose (computed before drawing)."""
    torso_origin: Point
    neck: Point
    head_angle: float
    shoulders: Dict[str, Point]
    elbows: Dict[str, Point]
    wrists: Dict[str, Point]
    fore_angles: Dict[str, float]
    hips: Dict[str, Point]
    knees: Dict[str, Point]
    ankles: Dict[str, Point]
    head_center: Point
    head_top: Point
    mouth: Point


def compute_skeleton(style: CharacterStyle, pose: Dict) -> Skeleton:
    r = style.rig
    root = (pose.get("body_x", 0.0), pose.get("body_y", 0.0))
    lean = pose.get("torso_lean", 0.0)
    bob = pose.get("torso_bob", 0.0)
    torso_origin = (root[0], root[1] + bob)

    def torso_pt(p: Point) -> Point:
        q = _rot((p[0], p[1] * pose.get("squash", 1.0)), lean)
        return (torso_origin[0] + q[0], torso_origin[1] + q[1])

    neck = torso_pt(tuple(r["neck"]))
    head_angle = lean + pose.get("head_tilt", 0.0)
    shoulders, elbows, wrists, fore = {}, {}, {}, {}
    for side in ("l", "r"):
        sh = torso_pt(tuple(r[f"shoulder_{side}"]))
        target = pose.get(f"ik_{side}")
        if target is not None:
            # IK target is given for the hand centre (rig units); bend elbows outward/down
            bend = pose.get(f"ik_bend_{side}", 1.0 if side == "r" else -1.0)
            a1, rel = solve_two_bone_ik(sh, (target[0], target[1]), r["upper_arm"], r["forearm"] + 28, bend)
            a2 = a1 + rel
        else:
            a1 = pose.get(f"arm_{side}_sh", 0.0)
            a2 = a1 + pose.get(f"arm_{side}_el", 0.0)
        d1, d2 = _dir(a1), _dir(a2)
        el = (sh[0] + d1[0] * r["upper_arm"], sh[1] + d1[1] * r["upper_arm"])
        wr = (el[0] + d2[0] * r["forearm"], el[1] + d2[1] * r["forearm"])
        shoulders[side], elbows[side], wrists[side], fore[side] = sh, el, wr, a2
    hips, knees, ankles = {}, {}, {}
    for side in ("l", "r"):
        hp = (root[0] + r[f"hip_{side}"][0], root[1] + r[f"hip_{side}"][1])
        a1 = pose.get(f"leg_{side}_hip", 0.0)
        a2 = a1 + pose.get(f"leg_{side}_knee", 0.0)
        d1, d2 = _dir(a1), _dir(a2)
        kn = (hp[0] + d1[0] * r["thigh"], hp[1] + d1[1] * r["thigh"])
        an = (kn[0] + d2[0] * r["shin"], kn[1] + d2[1] * r["shin"])
        hips[side], knees[side], ankles[side] = hp, kn, an
    hc = _rot((0, -120), head_angle)
    ht = _rot((0, -255), head_angle)
    mo = _rot(tuple(r["mouth"]), head_angle)
    return Skeleton(torso_origin, neck, head_angle, shoulders, elbows, wrists, fore, hips, knees,
                    ankles, (neck[0] + hc[0], neck[1] + hc[1]), (neck[0] + ht[0], neck[1] + ht[1]),
                    (neck[0] + mo[0], neck[1] + mo[1]))


# --------------------------------------------------------------------------- drawing
def _capsule(ctx: cairo.Context, pts: List[Point], width: float, colors: List[Tuple[float, float, float]],
             outline: Tuple[float, float, float], outline_w: float = 7.0) -> None:
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.move_to(*pts[0])
    for p in pts[1:]:
        ctx.line_to(*p)
    ctx.set_source_rgb(*outline)
    ctx.set_line_width(width + 2 * outline_w)
    ctx.stroke()
    for i in range(len(pts) - 1):
        ctx.move_to(*pts[i])
        ctx.line_to(*pts[i + 1])
        ctx.set_source_rgb(*colors[min(i, len(colors) - 1)])
        ctx.set_line_width(width)
        ctx.stroke()


def draw_character(ctx: cairo.Context, style: CharacterStyle, pose: Dict, face: FaceState,
                   place: Placement, alpha: float = 1.0,
                   held: Optional[Callable[[cairo.Context, Skeleton], None]] = None) -> Skeleton:
    """Draw the character. `held` (optional) draws a held prop in rig space between torso and arms."""
    sk = compute_skeleton(style, pose)
    r, c = style.rig, style.colors
    ink = hex_to_rgb(c["outline"])
    s = place.scale(style)
    if alpha < 0.999:
        ctx.push_group()
    ctx.save()
    ctx.translate(place.x, place.y)
    ctx.scale(s * place.facing, s)
    ctx.translate(0, -r["ground_offset"])

    # ground shadow
    ctx.save()
    ctx.translate(0, r["ground_offset"] - 2)
    ctx.scale(150, 18 * max(0.35, 1 - abs(pose.get("body_y", 0.0)) / 200))
    ctx.arc(0, 0, 1, 0, 2 * math.pi)
    ctx.restore()
    ctx.set_source_rgba(*ink, 0.13)
    ctx.fill()

    pants = hex_to_rgb(c["pants"])
    pants_cuff = hex_to_rgb(c["pants_cuff"])
    sleeve, skin = hex_to_rgb(c["sleeve"]), hex_to_rgb(c["skin"])
    cuff = hex_to_rgb(c["sleeve_cuff"])

    # backpack body (behind everything above the legs)
    if style.backpack:
        ctx.save()
        ctx.translate(*sk.torso_origin)
        ctx.rotate(math.radians(pose.get("torso_lean", 0.0)))
        style.backpack.draw_native(ctx, only_groups=("pack",))
        ctx.restore()

    # legs + shoes
    for side in ("l", "r"):
        hp, kn, an = sk.hips[side], sk.knees[side], sk.ankles[side]
        _capsule(ctx, [hp, kn, an], r["leg_width"], [pants, pants], ink)
        # trouser cuff
        d = (an[0] - kn[0], an[1] - kn[1])
        L = math.hypot(*d) or 1
        cpt = (an[0] - d[0] / L * 8, an[1] - d[1] / L * 8)
        ctx.move_to(*cpt)
        ctx.line_to(*an)
        ctx.set_source_rgb(*pants_cuff)
        ctx.set_line_width(r["leg_width"] + 6)
        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
        ctx.stroke()
        ctx.save()
        ctx.translate(*an)
        ctx.rotate(math.radians(-pose.get(f"foot_{side}", 0.0)))
        style.shoe.draw_native(ctx)
        ctx.restore()

    # torso
    ctx.save()
    ctx.translate(*sk.torso_origin)
    ctx.rotate(math.radians(pose.get("torso_lean", 0.0)))
    ctx.scale(1, pose.get("squash", 1.0))
    style.torso.draw_native(ctx)
    if style.backpack:
        style.backpack.draw_native(ctx, only_groups=("straps",))
    ctx.restore()

    # neck + head
    ctx.save()
    ctx.translate(*sk.neck)
    ctx.rotate(math.radians(sk.head_angle))
    ctx.rectangle(-r["neck_width"] / 2, -r["neck_length"] - 20, r["neck_width"], r["neck_length"] + 26)
    ctx.set_source_rgb(*hex_to_rgb(c["skin_shadow"]))
    ctx.fill()
    style.head.draw_native(ctx, only_groups=("back",))
    style.face.draw(ctx, face)
    style.head.draw_native(ctx, only_groups=("front",))
    ctx.restore()

    if held:
        held(ctx, sk)

    # arms + hands (in front)
    for side in ("l", "r"):
        sh, el, wr = sk.shoulders[side], sk.elbows[side], sk.wrists[side]
        _capsule(ctx, [sh, el, wr], r["arm_width"], [sleeve, skin], ink)
        # rolled sleeve cuff at the elbow
        d = (el[0] - sh[0], el[1] - sh[1])
        L = math.hypot(*d) or 1
        a = (el[0] - d[0] / L * 14, el[1] - d[1] / L * 14)
        b = (el[0] + d[0] / L * 6, el[1] + d[1] / L * 6)
        ctx.move_to(*a)
        ctx.line_to(*b)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_source_rgb(*ink)
        ctx.set_line_width(r["arm_width"] + 16)
        ctx.stroke()
        ctx.move_to(*a)
        ctx.line_to(*b)
        ctx.set_source_rgb(*cuff)
        ctx.set_line_width(r["arm_width"] + 4)
        ctx.stroke()
        hand = style.hands.get(pose.get(f"hand_{side}", "open"), style.hands["open"])
        ctx.save()
        ctx.translate(*wr)
        ctx.rotate(-math.radians(sk.fore_angles[side]))
        if side == "l":
            ctx.scale(-1, 1)  # mirror so thumbs face the body on both hands
        hand.draw_native(ctx)
        ctx.restore()

    ctx.restore()
    if alpha < 0.999:
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(alpha)
    return sk


def hand_world(style: CharacterStyle, place: Placement, sk: Skeleton, side: str, reach: float = 40) -> Point:
    """World position slightly past the wrist (centre of the hand)."""
    a = sk.fore_angles[side]
    wr = sk.wrists[side]
    p = (wr[0] + math.sin(math.radians(a)) * reach, wr[1] + math.cos(math.radians(a)) * reach)
    return place.to_world(style, p)
