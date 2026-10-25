# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Curious Minds: a Python pipeline that turns one topic into a narrated, animated cartoon/doodle explainer. It writes a 9:16 Short (1080x1920) and a 16:9 YouTube video (1920x1080), plus SRT files, thumbnails, metadata, per-video quality reports and a `production_report.json`. Rendering is pure Cairo vector drawing piped to FFmpeg. Narration defaults to local Kokoro-82M TTS (Piper, ElevenLabs and OpenAI are alternative providers). Music and SFX are generated procedurally. No paid service is required. Claude (`LLM_API_KEY`) is optional and only writes scripts/metadata. `docs/QUALITY_UPGRADE.md` explains the voice / visuals / storytelling design and why it is built this way.

## Commands

System deps: `ffmpeg`/`ffprobe` on PATH, plus Cairo (pycairo) and fontconfig. CI runs Python 3.11 on Ubuntu. The checked-in `.venv` is a Linux venv. On this Windows machine use `.venv-win/Scripts/python.exe` (a uv-managed Python 3.11; `.venv-win/` is gitignored). FFmpeg comes from winget and is already on PATH. Always `export PYTHONUTF8=1` first (required on Windows; the code reads text without explicit encodings in places). Helper scripts in `scripts/` need `PYTHONPATH=.`.

```bash
pip install -r requirements.txt

# Full episode (the reference/acceptance topic uses the curated content pack)
python -m src.main generate --topic "Why Do We Dream?" --niche psychology
#   flags: --no-short / --no-long, --short-duration 25-90 (s; accepted within ±20 % of it), --long-duration 6-10 (min),
#          --voice, --subtitles true|false, --thumbnail, --script-source auto|llm|curated|offline, --config my.yaml

# Tools
python -m src.main voice preview [--extra am_fenrir en_US-joe-medium]   # compare voices with QC scores
python -m src.main research --topic "..." --out research.json
python -m src.main qc --video generated/<slug>/curious_minds_shorts_9x16.mp4 --profile vertical
python -m src.main assets index                 # rebuild assets/manifest.json after adding/editing SVGs
python -m src.main assets search --query "heart blood"
python -m src.main analytics import --platform youtube --csv file.csv
python -m src.main analytics report
python -m src.main topics suggest --n 6

# Tests
python -m pytest                                # full suite, includes a real mini render (integration marker)
python -m pytest -m "not integration"           # fast unit tests (what CI runs before generating)
python -m pytest tests/test_content.py::test_name
```

Visual QA scripts are in `scripts/`: `storyboard_preview.py --script content_packs/<slug>/script_short.json` renders a contact sheet of a storyboard without TTS or encoding (the fastest way to check layouts), plus `preview_assets.py`, `character_sheet.py`, `layout_gallery.py`. `annotate_assets.py` fills the required SVG metadata (`data-subcategory`, `data-style`, `data-animations`); `tests/test_quality_upgrade.py` fails if any asset lacks it.

## Architecture

`src/pipeline.py` (`Pipeline.run`) runs the stages: research → script + fact-check → storyboard → narration fitted to duration → narration QC + preview WAV → storytelling/visual review → render → technical QC → metadata + thumbnails → `review/quality_report_<fmt>.md` → manifest. Each stage is wrapped by `_run`, which records its status in `production_report.json`. Each format (short, long) is produced independently in `_produce`, so a failure in one does not hide the other. The run is `success` only if every requested video rendered **and** passed technical QC, the hard narration checks, and (when `content.block_on_review_fail`) the review's `fail`-level checks. Failure reasons are listed in `outputs[fmt].failed_checks`. Never weaken this rule. CI fails the job based on it.

Key cross-cutting concepts:

