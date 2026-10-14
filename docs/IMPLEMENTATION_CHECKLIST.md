# Curious Minds — Implementation Checklist

Repository inspection (2026-10-14): the project directory was empty (no existing code,
workflows or assets to preserve). Host: Ubuntu 22.04, Python 3.10, FFmpeg 4.4, 8 cores,
16 GB RAM, system pycairo 1.20 (no Python headers, so the local venv uses
`--system-site-packages`; CI builds pycairo from PyPI).

Key technical decisions

| Area | Decision | Why |
|---|---|---|
| Vector rendering | pycairo, drawing directly to frames; raw BGRA frames piped to FFmpeg | Fast, true vector quality, no browser / LaTeX dependency |
| Assets | Hand-authored SVG files parsed by an in-house SVG loader (`svg_loader.py`) into Cairo display lists | Editable vector assets + per-path "draw-on" doodle effects |
| Character | Hierarchical 2-bone rig (torso, head, 2×arm, 2×leg) + SVG parts (head, hair, torso, hands, shoes, backpack) + parametric face | Real joint animation, IK pointing, lip sync, consistent design |
| Diagrams | Own Cairo doodle/diagram engine instead of Manim | Manim needs LaTeX/heavy deps and would not share the doodle style; documented in Known limitations |
| TTS | Piper (local, free). Default voice `en_US-joe-medium` (CC0 dataset) | ryan/hfc_male voices are CC BY-NC-SA (non-commercial) — unsuitable for a monetised channel |
| Music / SFX | Procedurally synthesised in-house (numpy) | Zero licensing risk |
| Fonts | Luckiest Guy (Apache-2.0), Lilita One (OFL), Patrick Hand (OFL) | Bundled with licences |
| LLM | Anthropic `claude-opus-5-5`, structured JSON output validated with Pydantic, server-side refusal fallback | Optional — curated + offline paths work without keys |
| Research | Wikipedia, MedlinePlus (NLM), PubMed (NCBI E-utilities) — keyless; optional Tavily web search restricted to authoritative domains | Real URLs, never fabricated |

## Phase 1 — Foundation
- [x] Directory structure, `requirements.txt`, `.gitignore`, `.env.example`
- [x] `config/default.yaml` + `src/config/settings.py` (Pydantic, env overrides)
- [x] Logging with secret redaction
- [x] Project-local fontconfig bootstrap
- [x] FFmpeg / FFprobe helpers
- [x] Config tests

## Phase 2 — Brand & character
- [x] Brand palette, stroke & shape language (`docs/BRAND_GUIDE.md`)
- [x] SVG loader (path/circle/ellipse/rect/polygon/line/groups/transforms/arcs, anchors)
- [x] Mascot "Milo" SVG parts + character spec JSON
- [x] Rig: joints, poses library (JSON), 2-bone IK
- [x] Expression engine (eyes, pupils, lids, blink, brows, mouth shapes, lip sync)
- [x] Character engine actions: idle, talk, walk, run, point, think, explain, wave, surprised, happy, sad, excited, hold, look-at, interact
- [x] Supporting character(s) via the same rig with a different style
- [x] Character consistency tests + pose sheet render

## Phase 3 — Doodle & animation
- [x] Easing library (ease, back, elastic, bounce)
- [x] Doodle primitives: draw-on strokes, arrows, circles/highlights, stars, sparkles, speech/thought bubbles, labels, particles, pathways with pulses, morphing, wobble
- [x] Asset library (human body, psychology, science, general objects) + manifest + licence record
- [x] Procedural backgrounds
- [x] Scene templates (≥12) with vertical & horizontal layouts, safe areas
- [x] Camera moves & transitions

## Phase 4 — Content intelligence
- [x] Pydantic models: research, script, storyboard, scene
- [x] Research providers + source manager + fact checker
- [x] LLM client (Anthropic) + prompts
- [x] Script generator: LLM / curated content pack / offline template
- [x] Storyboard generator (separate vertical & horizontal) + validation + repair
- [x] SEO / metadata generator, topic generator

## Phase 5 — Audio
- [x] Provider-independent TTS interface, Piper provider, pronunciation dictionary
- [x] Per-sentence synthesis → exact sentence timing, phoneme-weighted word timing
- [x] Duration fitting (speed adjustment) against target range
- [x] SFX library, music generator, mixer with ducking, loudness normalisation

## Phase 6 — Rendering
- [x] Parallel scene renderer → FFmpeg segments → concat → mux
- [x] Vertical (1080×1920) and horizontal (1920×1080) profiles, 30 fps, H.264/AAC, BT.709
- [x] SRT + burned-in captions in safe areas
- [x] Thumbnails (16:9 + 9:16 cover), metadata, chapters
- [x] Quality control (ffprobe streams, resolution, fps, duration, A/V sync, blank frames, loudness)
- [x] Production manifest / report

## Phase 7 — GitHub Actions
- [x] `generate-video.yml` (workflow_dispatch, inputs, validation, caching, artifacts, timeouts)

## Phase 8 — Analytics
- [x] CSV import (YouTube Studio, TikTok), normalisation
- [x] Performance analyser, weekly report, topic recommendations

## MVP acceptance — "Why Do We Dream?"
- [x] Short (60–90 s, 9:16) and long (6–10 min, 16:9) rendered, inspected, QC-passed
- [x] SRT, thumbnail, scripts, storyboards, research, production report

## Status (2026-10-14)
All phases implemented and tested; see README "Known limitations" for what is
intentionally out of scope (live LLM run not exercised without a key, Manim not used,
loudness-based lip sync, AI image assets).
