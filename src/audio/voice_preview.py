"""Short narration previews for choosing / verifying a voice before a full render.

``python -m src.main voice preview`` renders the same directed passage with every voice
profile (and optionally extra provider voices), measures each take with the narration QC
metrics (Whisper intelligibility, pitch variation, pace, level) and writes a comparison:

  <out>/<candidate>.wav  ·  <out>/voice_comparison.json  ·  <out>/voice_comparison.md
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from src.audio.audio_qc import (asr_available, compare_voices, read_wav, signal_metrics, transcribe, voice_score,
                                word_error_rate)
from src.audio.tts_engine import SceneContext, TTSEngine, resolve_voice
from src.config.settings import Settings

log = logging.getLogger(__name__)

PREVIEW_SCENES = [
    ("hook", "Your heart beats about a hundred thousand times a day. But what is it actually doing in there?"),
    ("explain", "The heart is a muscle with four rooms, called chambers. The right side pumps blood to your lungs, "
                "and the left side sends it to the rest of your body."),
    ("surprise", "But here's the surprising part: the heartbeat starts inside the heart itself, with its own "
                 "built-in electrical spark."),
    ("ending", "So the next time you feel your pulse, remember: that's your own power plant, working every second. "
               "Stay curious!"),
]


def _candidates(settings: Settings, extra: Sequence[str]) -> List[Dict]:
    out = [{"name": "baseline_piper_joe", "provider": "piper", "voice": "en_US-joe-medium",
            "legacy": True, "label": "Previous default (Piper joe, length_scale 1.15, noise 0.72, flat delivery)"}]
    for key, p in settings.tts.profiles.items():
        out.append({"name": f"profile_{key}", "profile": key, "label": f"{p.label} — {p.description}"})
    for v in extra:
        out.append({"name": f"voice_{v.replace(':', '').replace(',', '_')}", "voice_value": v, "label": v})
    return out


def preview(settings: Settings, out_dir: Path, extra_voices: Sequence[str] = (), asr: bool = True,
            scenes: Optional[Sequence] = None) -> Dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    scenes = scenes or PREVIEW_SCENES
    rows: List[Dict] = []
    for cand in _candidates(settings, extra_voices):
        s = copy.deepcopy(settings)
        try:
            if cand.get("legacy"):
                s.tts.provider, s.tts.voice = "piper", cand["voice"]
                s.tts.length_scale, s.tts.noise_scale, s.tts.noise_w_scale = 1.15, 0.72, 0.85
                s.tts.profiles[s.tts.profile].expressiveness = 0.0    # the old engine read every sentence alike
                s.tts.profiles[s.tts.profile].speed = 1.0
            elif "profile" in cand:
                s.tts.profile = cand["profile"]
            else:
                resolve_voice(s, cand["voice_value"])
            eng = TTSEngine(s)
            parts = []
            for i, (_, text) in enumerate(scenes):
                parts.append(eng.synthesize_scene(f"{cand['name']}_{i}", text, out_dir / "_parts", s.tts.length_scale,
                                                  context=SceneContext(index=i, count=len(scenes))))
        except Exception as exc:  # noqa: BLE001 - a missing provider must not stop the comparison
            rows.append({**cand, "error": f"{type(exc).__name__}: {exc}"})
            log.warning("preview %s failed: %s", cand["name"], exc)
            continue
        import numpy as np
        import wave
        sr = parts[0].sample_rate
        gap = np.zeros(int(sr * 0.45), dtype=np.int16)
        chunks = []
        for p in parts:
            x, _ = read_wav(p.wav_path)
            chunks += [(x * 32767).astype(np.int16), gap]
        wav = out_dir / f"{cand['name']}.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(np.concatenate(chunks).tobytes())
        x, _ = read_wav(str(wav))
        m = signal_metrics(x, sr)
        words = sum(len(t.split()) for _, t in scenes)
        row = {**cand, "file": wav.name, "provider_used": eng.provider.name, "voice_used": eng.provider.voice_name,
               "duration_s": m["duration"], "words_per_second": round(words / sum(p.duration for p in parts), 2),
               "f0_std_semitones": m["f0_std_semitones"], "f0_range_semitones": m["f0_range_semitones"],
               "f0_median_hz": m["f0_median_hz"], "peak_dbfs": m["peak_dbfs"], "clip_ratio": m["clip_ratio"],
               "prosody_std": m.get("prosody_std", 0), "prosody_range": m.get("prosody_range", 0),
               "jitter": m.get("jitter", 0), "harmonicity": m.get("harmonicity", 0),
               "octave_errors": m.get("octave_errors", 0),
               "sample_rate": sr, "intents": [d["intent"] for p in parts for d in p.deliveries]}
        if asr and asr_available():
            heard = transcribe(str(wav))
            row["wer"] = round(word_error_rate(" ".join(t for _, t in scenes), heard), 3)
            row["heard"] = heard
        row["score"] = voice_score(row)
        rows.append(row)
    ranked = compare_voices([r for r in rows if "error" not in r])
    report = {"passage": [t for _, t in scenes], "candidates": rows,
              "ranking": [r["name"] for r in ranked], "default_profile": settings.tts.profile}
    (out_dir / "voice_comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out_dir / "voice_comparison.md").write_text(_markdown(report), encoding="utf-8")
    return report


def _markdown(rep: Dict) -> str:
    lines = ["# Voice comparison", "", "Same directed passage (hook, explanation, surprise, ending) for every voice.",
             "", "| Candidate | Engine / voice | Score /100 | WER | Harmonicity | Jitter (st) | Octave breaks | "
             "Intonation std (st) | Pace (w/s) |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rep["candidates"]:
        if "error" in r:
            lines.append(f"| {r['name']} | — | error: {r['error'][:60]} | | | | | | |")
            continue
        wer = f"{r['wer']:.1%}" if "wer" in r else "n/a"
        lines.append(f"| {r['name']} | {r['provider_used']} `{r['voice_used']}` | {r.get('score', '')} | {wer} | "
                     f"{r['harmonicity']} | {r['jitter']} | {r['octave_errors']:.1%} | {r['prosody_std']} | "
                     f"{r['words_per_second']} |")
    lines += ["", "Harmonicity: tonal clarity (higher = cleaner, less buzzy). Jitter: frame-to-frame pitch "
              "instability (lower = steadier, no warble). Octave breaks: pitch jumps typical of vocoder artefacts. "
              "Intonation: phrase-level melody (about 2-4.5 st sounds lively but natural).", "",
              f"Ranking: {', '.join(rep['ranking'])}"]
    return "\n".join(lines) + "\n"
