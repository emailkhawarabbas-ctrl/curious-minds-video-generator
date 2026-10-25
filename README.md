# CURIOUS MINDS — automated cartoon & doodle educational video generator

*Understand the world in a fun way.*

Give it one topic. It researches the topic from real sources, writes original narration with
a retention-focused story arc, builds format-specific storyboards in one of **three niche
visual identities** (Human Body · Science · Psychology), animates a **per-niche host character** (a see-through anatomy kid, a flask scientist or a
two-tone brain; Milo for topics outside the three niches) acting
alongside topic-specific illustrations and **animated scientific demonstrations**, narrates
with a directed, natural **neural US-English male voice** (Kokoro, local and free), mixes music and sound
effects, renders a **9:16 TikTok/Shorts video** and a **16:9 YouTube long-form video**,
burns in captions, exports SRT, draws thumbnails, writes titles/descriptions/chapters, runs
automated voice / visual / storytelling / technical quality control with a per-video report, and
saves everything for manual review.

See [`docs/QUALITY_UPGRADE.md`](docs/QUALITY_UPGRADE.md) for the root-cause analysis of the
previous voice, visuals and storytelling, and a before/after comparison.

Runs locally or on GitHub Actions. **No paid service is required.** Claude (via `LLM_API_KEY`)
is optional and used for writing scripts/metadata for new topics.

There are two ways to make a video:

* **Your own script** (script mode): you write the text scene by scene, the tool animates it
  as a **whiteboard explainer**: a hand draws everything line by line and the host reacts.
  See the next section.
* **A topic** (topic mode): the tool researches and writes the script itself (§1–§3).

---

## Make a video from your own script (script mode)

### 1. Write a script file

Create a file in `scripts/`, for example `scripts/my_video.yaml`:

```yaml
title: "What Happens If You Don't Sleep for 24 Hours"
format: short          # short = 1080x1920 (Shorts/TikTok), long = 1920x1080 (YouTube)
voice_language: en     # English only
loop_to_start: true    # the last frame flows back into the first, so the Short loops
scenes:
  - text: "Stay awake for *24 hours*, and your brain starts acting *drunk*."
    visual: brain.svg
    sfx: whoosh
  - text: "Then come *microsleeps*: blackouts of a few seconds you don't even notice."
    visual: eye.svg
    visuals: [zzz.svg]
```

Only `text` is required in each scene. Anything you leave out is chosen for you, and the
choices change from scene to scene so the video never looks the same twice in a row.

**Tips**

* Wrap a word in `*asterisks*` to make it the scene's keyword: it is handwritten on the board and
  gets one gentle camera punch-in. The asterisks are not spoken.
* Keep each scene to one or two short sentences (max 45 words for a Short).
* About 2.8 words = 1 second of narration. 80–90 words make a ~30 s Short.
* For a good loop, write the last line so it leads back into the first line.
* A complete example: [`scripts/sample_24_hours_awake.yaml`](scripts/sample_24_hours_awake.yaml).

### 2. All script options

Top of the file:

| Field | What it does | Default |
|---|---|---|
| `title` | video title (also the opening headline) | required |
| `format` | `short` (9:16) or `long` (16:9) | `short` |
| `voice_language` | `en` | `en` |
| `voice` | `friendly`, `energetic`, `documentary`, or a Kokoro voice like `am_michael` | `friendly` |
| `niche` | `human_body`, `science`, `psychology`, `mixed`: picks the host character | `mixed` |
| `character` | force a host: `human_body`, `science`, `psychology`, `milo`, `zoe` | from `niche` |
| `music` | background music mood: `curious`, `dreamy`, `upbeat`, `calm` | `curious` |
| `subtitles` | burn in captions: `true` / `false` | `true` |
| `loop_to_start` | end on the first frame so the Short loops | `false` |

Each scene:

