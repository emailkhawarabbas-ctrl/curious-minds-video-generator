# CURIOUS MINDS — automated cartoon & doodle educational video generator

*Understand the world in a fun way.*

Give it one topic. It researches the topic from real sources, writes original narration,
builds format-specific storyboards, animates the mascot **Milo** with colourful doodle
illustrations, narrates in a friendly US-English male voice, mixes music and sound
effects, renders a **9:16 TikTok/Shorts video** and a **16:9 YouTube long-form video**,
burns in captions, exports SRT, draws thumbnails, writes titles/descriptions/chapters, runs
automated quality control, and saves everything for manual review.

Runs locally or on GitHub Actions. **No paid service is required.** Claude (via `LLM_API_KEY`)
is optional and used for writing scripts/metadata for new topics.

---

## 1. Quick start (local)

```bash
# system packages (Ubuntu/Debian)
sudo apt-get install -y ffmpeg libcairo2-dev pkg-config fontconfig python3-dev

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional: add LLM_API_KEY / RESEARCH_API_KEY

# the MVP acceptance episode (curated content pack, both formats)
python -m src.main generate --topic "Why Do We Dream?" --niche psychology
```

Output lands in `generated/why_do_we_dream/` (see §5). The Piper voice model (~60 MB) is
downloaded automatically on first use into `models/piper/`.

> If your system cannot build `pycairo` (no Python headers), create the venv with
> `python3 -m venv --system-site-packages .venv` and install `python3-cairo` from apt.

### Exact commands for future videos

```bash
# both formats, default durations (short 75 s, long 8 min)
python -m src.main generate --topic "Why Do We Get Goosebumps?" --niche human_body

# only a Short, 60 s
python -m src.main generate --topic "Why Is the Sky Blue?" --niche science --no-long --short-duration 60

# only a long video, 10 minutes, calmer voice, no burned-in captions
python -m src.main generate --topic "How Does Your Brain Create Memories?" --niche psychology \
    --no-short --long-duration 10 --voice "US English Male (Calm)" --subtitles false

# force the script source: auto | llm | curated | offline
python -m src.main generate --topic "How Do Magnets Work?" --niche science --script-source llm

# tools
python -m src.main research --topic "Why Do We Hiccup?" --out research.json
python -m src.main qc --video generated/why_do_we_dream/curious_minds_shorts_9x16.mp4 --profile vertical
python -m src.main assets index            # rebuild assets/manifest.json
python -m src.main assets search --query "heart blood"
python -m src.main analytics import --platform youtube --csv youtube_export.csv
python -m src.main analytics import --platform tiktok  --csv tiktok_export.csv
python -m src.main analytics report        # weekly report (Markdown + JSON)
python -m src.main topics suggest --n 6    # pillar-balanced, analytics-aware ideas

# tests
python -m pytest                     # full suite incl. real mini render
python -m pytest -m "not integration"   # fast unit tests only
```

## 2. GitHub Actions

Workflow: `.github/workflows/generate-video.yml` → **Actions → Generate Curious Minds video → Run workflow**.

| Input | Values |
|---|---|
| `topic` | required, free text (3–120 chars) |
| `niche` | science / psychology / human_body / mixed |
| `generate_shorts`, `generate_long_video` | true / false |
| `short_duration` | 60–90 s |
| `long_duration` | 6–10 min |
| `voice` | US English Friendly Male (default) / Calm / Narrator |
| `generate_subtitles`, `generate_thumbnail` | true / false |
| `script_source` | auto / llm / curated / offline |

Secrets (all optional): `LLM_API_KEY` (Anthropic, for LLM scripts/metadata),
`RESEARCH_API_KEY` (Tavily web search limited to authoritative domains), `TTS_API_KEY`
(reserved for a paid TTS provider; Piper needs none).

The job: checks out, validates inputs (passed via env vars — no shell interpolation),
installs FFmpeg/Cairo, caches pip and the voice model, runs unit tests, generates, writes a
QC summary to the run page, uploads `generated/<slug>/` as an artifact (14-day retention),
and fails the run if any requested video failed or did not pass QC. Generated media is never
committed (`.gitignore`). Timeout: 120 min (a full short + 8-min long run takes roughly
10–20 min on a 4-vCPU runner).

## 3. How it works

