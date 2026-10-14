"""Render the character model sheet (all poses / all expressions) for visual QA.

  python scripts/character_sheet.py --char milo --out milo_sheet.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import src  # noqa: F401,E402
import cairo  # noqa: E402

from src.animation.character_rig import Placement, draw_character, load_character, make_pose, pose_names  # noqa: E402
from src.animation.expression_engine import expression_names, expression_state, with_overrides  # noqa: E402
from src.animation.palette import PALETTE  # noqa: E402
from src.utils.fonts import CAPTION_FONT  # noqa: E402

POSE_FACE = {"think": "thinking", "sad": "sad", "surprised": "surprised", "excited": "excited",
             "wave": "happy", "yawn": "yawning", "shrug": "confused", "thumbs_up": "happy",
             "point_up": "curious", "explain": "happy"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--char", default="milo")
    ap.add_argument("--out", default="character_sheet.png")
    ap.add_argument("--mode", choices=["poses", "faces"], default="poses")
    a = ap.parse_args()
    style = load_character(a.char)
    items = pose_names() if a.mode == "poses" else expression_names()
    cols, cw, ch = 6, 300, 420 if a.mode == "poses" else 300
    rows = (len(items) + cols - 1) // cols
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, cols * cw, rows * ch)
    ctx = cairo.Context(surf)
    ctx.set_source_rgb(*PALETTE["cream"])
    ctx.paint()
    for i, name in enumerate(items):
        x, y = (i % cols) * cw, (i // cols) * ch
        ctx.save()
        ctx.rectangle(x, y, cw, ch)
        ctx.clip()
        if a.mode == "poses":
            pose = make_pose(name)
            face = with_overrides(expression_state(POSE_FACE.get(name, "neutral")),
                                  look_x=pose.get("look_x", 0), look_y=pose.get("look_y", 0),
                                  head_turn=pose.get("head_turn", 0))
            draw_character(ctx, style, pose, face, Placement(x + cw / 2, y + ch - 40, 340))
        else:
            pose = make_pose("stand")
            draw_character(ctx, style, pose, expression_state(name), Placement(x + cw / 2, y + ch * 1.9, 640))
        ctx.select_font_face(CAPTION_FONT)
        ctx.set_font_size(22)
        ctx.set_source_rgb(*PALETTE["ink"])
        ctx.move_to(x + 12, y + 28)
        ctx.show_text(name)
        ctx.restore()
    surf.write_to_png(a.out)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