| Field | Options | Default |
|---|---|---|
| `text` | the narration (required) | — |
| `visual` | an SVG from `assets/` (`brain.svg` or `brain`) | best match for the text |
| `visuals` | up to 3 extra SVGs, drawn small during the scene (or held up by the host) | none |
| `animation` | how the main visual appears: `draw_on` (the hand draws it line by line, then colour fills in), `pop_in` (grows 0 → 110 % → 100 %), `bounce`, `slide_in`, `spin_in`, `fade_in` | whiteboard: `draw_on` |
| `camera` | slow move for the whole scene: `zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `pan_up`, `pan_down`, `drift`, `static` | whiteboard: `zoom_in` / `zoom_out` in turn (3–5 %) |
| `shake` | `true` = small camera shake for a dramatic line | `false` |
| `sfx` | one or a list: `pop`, `whoosh`, `ding`, `sparkle`, `boing`, `click`, `chime`, `tick`, `bubble`, `magic`, `snore`, `heartbeat`, `success`, `scribble` | none (marker scribbles and whooshes are added automatically) |
| `headline` | text handwritten across the top, max 48 characters | the title on scene 1 |
| `host` | where the host stands: `left`, `right`, `center` (big, waist-up), `corner_left`, `corner_right`, `none` | changes per scene |
| `pose` | the host's action: `draw` (writes the keyword with a marker), `count` (counts on fingers), `hold_up` (holds up the first extra visual), `think`, `surprised`, `shrug`, `explain`, `point`, `present`, `excited`, `happy`, `sad`, `thumbs_up`, `celebrate`, `yawn`, `wave`, `talk`, `sleep` | from the text, see below |
| `expression` | `happy`, `excited`, `surprised`, `curious`, `thinking`, `worried`, `confused`, `determined`, `sleepy`, `scared`, `sad`, `laughing`, … | from the action |
| `host_enter` | `walk` (walks into the frame), `pop`, `none` | `walk` on scene 1 |
| `host_exit` | `walk` (walks out at the end of the scene), `none` | `none` |
| `transition` | into the next scene: `whip_left`, `whip_right`, `whip_up`, `zoom_through`, `ink_swipe`, `cut` | changes per scene |

How the host's action is picked when you leave `pose` out (never the same action twice in a row):
a question → `think`; "nobody knows", "maybe" → `shrug`; a small number ("one", "two", "3",
"twice") → `count`; a shocking fact ("!", "actually", "even", "huge", …) → `surprised`; a process
("because", "then", "makes", "leads to", …) → `draw`; a scene with extra `visuals` → `hold_up`;
otherwise `explain` / `point` / `present`.

All SVG names: `python -m src.main assets list`. To use a new SVG, put it in
`assets/<category>/` (following [`docs/BRAND_GUIDE.md`](docs/BRAND_GUIDE.md)) and run
`python -m src.main assets index`.

If something is wrong, the tool lists every problem with the scene number and a suggestion:

```text
Script problems in scripts/my_video.yaml:
  - scene 1: unknown field 'visul'. Did you mean 'visual'?
  - scene 2: visual: 'clok.svg' not found in assets/. Did you mean clock.svg? ...
  - scene 2: animation: unknown animation 'drawon'. Did you mean 'draw_on'? ...