- **Settings** (`src/config/settings.py`): typed Pydantic settings. Load order: `config/default.yaml` → `--config` YAML → env vars `CM__SECTION__KEY=value` (values parsed as YAML scalars). Relative paths resolve against the project root. Secrets (`LLM_API_KEY`/`ANTHROPIC_API_KEY`, `RESEARCH_API_KEY`, `TTS_API_KEY`) come from the environment only and are redacted in logs.
- **`import src` bootstraps fontconfig** (`src/__init__.py` → `utils/fonts.py`) so Cairo finds the bundled fonts. Entry points and `tests/conftest.py` must import `src` before any Cairo use.
- **Data contracts** (`src/content/models.py`): `ResearchPack`, `Script`, `Storyboard`, `Scene`, etc. Validators enforce the closed vocabulary in **`src/animation/registry.py`** (layouts, backgrounds, transitions, camera moves, doodles, SFX, text length limits). Validators also check that every asset id exists in the `AssetManager`. A new layout, background or transition must be added to `registry.py` **and** implemented in its engine (`scene_engine.py` `_layout_*`, `backgrounds.py`, `transition_engine.py`). LLM output is only ever JSON validated against these models. Generated code is never executed.
- **Script sources** (`src/content/script_generator.py`): `auto` picks `curated` if `content_packs/<slug>/script_<short|long>.json` exists, else `llm` if a key is set, else `offline` (a story-arc template built from research facts). LLM scripts must pass the fact-check *and* the storytelling review; failures are fed back for up to 3 attempts. Curated packs exist for "Why Do We Dream?", the three niche samples (overthinking, heart, sky) and the Phase 1 acceptance Short "Why Water Is the Weirdest Substance on Earth" (short only). The research is re-run on every build, and narration numbers must appear in it. Script generation refuses to run when research is `unavailable`, unless the source is curated or `content.allow_unresearched` is set. `research/fact_checker.py` requires every number in a script to appear in the sources. It also rejects medical-advice phrasing.
- **Story → theme → visuals** (`src/content/story_engine.py`, `src/animation/themes.py`, `src/content/visual_selector.py`): each beat gets a story `role` (curated/LLM-supplied or inferred). The role maps to a scene `purpose`, which picks the niche theme's environment, camera move and narrator delivery. `VisualSelector` scores assets through a concept ontology (`CONCEPTS`) and picks a `demonstration` when narration describes a known mechanism. Adding a concept, theme or demo means editing these tables, not the generator logic.
- **Hosts (characters)**: each niche theme names a `mascot` (`human_body`, `science`, `psychology`; rigs in `assets/characters/<id>/` built on Milo's skeleton via `"base": "milo"`, source art in `characters/`). `themes.resolve_mascot` picks it (`mixed` → best-matching niche, no match → `science`, like the theme; Milo is only used when forced); `brand.mascot` forces one (`auto` by default). `StoryboardGenerator.build` stamps it on the storyboard and every scene; `compose_scene` uses `scene.character.character` unless given `char_id`. Thumbnails draw the raster art (`src/animation/character_art.py`, `thumbnail` block in `character.json`; cutouts flood-fill the white background, `clear_points` seed enclosed pockets) and fall back to the rig. Check a rig with `scripts/character_sheet.py --char <id>`.
- **Demonstrations** (`src/animation/demos.py`): staged animated diagrams. Subclasses implement `content(ctx, t)`; the base `Demo.draw` adds the diagram card. Stages start on the scene's `demo.stage_cues` words. `focus(t)` drives the `focus`/`follow` camera and `label_points` anchor the callouts. Register new kinds in `DEMO_CLASSES` and `STAGE_COUNT` (the registry imports `DEMO_KINDS`).
- **Narration** (`src/audio/tts_engine.py`, `narration_director.py`): synthesis is per sentence, each with a `Delivery` (intent → tempo, pauses, emphasis). Sentences are loudness-normalised on speech frames and trimmed with long tails and fades. Renders are cached in `generated/.cache/tts` keyed by text and parameters. Providers never fall back silently (`tts.fallback_provider`). `--voice` goes through `resolve_voice` (profile label/key, Kokoro voice/blend or Piper id).
- **Reviews**: `src/audio/audio_qc.py` (signal metrics plus an optional faster-whisper WER) and `src/content/retention_review.py` (hook, curiosity gap, mini-hooks, repetition, asset relevance, niche identity, pacing) are heuristic gates. Neither claims to predict real retention.
- **Duration is driven by measured audio.** `Pipeline.narrate` synthesizes narration per scene and computes the timeline with `rendering/renderer.py::plan_timeline` (lead-in + audio + tail, snapped to whole frames). It then re-synthesizes with an adjusted Piper `length_scale` (bounded by `tts.speed_fit_range`) until the total lands in the target range. Scene durations are never authored by hand.
- **Rendering** (`rendering/renderer.py`, with thin `vertical_renderer.py`/`horizontal_renderer.py` subclasses that pick a profile): scenes render in a multiprocessing pool. Each worker composes Cairo frames (`animation/scene_engine.compose_scene`) and pipes raw BGRA to a libx264 segment. Transitions are split into cover/reveal halves so each scene stays independent and deterministic. Segments are stream-copy concatenated. Audio is mixed (narration + ducked music + SFX), passed through two-pass loudnorm to -14 LUFS, and muxed. Captions are burned in (`subtitle_engine.py`). Layouts must keep content inside each profile's `safe` area and out of the caption band (`caption_zone_y`).
- **Animation stack** (`src/animation/`): `svg_loader.py` (an in-house SVG → Cairo display-list parser; it reduces gradients to their first stop), `asset_manager.py` (scans `assets/<category>/*.svg`; `manifest.json` is a generated index), `character_rig.py` + `assets/characters/poses.json` (2-bone IK rig), `expression_engine.py` + `assets/expressions/expressions.json` (faces, lip sync driven by the loudness envelope), `character_engine.py` (actions), `doodle_engine.py` (draw-on strokes, charts, particles), `palette.py` (the locked brand palette).
- **Lively style + script mode** (`src/lively/`, `src/script_mode/`): `python -m src.main render-script --script scripts/x.yaml [--style classic]` renders a user-written script (schema with per-scene error messages in `script_mode/schema.py`; defaults in `builder.py`). Lively storyboards (`Storyboard.style == "lively"`) are composed by `lively/composer.compose_lively`: the `spotlight` layout for script mode, `enhance_classic` around classic layouts for `generate --style lively`. Camera, beats (a new visual event every ≤1.8 s), 0.26 s transitions, captions, boil and the paper background are separate modules. Colours/fonts/timings live in `config/style.yaml`. Caption word times are aligned with faster-whisper (`audio/word_aligner.py`, `tts.word_alignment`). Topic mode still defaults to classic. `scripts/motion_report.py` measures pixel change per second of a rendered video.
- **Whiteboard look** (script mode's default, `--style whiteboard`; storyboards keep `style == "lively"` with `layout == "whiteboard"`): `lively/whiteboard.py::compose_whiteboard` queues pen drawings (`lively/drawing.py`: `DrawnSvg` traces an SVG in `stroke_order`, big shapes first, with `outline_asset` adding ink outlines to fill-only shapes; `HandText` handwriting; `PenPath` beats) and a `DrawingHand` (`assets/hands/marker_hand.svg`) follows `pen(t)`. Host actions `draw` (IK on the pen via `CharacterCue.target_fn`, `hand_marker.svg`), `count` (`hand_one/two/three.svg`) and `hold_up` (`CharacterAnimator.prop`) live in `character_engine.py`. `builder.whiteboard_action` picks the action from the text. Calm camera and drawing timings are under `whiteboard:` in `config/style.yaml`. `scripts/audit_assets.py` writes `docs/ASSET_AUDIT.md`. On Windows, Cairo resolves fonts through DirectWrite (not fontconfig): run `scripts/install_fonts_windows.py` once, or text falls back to Arial.
- **QC** (`rendering/quality_control.py`): ffprobe checks for streams, resolution, fps, duration range, A/V sync, blank/frozen frames, loudness and the SRT.

## Conventions

- New SVG assets must follow `docs/BRAND_GUIDE.md`: palette colours only, ink outlines, round caps, stroke widths on a 400×400 viewBox, no gradients. Run `python -m src.main assets index` after adding them.
- Use only voices with commercially usable licences. The default is Kokoro `am_michael` (Apache-2.0). Piper `ryan`/`hfc_male` are deliberately excluded (CC BY-NC-SA). Voice profiles (friendly / energetic / documentary) live in `config/default.yaml` under `tts.profiles`, and their `words_per_second` drives script length targets. Re-measure with `voice preview` if you change a profile.
- Research (`src/research/researcher.py`) searches Wikipedia with the natural question, the keywords and `RELATED` concept expansions, and drops pages whose short description marks them as media or organisations (`OFF_TOPIC_DESC`). Wikipedia rate-limits bursts, and `_get_json` backs off on HTTP 429.
- LLM prompt templates are in `prompts/`. The model and effort level are set in `config/default.yaml` under `llm`.
- `generated/` holds the outputs and is gitignored. The `work/` dir inside each episode is deleted at the end of the run.
- Integration tests use the `small_settings` fixture (tiny render profiles, `ultrafast` preset) to keep real renders quick.
- GitHub Actions (`.github/workflows/generate-video.yml`) passes workflow inputs through env vars. Never interpolate them directly into shell commands.
