"""Raster character art (``characters/*.png|jpg``) for still images such as thumbnails.

Videos use the rigged vector version of each character (``assets/characters/<id>``) because
it has to move: poses, lip sync, expressions. Thumbnails don't move, so they show the original
illustration instead. A character opts in with a ``thumbnail`` block in its ``character.json``:

    "thumbnail": {"image": "characters/science.jpg", "mode": "cutout"}
    "thumbnail": {"image": "characters/human_body.png", "mode": "card", "crop": [x0, y0, x1, y1]}

``cutout`` removes the plain white background and the soft grey ground shadow (flood fill from
the border, so whites inside the outlined character survive). Background pockets the border
can't reach (e.g. between a coiled tube and the body) are listed as ``clear_points`` in source
image pixels. ``card`` crops a region of a busy illustration and frames it as a card.
Processed images are cached as PNGs keyed by the source file's size, mtime and the spec.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import cairo
import numpy as np
from PIL import Image, ImageDraw

from src.animation.character_rig import load_character
from src.animation.doodle_engine import rounded_rect
from src.animation.palette import PALETTE

log = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "generated" / ".cache" / "character_art"
MAX_HEIGHT = 1400                 # px; plenty for a 1920 px tall cover frame
_SENTINEL = (0, 255, 0)           # fill colour: must differ from white by more than the threshold
_VERSION = 2                      # bump when the processing changes (invalidates the cache)


@dataclass
class CharacterArt:
    surface: cairo.ImageSurface
    mode: str                     # "cutout" | "card"

    @property
    def aspect(self) -> float:
        return self.surface.get_width() / self.surface.get_height()


def _cutout(img: Image.Image, extra_seeds=(), thresh: int = 250) -> Image.Image:
    """Make the border-connected white background transparent.

    `thresh` is PIL's summed RGB distance from the seed colour; 250 also takes the light grey
    ground shadow (about 213 from white) but stops at ink outlines.
    """
    orig = img.convert("RGB")
    rgb = orig.copy()
    w, h = rgb.size
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
    for xy in [*seeds, *extra_seeds]:
        if not (0 <= xy[0] < w and 0 <= xy[1] < h):
            continue
        px = rgb.getpixel(xy)
        if px != _SENTINEL and min(px) >= 225:        # only flood from near-white background
            ImageDraw.floodfill(rgb, xy, _SENTINEL, thresh=thresh)
    bg = np.any(np.asarray(rgb) != np.asarray(orig), axis=2)   # every pixel the fill touched
    out = np.dstack([np.asarray(orig), np.where(bg, 0, 255).astype(np.uint8)])
    res = Image.fromarray(out, "RGBA")
    box = res.getchannel("A").getbbox()
    return res.crop(box) if box else res


def _process(spec: dict, src: Path) -> Image.Image:
    img = Image.open(src)
    img.load()
    ox, oy = 0, 0
    if spec.get("crop"):
        ox, oy = spec["crop"][0], spec["crop"][1]
        img = img.crop(tuple(spec["crop"]))
    k = 1.0
    if img.height > MAX_HEIGHT:
        k = MAX_HEIGHT / img.height
        img = img.resize((round(img.width * k), MAX_HEIGHT), Image.LANCZOS)
    if spec.get("mode", "cutout") == "cutout":
        seeds = [(int((x - ox) * k), int((y - oy) * k)) for x, y in spec.get("clear_points", [])]
        return _cutout(img, seeds)
    return img.convert("RGBA")


def _to_surface(img: Image.Image) -> cairo.ImageSurface:
    a = np.asarray(img.convert("RGBA")).astype(np.float32)
    alpha = a[..., 3:4] / 255.0
    bgra = np.dstack([a[..., 2:3] * alpha, a[..., 1:2] * alpha, a[..., 0:1] * alpha, a[..., 3:4]])
    w, h = img.size
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, w)
    buf = np.zeros((h, stride), np.uint8)
    buf[:, :w * 4] = np.round(bgra).astype(np.uint8).reshape(h, w * 4)
    tmp = cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, w, h, stride)
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)     # owns its pixels (no numpy buffer lifetime issues)
    c = cairo.Context(out)
    c.set_source_surface(tmp, 0, 0)
    c.paint()
    out.flush()
    return out


@lru_cache(maxsize=8)
def load_character_art(char_id: str) -> Optional[CharacterArt]:
    """The character's raster art prepared for compositing, or None (use the vector rig)."""
    spec = load_character(char_id).spec.get("thumbnail")
    if not spec:
        return None
    src = PROJECT_ROOT / spec["image"]
    if not src.exists():
        log.warning("character %s: thumbnail art %s not found; using the vector character", char_id, src)
        return None
    st = src.stat()
    key = hashlib.sha1(json.dumps([_VERSION, spec, st.st_size, int(st.st_mtime)], sort_keys=True).encode()).hexdigest()[:16]
    cached = CACHE_DIR / f"{char_id}_{key}.png"
    try:
        if cached.exists():
            img = Image.open(cached)
            img.load()
        else:
            img = _process(spec, src)
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            img.save(cached)
    except (OSError, ValueError) as exc:
        log.warning("character %s: could not prepare %s (%s); using the vector character", char_id, src, exc)
        return None
    return CharacterArt(_to_surface(img), spec.get("mode", "cutout"))


def draw_character_art(ctx: cairo.Context, art: CharacterArt, x: float, ground: float, height: float,
                       unit: float = 1.0, tilt: float = -4.0) -> None:
    """Draw the art standing on (x, ground) with the given height (a card is framed and tilted)."""
    surf = art.surface
    s = height / surf.get_height()
    w = surf.get_width() * s
    ctx.save()
    ctx.translate(x, ground - height / 2)
    if art.mode == "card":
        ctx.rotate(math.radians(tilt))
        pad, r = 12 * unit, 28 * unit
        rounded_rect(ctx, -w / 2 - pad + 10 * unit, -height / 2 - pad + 14 * unit, w + 2 * pad, height + 2 * pad, r)
        ctx.set_source_rgba(*PALETTE["ink"], 0.3)          # drop shadow
        ctx.fill()
        rounded_rect(ctx, -w / 2 - pad, -height / 2 - pad, w + 2 * pad, height + 2 * pad, r)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill_preserve()
        ctx.set_source_rgb(*PALETTE["ink"])
        ctx.set_line_width(6 * unit)
        ctx.stroke()
        rounded_rect(ctx, -w / 2, -height / 2, w, height, r * 0.6)
        ctx.clip()
    ctx.translate(-w / 2, -height / 2)
    ctx.scale(s, s)
    ctx.set_source_surface(surf, 0, 0)
    ctx.get_source().set_filter(cairo.FILTER_GOOD)
    ctx.paint()
    ctx.restore()