```

### 3. Run it on your computer

```bash
python -m src.main render-script --script scripts/my_video.yaml                    # whiteboard look
python -m src.main render-script --script scripts/my_video.yaml --style lively     # bouncy lively look
python -m src.main render-script --script scripts/my_video.yaml --style classic    # the original look
```

On Windows run `set PYTHONUTF8=1` (cmd) or `export PYTHONUTF8=1` (Git Bash) first, and once
`python scripts/install_fonts_windows.py`: on Windows Cairo only sees installed fonts, so without
it captions and handwriting fall back to Arial (`--remove` undoes it; Linux/GitHub need nothing).
The video is written to `generated/<title>/curious_minds_shorts_9x16.mp4`, with captions
(`subtitles/*.srt`), the storyboard and `production_report.json`. The other looks go to
`generated/<title>_lively/` and `generated/<title>_classic/`. A 30 s Short takes 2–4 minutes.

To compare two renders side by side:
`python scripts/side_by_side.py --left <old.mp4> --right <new.mp4> --left-label OLD --right-label NEW --out compare.mp4`

### 4. Run it from GitHub

1. Commit your script file to the repo (for example `scripts/my_video.yaml`) and push.
2. Go to **Actions → Generate Curious Minds video → Run workflow**.
3. Set **script_file** to `scripts/my_video.yaml` (leave **topic** empty). **style** `auto` uses the
   whiteboard look (`lively` and `classic` also work).
4. When the run finishes, download the video from the run's **Artifacts**.

### What the whiteboard look does (default for your scripts)

* **Real drawing**: a hand holding a marker traces every visual stroke by stroke (big shapes
  first, details after), lifting the pen between strokes, then the colour fades in. The main
  drawing takes about 60 % of the scene, timed to the narration. Fill-only parts of an SVG get an
  outline traced around them automatically, so nothing just pops in.
* **Handwriting**: the headline and each scene's keyword are written on the board letter by
  letter, with a red marker underline.
* **A host that explains**: while the hand draws, the host watches; then it acts: thinks,
  counts on its fingers, reacts in surprise, shrugs, holds up an object, presents, or takes the
  marker and writes the keyword itself. It walks in on scene 1, changes place and action every
  scene, lip-syncs to the voice and blinks. The host stands in front of the board.
* **Calm camera**: a slow 3–5 % zoom per scene, no constant panning, at most one small smooth
  punch-in (6 %) on the keyword, no shake unless you ask for it.
* **Never static**: when nothing new is drawn for ~1.8 s, the pen adds a quick circle, arrow,
  underline or emphasis lines.
* Captions, transitions, hook, loop, paper background and music are as in the lively look below.

All whiteboard values (camera, drawing speed, hand size, handwriting) are in the `whiteboard:`
section of [`config/style.yaml`](config/style.yaml).

`python scripts/audit_assets.py` checks every SVG for stroke-by-stroke drawing and writes
[`docs/ASSET_AUDIT.md`](docs/ASSET_AUDIT.md).

### What the lively look does (`--style lively`)

* **Draw-on and pop-in**: lines draw themselves, then colour fades in. Pop-ins grow to 110 % and
  settle at 100 %. All motion is eased; nothing moves linearly.
* **The camera is always moving**: a slow zoom or pan on every scene (about 16 %), a quick
  punch-in on key words, an optional shake, and a slight hand-held sway.
* **Something new every ~1.6 s**: when a scene is long, the tool adds secondary motion: a
  keyword sticker, a hand-drawn circle, an arrow, a sparkle burst or a squash-and-stretch bounce.
* **Big captions, word by word**: bold, centred low, thick outline and shadow. The word being
  spoken turns yellow. Word timings are measured from the voice with faster-whisper.
  The captions stay out of the Shorts side buttons and description area.
* **Quick transitions** (0.26 s): whips with motion blur, zoom-through and ink swipes, each with a whoosh.
* **Hook**: the first frame already shows the headline, the main visual and the host. No intro, no logo.
* **Loop ending**: with `loop_to_start: true` the last frames turn back into the opening frame.
* **Hand-drawn feel**: off-white paper with grain, lines that "boil" (redrawn 8 times a
  second), and a big host who changes position and pose between scenes.
* **Sound**: whoosh / pop / sparkle / click effects on transitions and pop-ins, and background
  music that automatically ducks under the voice.

All colours, fonts and timings of the lively look are in one file: [`config/style.yaml`](config/style.yaml).
The old look is still available everywhere: `--style classic` (script mode) and the default
for topic mode (`generate --style lively` switches a topic video to the new look).

**Licences of the sounds**: every sound effect and the background music are generated by the
code itself (`src/audio/sound_effects.py`, `src/audio/music_engine.py`). No third-party
recordings are used, so there is nothing to license. If you add your own music, use only
CC0 / royalty-free tracks and keep a note of the source.

**Measure the motion** of any rendered video and make a contact sheet of mid-scene frames:

```bash
PYTHONPATH=. python scripts/motion_report.py --video generated/<title>/curious_minds_shorts_9x16.mp4 \
    --storyboard generated/<title>/storyboard.json --sheet sheet.png
```

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

Output lands in `generated/why_do_we_dream/` (see §5). The Kokoro voice model (~350 MB) is
downloaded automatically on first use into `models/kokoro/`; the Whisper model used for the
intelligibility check (~140 MB) into the Hugging Face cache.

> **Windows:** works with Python 3.11 + a static FFmpeg build on `PATH` (pycairo, piper-tts and
> kokoro-onnx ship Windows wheels). Set `PYTHONUTF8=1` so text files are read as UTF-8.

> If your system cannot build `pycairo` (no Python headers), create the venv with
> `python3 -m venv --system-site-packages .venv` and install `python3-cairo` from apt.

### Exact commands for future videos

```bash
# both formats, default durations (short 75 s, long 8 min)
python -m src.main generate --topic "Why Do We Get Goosebumps?" --niche human_body

# only a Short, 60 s
python -m src.main generate --topic "Why Is the Sky Blue?" --niche science --no-long --short-duration 60
# the Phase 1 acceptance Short (curated pack, ~1 minute)
python -m src.main generate --topic "Why Water Is the Weirdest Substance on Earth" --niche science --no-long --short-duration 55

# only a long video, 10 minutes, calm documentary voice, no burned-in captions
python -m src.main generate --topic "How Does Your Brain Create Memories?" --niche psychology \
    --no-short --long-duration 10 --voice "US English Male (Calm)" --subtitles false

# the three niche samples (curated content packs)
python -m src.main generate --topic "Why Do We Overthink Everything?" --niche psychology
python -m src.main generate --topic "How Does Your Heart Actually Work?" --niche human_body
python -m src.main generate --topic "Why Is the Sky Blue?" --niche science

# force the script source: auto | llm | curated | offline
python -m src.main generate --topic "How Do Magnets Work?" --niche science --script-source llm

# tools
python -m src.main voice preview                       # same passage in every voice profile + scores
python -m src.main voice preview --extra am_fenrir am_puck en_US-joe-medium
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
| `script_file` | your script in the repo, e.g. `scripts/my_video.yaml` (script mode; then `topic` is not needed) |
| `topic` | free text (3–120 chars), required when `script_file` is empty |
| `style` | `auto` (lively for script files, classic for topics) / `lively` / `classic` |
| `niche` | science / psychology / human_body / mixed |
| `generate_shorts`, `generate_long_video` | true / false |
| `short_duration` | 25–90 s (accepted within ±20 % of the requested target) |
| `long_duration` | 6–10 min |
| `voice` | US English Friendly Male (default) / Energetic / Calm / Narrator |
| `generate_subtitles`, `generate_thumbnail` | true / false |
| `script_source` | auto / llm / curated / offline |

Secrets (all optional): `LLM_API_KEY` (Anthropic, for LLM scripts/metadata),
`RESEARCH_API_KEY` (Tavily web search limited to authoritative domains), and, only if you switch
`tts.provider` to a cloud narrator, `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` or `OPENAI_API_KEY`
(`TTS_API_KEY` works as a generic fallback key). The default Kokoro narrator needs no key.

The job: checks out, validates inputs (passed via env vars — no shell interpolation),
installs FFmpeg/Cairo, caches pip, the Kokoro/Piper voice models and the Whisper QC model,
runs unit tests, generates, writes a voice / story / visual / technical QC summary to the run page, uploads `generated/<slug>/` as an artifact (14-day retention),
and fails the run if any requested video failed or did not pass QC. Generated media is never
committed (`.gitignore`). Timeout: 120 min (a full short + 8-min long run takes roughly
10–20 min on a 4-vCPU runner).

## 3. How it works

```
topic ─► research (Wikipedia, MedlinePlus/NIH, PubMed, opt. Tavily) ─► facts + sources + statuses
      ─► script  (curated pack │ Claude JSON + Pydantic + fact-check repair loop │ offline template)
      ─► story roles (hook, curiosity gap, discovery, ...) ─► niche theme (human_body / science / psychology)
      ─► storyboard per orientation: niche-aware visual selector (concept ontology), animated
         demonstrations, composition variety, word-cued character acting, purposeful camera
      ─► validation & repair (vocabulary, assets, text lengths, durations, transitions)
      ─► directed narration per sentence (Kokoro; delivery per intent) ─► measured durations ─► speed fit
      ─► narration QC (clipping, cut-offs, pace, intonation, Whisper intelligibility) + preview WAV
      ─► storytelling & visual review (hook, curiosity loop, repetition, relevance, niche identity)
      ─► parallel scene rendering (Cairo vectors → raw frames → libx264 segments)
      ─► concat ─► mix (voice + ducked music + SFX) ─► 2-pass loudnorm (-14 LUFS) ─► MP4
      ─► QC (ffprobe streams, size, fps, duration, A/V sync, blank/frozen frames, loudness, SRT)
      ─► metadata, chapters, thumbnails ─► review/quality_report_<fmt>.md ─► production_report.json
```

### Project layout

```
src/
  main.py                 CLI            pipeline.py   stage orchestration + manifest
  config/settings.py      typed settings (YAML + CM__ env overrides; secrets from env only)
  research/               researcher.py (providers) · fact_checker.py · source_manager.py
  content/                models.py (Pydantic contracts) · llm_client.py (Claude) ·
                          script_generator.py · storyboard_generator.py · seo_generator.py ·
                          topic_generator.py · story_engine.py (roles, hooks, mini-hooks) ·
                          visual_selector.py (niche-aware concept ontology) · retention_review.py
  animation/              svg_loader.py · asset_manager.py · palette.py · easing.py ·
                          character_rig.py · expression_engine.py · character_engine.py ·
                          doodle_engine.py · backgrounds.py · scene_engine.py ·
                          transition_engine.py · text_render.py · registry.py (vocabulary) ·
                          themes.py (3 niche identities) · demos.py (animated demonstrations)
  audio/                  tts_engine.py (Kokoro / Piper / ElevenLabs / OpenAI) · narration_director.py ·
                          audio_qc.py · voice_preview.py · music_engine.py · sound_effects.py · mixer.py
  rendering/              renderer.py · vertical_renderer.py · horizontal_renderer.py ·
                          subtitle_engine.py · thumbnail_engine.py · quality_control.py · quality_report.py
  analytics/              csv_importer.py · performance_analyzer.py · weekly_report.py
assets/                   characters/ (milo, zoe, poses.json) · expressions/ · human_body/ ·
                          psychology/ · science/ · objects/ · fonts/ · sound_effects/ · manifest.json
content_packs/<slug>/     curated scripts + metadata (used automatically when present)
prompts/                  LLM prompt templates
config/                   default.yaml · pronunciations.yaml
scripts/                  preview_assets.py · character_sheet.py · layout_gallery.py · storyboard_preview.py ·
                          annotate_assets.py (visual QA + asset metadata tools)
docs/                     BRAND_GUIDE.md · IMPLEMENTATION_CHECKLIST.md · QUALITY_UPGRADE.md
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
* **Assets** — 96 original SVG illustrations (human body, psychology, science, everyday
  objects) with full metadata (name, category, subcategory, keywords, visual style, licence,
  supported animations), anchors and highlightable parts; drawn on with a progressive outline
  reveal. 24 procedural backgrounds with ambient animation, 11 of them niche environments.
* **Niche identities** (`themes.py`) — Human Body (medical cartoon: bloodstream, clinic with live ECG,
  anatomy blueprint, microscope cell world), Science (exploration: open sky, notebook grid, Earth's
  limb, sunset), Psychology (mind & behaviour: mind maze, late-night thought room, emotion waves).
  Each theme picks environments per scene purpose, accent colours, particles, transitions, camera
  temperament, music mood, foreground depth props and the host character (`themes.resolve_mascot`).
* **Animated demonstrations** (`demos.py`) — staged scientific diagrams on a "diagram card", synced to
  narration cue words: heart pump, two-loop circulation, ECG heartbeat, light scattering, wavelength
  comparison, sunset path, thought loop, what-if decision tree, neural signal, stress alarm response.
* **Scenes** — 18 layout templates (hook, explainer, object focus, diagram flow, list, comparison,
  thought bubble, fact card, story scene, network, chart, question, timeline, wave monitor, outro,
  demonstration, full illustration, character close-up), each with separate vertical/horizontal
  composition inside the platform-safe area and out of the caption band; reveals are synced to the
  narration (cue words). Camera moves `focus` / `follow` / `reveal` glide to whatever was just
  revealed; the background moves less than the stage (parallax) and niche foreground props more.
* **Acting** — Milo reacts sentence by sentence: thinks on questions, is surprised by surprises,
  points at the active part of a diagram when it is mentioned, explains with gestures, waves at the end.
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
* Success is only reported when every requested video exists and passes technical QC, the hard
  narration checks (clipping, cut-off sentences, narration fits, intelligibility) and — with
  `content.block_on_review_fail` — the storytelling / visual review. Every failure is listed with
  its reason in `review/quality_report_<fmt>.md` and `production_report.json`.
* The narrator never changes silently: if the configured TTS provider is unavailable the run fails,
  unless `tts.fallback_provider` is set, in which case the fallback is recorded in the report.

## 4. Configuration

`config/default.yaml` (override with `--config my.yaml` or env `CM__SECTION__KEY=value`):
voice provider and profiles (`tts.*`), duration ranges, review gating (`content.block_on_review_fail`), render profiles (resolution,
fps, safe areas, caption position), CRF/preset/workers, loudness target (-14 LUFS), music and SFX
levels, research providers, LLM model (`claude-opus-5-5`, effort, refusal fallback).
Pronunciation fixes: `config/pronunciations.yaml`.

### Narration voices

| Profile (`--voice`) | Persona | Kokoro voice | Pace |
|---|---|---|---|
| **US English Friendly Male** (default, `friendly`) | Professional Friendly Male | `am_michael` | natural |
| US English Male (Energetic) (`energetic`) | Energetic Educational Male | `am_puck` 60 % + `am_michael` 40 % | 1.04×, most expressive |
| US English Male (Calm) / (Narrator) (`documentary`) | Calm Documentary Male | `am_michael` 65 % + `am_fenrir` 35 % | 0.93×, measured |

* **Provider** (`tts.provider`): `kokoro` (default, local, Apache-2.0), `piper` (local, legacy),
  `elevenlabs` or `openai` (cloud, keys from env only). Each profile maps to every provider's own
  voice id. `--voice` also accepts a Kokoro voice/blend (`am_fenrir`, `am_michael:0.7,am_puck:0.3`) or
  a Piper id (`en_US-norman-medium`).
* **Direction** (`src/audio/narration_director.py`): every sentence gets an intent (hook, question,
  relatable, explanation, transition, surprise, discovery, ending) that sets tempo, pauses before/after
  and a small emphasis offset, scaled by the profile's `expressiveness`; cloud providers additionally
  receive it as a style / spoken instruction. Pitch (`pitch_semitones`) uses provider-native control
  where available, otherwise a formant-preserving resample (default 0 — no effects on the voice).
* **Levels**: each sentence is normalised on its speech frames (-20 dBFS RMS, peaks ≤ -1 dBFS by gain),
  then the mix is 2-pass loudness-normalised to -14 LUFS.
* **Fallback**: `tts.fallback_provider: none` — an unavailable provider fails the run rather than
  silently using a weaker voice.
* Pronunciation fixes for scientific / medical terms: `config/pronunciations.yaml`.
* Piper voices `ryan` and `hfc_male` are **CC BY-NC-SA (non-commercial)** and deliberately not used.

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
  audio/      per-scene narration WAVs + timing (sentences, words, deliveries, lip-sync envelope),
              preview_<fmt>.wav (first scenes, for a quick listen), narration_qc_<fmt>.json
  review/     storytelling_<fmt>.json (story + visual review), quality_report_<fmt>.md
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
| Kokoro-82M (`kokoro-onnx`, onnxruntime, espeak-ng) | default narrator | Apache-2.0 (model & voices) · GPL-3.0 (espeak-ng) |
| Piper TTS (`piper-tts`) | optional local narrator | GPL-3.0 (engine), voice datasets CC0 / public domain |
| faster-whisper (Whisper base.en) | narration intelligibility QC | MIT |
| numpy, Pydantic, PyYAML, requests, Pillow, python-dotenv | core | BSD/MIT/HPND |
| anthropic (optional) | Claude API client | MIT |
| Luckiest Guy · Lilita One · Patrick Hand fonts | typography | Apache-2.0 · OFL-1.1 · OFL-1.1 |
| Wikipedia, MedlinePlus (NLM), PubMed E-utilities (NCBI) | research APIs | public APIs; content cited by URL |
| Music, sound effects, SVG art, mascot | created in this project (procedural / hand-authored) | original |

## 7. Known limitations

* **Script quality without an LLM**: curated content packs give production quality; the offline
  template now follows a story arc (hook, curiosity gap, varied mini-hooks, hedged theories, payoff)
  but still assembles extracted research sentences, so it remains plainer than a written script.
  For new topics at production quality set `LLM_API_KEY` (Claude) — that path is implemented and
  unit-tested with a mocked client, but was **not exercised against the live API** during
  development (no key was available).
* **Manim is not used**; diagrams come from the in-house Cairo doodle engine (keeps one visual
  style, avoids LaTeX/OpenGL dependencies).
* **Word-level caption timing**: the lively style aligns caption words to the voice with
  faster-whisper (see `src/audio/word_aligner.py`). The classic style still uses phoneme-weighted
  estimates inside each sentence (sentence boundaries are exact).
* **Lively topic videos** (`generate --style lively`) get the new camera, beats, paper look,
  captions and transitions, but keep the classic layouts, so their subjects are smaller than in
  script mode's spotlight layout.
* **Lip sync** follows loudness (open/close + width variation), not phoneme visemes.
* **Voice quality is measured, not listened to, in CI**: narration QC uses signal metrics and a
  Whisper word-error rate; "pleasant" is still a human judgement — use `voice preview` to compare.
* **Kokoro has no native pitch or emotion control**: delivery intents are realised through pacing,
  pauses and emphasis; ElevenLabs / OpenAI providers can use richer style control (keys required,
  implemented with mocked tests only — not exercised against the live APIs).
* **Animated demonstrations** exist for ten mechanisms; other processes fall back to labelled
  illustrations, diagram flows and networks. New demos are added in `src/animation/demos.py`.
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
