# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CURIOUS MINDS: a topic-in, videos-out pipeline. Given one topic it researches real sources, writes a script, builds storyboards, animates the mascot Milo with Cairo-drawn doodles, narrates with local Piper TTS, and renders a 9:16 Short and a 16:9 YouTube video, plus captions, thumbnails, metadata and QC. No paid service is required. `LLM_API_KEY` (Anthropic) is optional.

## Commands

System deps: `ffmpeg`, `ffprobe`, Cairo (`libcairo2-dev`), fontconfig. The project was developed on Ubuntu with Python 3.10, and CI runs on `ubuntu-latest`.

```bash
pip install -r requirements.txt          # inside .venv
cp .env.example .env                     # all keys optional

python -m src.main generate --topic "Why Do We Dream?" --niche psychology   # reference episode (curated pack)
python -m src.main generate --topic "..." --niche science --no-long --short-duration 60
python -m src.main generate --topic "..." --script-source llm|curated|offline|auto

python -m src.main research --topic "..." --out research.json
python -m src.main qc --video generated/<slug>/curious_minds_shorts_9x16.mp4 --profile vertical
python -m src.main assets index          # rebuild assets/manifest.json after adding SVGs
python -m src.main assets search --query "heart blood"
python -m src.main topics suggest --n 6
python -m src.main analytics import|report ...

python -m pytest                          # full suite, including a real mini render and TTS
python -m pytest -m "not integration"     # fast unit tests (what CI runs before generating)
python -m pytest tests/test_content.py::test_name   # single test
```

The Piper voice model downloads into `models/piper/` on first use. Visual QA helpers live in `scripts/` (`preview_assets.py`, `character_sheet.py`, `layout_gallery.py`).

## Architecture

`src/main.py` is the CLI. `src/pipeline.py` (`Pipeline.run`) orchestrates the stages. Each stage goes through `_run`, which records timing and status into `production_report.json`. Research runs once per topic. Then `_produce` runs once per format (short → `VerticalRenderer`, long → `HorizontalRenderer`), and one format failing does not abort the other:

1. **research** (`src/research/`): keyless providers (Wikipedia, MedlinePlus, PubMed), plus Tavily when `RESEARCH_API_KEY` is set. Failures are recorded verbatim. With no sources, script generation stops (`content.allow_unresearched: false`).
2. **script** (`src/content/script_generator.py`): `resolve_source` with `auto` picks the curated pack in `content_packs/<slug>/` if one exists, then the LLM if a key is set, then the offline template. The LLM path returns schema-constrained JSON that is validated by Pydantic (`content/models.py`), with a fact-check repair loop. `research/fact_checker.py` requires every number in the script to appear in the source texts and rejects medical-advice phrasing. A failed fact-check fails that format.
3. **storyboard** (`storyboard_generator.py`): builds a separate storyboard per orientation, then validates and repairs it.
4. **narration** (`Pipeline.narrate`, `audio/tts_engine.py`): per-sentence Piper synthesis gives measured durations. `length_scale` is adjusted iteratively so the total fits the target duration range, and scene durations are then derived from the audio (`plan_timeline`).
5. **render** (`src/rendering/`): scenes are rendered independently in parallel (Cairo → raw BGRA frames → libx264 segments). Transitions are rendered as cover/reveal halves so scenes stay independent. Segments are concatenated, mixed (voice + ducked procedural music + SFX), and loudness-normalised in two passes to -14 LUFS.
6. **qc** (`rendering/quality_control.py`): checks streams, size, fps, duration, A/V sync, blank/frozen frames, loudness and SRT. A run only counts as success when every requested video exists and passes QC.
7. **metadata / thumbnails**: non-critical stages (`critical=False`).

Key invariants:
- **`src/animation/registry.py` is the closed vocabulary** (layouts, backgrounds, actions, expressions, etc.) for every storyboard, whether hand-written, rule-based or LLM-made. Validators in `content/models.py` enforce it. The LLM never produces executable code. To add a new layout or effect, register it here and implement it in `scene_engine.py` / `doodle_engine.py`, with both vertical and horizontal compositions inside the safe area and clear of the caption band.
- Assets are hand-authored SVGs parsed by the in-house `svg_loader.py`; there is no external SVG renderer. New SVGs go in `assets/<category>/` following `docs/BRAND_GUIDE.md`, and then you re-run `assets index`.
- Milo is a 2-bone hierarchical rig (`character_rig.py`, poses in `assets/characters/poses.json`, expressions in `assets/expressions/expressions.json`). Lip sync is driven by the loudness envelope, not by visemes.
- Music and SFX are synthesised procedurally with numpy. Voices must be commercially licensed: Piper `ryan` and `hfc_male` are CC BY-NC-SA and deliberately excluded.

## Configuration

`config/default.yaml` is loaded by `src/config/settings.py` (Pydantic). Override it with `--config file.yaml` or env vars `CM__SECTION__KEY=value` (e.g. `CM__RENDER__WORKERS=4`). Secrets come only from env (`LLM_API_KEY`, `RESEARCH_API_KEY`, `TTS_API_KEY`) and are redacted from logs. LLM prompt templates are in `prompts/`, and pronunciation fixes are in `config/pronunciations.yaml`.

Output goes to `generated/<slug>/` and is gitignored. Look there for `production_report.json` and `logs/generation.log` when debugging a run.

## Tests

`tests/conftest.py` provides settings with tiny render profiles. Tests marked `@pytest.mark.integration` render real video and use the TTS model, so they need ffmpeg and the voice model. The LLM path is only tested against a mocked client.

## CI

`.github/workflows/generate-video.yml` is triggered manually (`workflow_dispatch`). Inputs reach the job through env vars and are never interpolated into shell code; keep it that way. The job runs the unit tests, generates the videos, uploads `generated/<slug>/` as an artifact, and fails if any requested video fails QC.
