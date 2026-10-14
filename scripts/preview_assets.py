"""Render a contact sheet of SVG assets for visual review.

Usage:
  python scripts/preview_assets.py --category human_body --out sheet.png
  python scripts/preview_assets.py --files assets/science/atom.svg --progress
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import src  # noqa: F401,E402  (fontconfig bootstrap)
import cairo  # noqa: E402

from src.animation.palette import PALETTE  # noqa: E402
from src.animation.svg_loader import load_svg  # noqa: E402
from src.utils.fonts import CAPTION_FONT  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--out", default="asset_sheet.png")
    ap.add_argument("--cell", type=int, default=260)
    ap.add_argument("--progress", action="store_true", help="also show draw-on stages 25/50/75%")
    a = ap.parse_args()
    files = [Path(f) for f in (a.files or [])]
    if a.category:
        files += sorted(Path("assets", a.category).glob("*.svg"))
    if not files:
        sys.exit("no files")
    stages = [0.25, 0.5, 0.75, 1.0] if a.progress else [1.0]
    cols = 4 if not a.progress else len(stages)
    n = len(files) * len(stages)
    rows = math.ceil(n / cols)
    c = a.cell
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, cols * c, rows * (c + 30))
    ctx = cairo.Context(surf)
    ctx.set_source_rgb(*PALETTE["cream"])
    ctx.paint()
    i = 0
    for f in files:
        asset = load_svg(f)
        for st in stages:
            x, y = (i % cols) * c, (i // cols) * (c + 30)
            ctx.set_source_rgba(0, 0, 0, 0.06)
            ctx.rectangle(x + 4, y + 4, c - 8, c - 8)
            ctx.fill()
            h = c * 0.8 if asset.aspect <= 1 else c * 0.8 / asset.aspect
            asset.draw(ctx, x + c / 2, y + c / 2, h, draw_progress=st)
            ctx.select_font_face(CAPTION_FONT)
            ctx.set_font_size(16)
            ctx.set_source_rgb(*PALETTE["ink"])
            ctx.move_to(x + 8, y + c + 20)
            label = f.stem + ("" if st == 1 else f" {int(st*100)}%")
            ctx.show_text(f"{label}  [{len(asset.anchors)} anchors]")
            for name in asset.anchors:
                ax, ay = asset.anchor(name, x + c / 2, y + c / 2, h)
                ctx.set_source_rgb(1, 0, 0)
                ctx.arc(ax, ay, 3, 0, 2 * math.pi)
                ctx.fill()
            i += 1
    surf.write_to_png(a.out)
    print(f"wrote {a.out} ({len(files)} assets)")


if __name__ == "__main__":
    main()
