# Curious Minds — Brand & Asset Style Guide

Brand: **CURIOUS MINDS** — *Understand the world in a fun way.*

Visual identity: colorful 2D cartoon + modern doodle animation, friendly, clean, professional.

## 1. Palette (locked — `src/animation/palette.py`)

| Token | Hex | Use |
|---|---|---|
| ink | `#2B2D42` | **All outlines**, text strokes |
| cream / paper | `#FFF8E7` / `#FDF6E3` | Light backgrounds |
| teal / teal_dark / teal_light | `#2EC4B6` / `#1A9E92` / `#9BE7DF` | Brand primary (Milo's jacket) |
| orange / orange_dark | `#FF9F1C` / `#E07B00` | Brand secondary (backpack, CTA) |
| yellow / yellow_light | `#FFD23F` / `#FFE98A` | Highlights, stars, energy |
| coral / red | `#FF5D73` / `#EF476F` | Alerts, hearts, emphasis |
| pink / pink_light | `#FF8FAB` / `#FFD6E0` | Organs, brain |
| purple / purple_dark / lavender | `#8E7DFF` / `#5B4BC4` / `#CFC6FF` | Psychology, dreams, night |
| blue / sky / sky_light | `#3A86FF` / `#8ECAE6` / `#D7F0FA` | Science, water, sky |
| green / leaf | `#06D6A0` / `#7BD389` | Nature, success |
| night / midnight | `#1B1F3B` / `#2A2E5C` | Night & space backgrounds |
| skin / skin_shadow | `#F8C9A0` / `#E9A97F` | Characters |
| hair / navy / grey | `#5B3A29` / `#3D405B` / `#B8BCC8` | Details |
| white | `#FFFFFF` | Highlights, eyes |

## 2. Line & shape language
* Every filled shape has an **ink outline**. On a 400×400 viewBox: main silhouette `stroke-width="8"`, inner details `5–6`, tiny details `4`.
* `stroke-linecap="round"` and `stroke-linejoin="round"` everywhere (the loader defaults to round).
* Flat fills from the palette. Add depth with **one darker shade shape** (e.g. teal_dark) on the bottom/right and **one white highlight stroke or shape** (`stroke-opacity`/`fill-opacity` 0.5–0.75) top-left.
* Soft rounded, slightly chunky proportions; no sharp thin spikes; no photorealism; no gradients (gradients are reduced to their first stop).
* Optional soft ground shadow: `<ellipse … fill="#2B2D42" fill-opacity="0.12"/>` below the object.
* Friendly but not childish. Faces on objects only where the design calls for it (e.g. sleepy moon).

## 3. SVG authoring rules (for `src/animation/svg_loader.py`)
* Root: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" data-title="Human Title" data-tags="comma,separated,keywords">`.
  Use a different viewBox only for strongly non-square objects (e.g. `0 0 600 300` for a bed).
* Supported elements: `g, path, circle, ellipse, rect (rx/ry), line, polyline, polygon`.
* Path commands: `M L H V C S Q T A Z` (absolute and relative). Transforms: `translate, scale, rotate, skewX, skewY, matrix`.
* Attributes: `fill, stroke, stroke-width, opacity, fill-opacity, stroke-opacity, stroke-linecap, stroke-linejoin, fill-rule`, also via `style=""`.
* **Not supported**: `<text>`, `<image>`, `<use>`, filters, masks, clip paths, CSS classes, gradients (approximated). Never put text in assets — labels are drawn by the doodle engine.
* Draw order = document order (back to front). The draw-on animation also traces outlines in document order, so list the main silhouette first and details after.
* **Parts**: wrap meaningful parts in `<g id="part-NAME">` so they can be highlighted individually.
* **Anchors**: add invisible anchor points as `<circle id="anchor-NAME" cx=".." cy=".." r="4"/>`. Every asset needs `anchor-center` and `anchor-top`, plus 2–4 anchors on meaningful parts (used for labels and arrows).
* `data-tags`: 6–12 lowercase keywords used by the automatic visual planner (synonyms, topic words).
* Keep files small (< 12 KB) and hand-readable.

## 4. Mascot — Milo
See `assets/characters/milo/character.json` for the locked specification (proportions,
colours, outfit). Milo always wears: teal explorer jacket with rolled sleeves, yellow
shirt with the "?" badge, navy cargo trousers, red sneakers, orange backpack, and amber
goggles on his forehead over brown swoosh hair. Big expressive eyes, thick brows.

## 5. Typography
* Titles & thumbnails: **Luckiest Guy** (Apache-2.0)
* Captions, labels, UI: **Lilita One** (OFL-1.1)
* Hand-written notes: **Patrick Hand** (OFL-1.1)

## 6. Motion language
* Entrances use `out_back` / `out_elastic` pops (overshoot ≈ 10–15 %), exits use `in_back`.
* Doodles are *drawn on* (stroke reveal) then fills fade in.
* Idle life everywhere: breathing, blinking, gentle floating (±2–4 % of size).
* Transitions are colourful cover/reveal wipes in brand colours (0.35–0.5 s).