```
topic ─► research (Wikipedia, MedlinePlus/NIH, PubMed, opt. Tavily) ─► facts + sources + statuses
      ─► script  (curated pack │ Claude JSON + Pydantic + fact-check repair loop │ offline template)
      ─► storyboard per orientation (vertical for the short, horizontal for the long)
      ─► validation & repair (vocabulary, assets, text lengths, durations, transitions)
      ─► narration per sentence (Piper) ─► measured durations ─► speed fit into target range
      ─► parallel scene rendering (Cairo vectors → raw frames → libx264 segments)
      ─► concat ─► mix (voice + ducked music + SFX) ─► 2-pass loudnorm (-14 LUFS) ─► MP4
      ─► QC (ffprobe streams, size, fps, duration, A/V sync, blank/frozen frames, loudness, SRT)
      ─► metadata, chapters, thumbnails ─► production_report.json
```

### Project layout

```
src/
  main.py                 CLI            pipeline.py   stage orchestration + manifest
  config/settings.py      typed settings (YAML + CM__ env overrides; secrets from env only)
  research/               researcher.py (providers) · fact_checker.py · source_manager.py
  content/                models.py (Pydantic contracts) · llm_client.py (Claude) ·
                          script_generator.py · storyboard_generator.py · seo_generator.py ·
                          topic_generator.py
  animation/              svg_loader.py · asset_manager.py · palette.py · easing.py ·
                          character_rig.py · expression_engine.py · character_engine.py ·
                          doodle_engine.py · backgrounds.py · scene_engine.py ·
                          transition_engine.py · text_render.py · registry.py (vocabulary)
  audio/                  tts_engine.py · music_engine.py · sound_effects.py · mixer.py
  rendering/              renderer.py · vertical_renderer.py · horizontal_renderer.py ·
                          subtitle_engine.py · thumbnail_engine.py · quality_control.py
  analytics/              csv_importer.py · performance_analyzer.py · weekly_report.py
assets/                   characters/ (milo, zoe, poses.json) · expressions/ · human_body/ ·
                          psychology/ · science/ · objects/ · fonts/ · sound_effects/ · manifest.json
content_packs/<slug>/     curated scripts + metadata (used automatically when present)
prompts/                  LLM prompt templates
config/                   default.yaml · pronunciations.yaml
scripts/                  preview_assets.py · character_sheet.py · layout_gallery.py (visual QA tools)
docs/                     BRAND_GUIDE.md · IMPLEMENTATION_CHECKLIST.md
tests/                    unit + integration tests
```

### Animation system
* **Mascot rig** — Milo is a hierarchical 2-bone rig (torso, neck/head, 2× upper arm/forearm/hand,
  2× thigh/shin/shoe) with SVG parts (head, hair, goggles, torso, backpack, 5 hand shapes, shoes)
  and capsule limbs. 17 poses (`assets/characters/poses.json`), analytic **2-bone IK** for
  pointing/reaching/hand-to-chin, 21 actions (idle, talk, explain, walk, run, point, think, wave,
  surprised, excited, happy, sad, hold, look_at, interact, yawn, shrug, …), walk/run cycles,
  breathing, entrances (pop / walk / run / slide).
* **Faces** — parametric eyes, pupils with highlights, eyelids, natural blinking, eyebrows,
  9 mouth shapes; 16 expressions (`assets/expressions/expressions.json`) with smooth blending;
  **lip sync** from the narration loudness envelope per frame.
* **Doodle engine** — draw-on strokes with hand-drawn "line boil", arrows, circle highlights,
  marker swipes, stars, sparkles, bursts, speech/thought bubbles, labels with leader lines,
  pop text, counters, icon pops (pop/elastic/bounce/draw/spin), morphing shapes, particles
  (burst, confetti, twinkles, zzz, bubbles), pathways with travelling pulses, animated bar/line/
  step charts and brain-wave monitors.
* **Assets** — 72 original SVG illustrations (human body, psychology, science, everyday
  objects) with tags, anchors and highlightable parts; drawn on with a progressive outline
  reveal. 13 procedural backgrounds with ambient animation.
* **Scenes** — 15 layout templates (hook, explainer, object focus, diagram flow, list, comparison,
  thought bubble, fact card, story scene, network, chart, question, timeline, wave monitor, outro),
  each with separate vertical/horizontal composition inside the platform-safe area and out of the
  caption band; reveals are synced to the narration (cue words).
* **Transitions** — circle wipe, doodle swipe, slide, star zoom, dots, blinds, dip — rendered as
  cover/reveal halves so scenes render independently in parallel.

### Safety rules built in
* The LLM only returns JSON that is validated against a closed schema and Pydantic models; **no
  generated code is ever executed**. Storyboards may only use names from `src/animation/registry.py`.
* Research failures are recorded verbatim; nothing is invented. If no source is found, script
  generation stops (`content.allow_unresearched: false`).
