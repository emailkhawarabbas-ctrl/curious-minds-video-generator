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

## 4. Hosts — one character per niche, Milo as the fallback
Each niche has its own host, drawn from the source art in `characters/` and rebuilt as a vector
rig on Milo's skeleton (same proportions, poses, hands, lip sync and expressions):

| Niche | Host (`assets/characters/<id>`) | Look | Source art |
|---|---|---|---|
| Human Body | `human_body` — Body Explorer | kid in a see-through sky-blue anatomy suit (lungs, heart, stomach, intestines, vessels) | `characters/human_body.png` |
| Science | `science` — Professor Flask | corked round-bottom flask head with bubbling teal liquid and red / green coils, white lab coat, metal limbs | `characters/science.jpg` |
| Psychology | `psychology` — Brainy | two-tone brain head (wired purple half, pink folded half), sky-blue lab coat with emotion pins | `characters/psychology.jpg` |

The host is chosen by `themes.resolve_mascot` (niche → host; `mixed` → best-matching niche;
no match → Milo). `brand.mascot` in the config forces one host (`auto` = per niche). Thumbnails
show the original raster art (`character.json` → `thumbnail`), since nothing moves there.

### Milo (fallback host)
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

## 7. Niche visual identities (`src/animation/themes.py`)
The palette, line language and typography never change. What changes per niche is the host
(section 4) and the *world around it* — environments, illustration subjects, diagram language, accents, particles,
transitions, camera temperament and music:

| | Human Body | Science | Psychology |
|---|---|---|---|
| Look | Professional medical cartoon | Exploration & discovery | Mind & behaviour storytelling |
| Environments | `bloodstream`, `body_lab` (live ECG), `anatomy_blueprint`, `cell_world` | `sky_day`, `science_grid`, `atmosphere_view`, `sunset_sky`, `underwater`, `space`, `lab` | `mind_maze`, `thought_room`, `emotion_waves`, `brain_space`, `city` |
| Illustrations | Organs, cutaways, blood cells, vessels, medical tools | Light, atmosphere, molecules, planets, instruments | Heads & people, thought loops, emotions, decisions, conversations |
| Demonstrations | heart pump, circulation loop, ECG heartbeat | light scattering, wavelengths, sunset path, water molecule, hydrogen bonds, ice lattice, frozen lake | thought loop, decision tree, stress alarm, neural signal |
| Accents | coral · teal · blue · pink | blue · orange · teal · purple | purple · pink · teal · orange |
| Foreground depth | soft out-of-focus blood cells | floating light motes | slow thought rings |
| Transitions | circle wipe, blinds, slide, dots | star zoom, slide, circle wipe, doodle swipe | doodle swipe, dots, circle wipe, blinds |
| Music mood | curious | upbeat | calm |

Rules:
* Choose illustrations that **depict the sentence being spoken** (the visual selector enforces
  this); generic stars / planets / rockets are fillers and are only allowed when the narration is
  about them.
* Every mechanism or process gets a **demonstration** on a diagram card: cream card, 34 px radius,
  7 px ink outline, soft ink drop shadow, contents clipped to the card, stages revealed on the
  narration's cue words, leader-line callouts that follow the stages.
* Colour conventions inside diagrams: oxygen-rich blood red / oxygen-poor blue (and say it is a
  colour code); blue light = `blue`, red light = `red`; worry = `lavender` loops; decisions = `green`
  for the chosen path.
* New SVGs carry full metadata on the root: `data-title`, `data-tags` (6–12 keywords),
  `data-subcategory`, `data-style` (`medical_cartoon` · `science_explorer` · `mind_storybook` ·
  `everyday_doodle`), `data-animations` (e.g. `draw,beat,pulse,highlight`). Run
  `python scripts/annotate_assets.py` then `python -m src.main assets index`.

## 8. Character direction
* Milo participates: he looks at and points to the active part of a diagram when it is named,
  thinks on questions, reacts to surprises (short reaction, then back to talking), explains with
  gestures, and waves at the end. Cues fire on the spoken word, not on a fixed fraction.
* Close-ups (`character_closeup`, waist-up) are for relatable moments and direct questions —
  at most 2 per short.
* In demonstrations Milo stands small in a corner so the diagram owns the frame; in full
  illustrations he sometimes leaves the frame entirely.