* Fact-check: every number in a script must appear in the retrieved sources; medical-advice
  phrasing fails the check; hypotheses must be hedged (warning).
* Secrets only come from env/GitHub Secrets and are redacted from logs.
* Success is only reported when every requested video exists and passes QC.

## 4. Configuration

`config/default.yaml` (override with `--config my.yaml` or env `CM__SECTION__KEY=value`):
voice and pace (`tts.voice`, `tts.length_scale`), duration ranges, render profiles (resolution,
fps, safe areas, caption position), CRF/preset/workers, loudness target (-14 LUFS), music and SFX
levels, research providers, LLM model (`claude-opus-5-5`, effort, refusal fallback).
Pronunciation fixes: `config/pronunciations.yaml`.

Voices (Piper, local): default **`en_US-joe-medium`** ("US English Friendly Male", CC0
dataset). Alternatives: `en_US-norman-medium`, `en_US-john-medium` (public-domain datasets).
Popular voices `ryan` and `hfc_male` are **CC BY-NC-SA (non-commercial)** and deliberately not used.

## 5. Output of one episode

```
generated/why_do_we_dream/
  curious_minds_shorts_9x16.mp4       1080x1920, 30 fps, H.264 + AAC
  curious_minds_youtube_16x9.mp4      1920x1080, 30 fps, H.264 + AAC
  production_report.json              config, stages, QC, outputs, licences, file list
  sources.json                        all sources with tier, provider, date, URL
  research/   research.json (facts + statuses), source_texts.json, fact_check_*.json
  scripts/    script_short.json/.txt, script_long.json/.txt
  storyboards/ storyboard_vertical.json, storyboard_horizontal.json
  audio/      per-scene narration WAVs + timing (sentences, words, lip-sync envelope)
  subtitles/  *.srt
  thumbnails/ 2 concepts × (16:9 + 9:16) JPG
  metadata/   3 titles, description (+chapters, sources, hashtags), keywords, thumbnail concepts
  assets/     SVGs used + asset_licenses.json
  logs/       generation.log
```

## 6. External dependencies & licences

| Dependency | Use | Licence |
|---|---|---|
| FFmpeg / FFprobe | encoding, muxing, loudness, probing | LGPL/GPL |
| Cairo / pycairo | vector rendering | LGPL / LGPL-MPL |
| Piper TTS (`piper-tts`, onnxruntime) | narration | GPL-3.0 (engine) |
| Voice `en_US-joe-medium` | default narrator | dataset CC0 |
| numpy, Pydantic, PyYAML, requests, Pillow, python-dotenv | core | BSD/MIT/HPND |
| anthropic (optional) | Claude API client | MIT |
| Luckiest Guy · Lilita One · Patrick Hand fonts | typography | Apache-2.0 · OFL-1.1 · OFL-1.1 |
| Wikipedia, MedlinePlus (NLM), PubMed E-utilities (NCBI) | research APIs | public APIs; content cited by URL |
| Music, sound effects, SVG art, mascot | created in this project (procedural / hand-authored) | original |

## 7. Known limitations

* **Script quality without an LLM**: curated content packs give production quality; the offline
  template only rephrases extracted research sentences (accurate but plain, generic visuals).
  For new topics at production quality set `LLM_API_KEY` (Claude) — that path is implemented and
  unit-tested with a mocked client, but was **not exercised against the live API** during
  development (no key was available).
* **Manim is not used**; diagrams come from the in-house Cairo doodle engine (keeps one visual
  style, avoids LaTeX/OpenGL dependencies).
* **Word-level caption timing** is phoneme-weighted inside each sentence (sentence boundaries are
  exact); it is phrase-accurate but not forced-alignment accurate.
* **Lip sync** follows loudness (open/close + width variation), not phoneme visemes.
* **Character views**: Milo is drawn in a front/three-quarter view and mirrored for left/right;
  there is no true side or back view. Walks/runs are stylised.
* **Music** is procedurally generated (pleasant, unobtrusive, royalty-free) but simpler than
  produced library music; drop licensed tracks in by extending `audio/music_engine.py`.
* **Research relevance** relies on keyword search plus filters; unusual topics may return few
  authoritative sources (always check `research/research.json`). NHS/CDC/APA content is reached
  only through the optional Tavily provider.
* Optional AI image generation for assets is not implemented; the local SVG library is the only
  asset source (extend `assets/<category>/` with new SVGs following `docs/BRAND_GUIDE.md`).
* Analytics are CSV-import based (no platform API integration), as specified.
