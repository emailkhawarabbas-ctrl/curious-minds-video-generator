"""Render a user-written script file: narration -> word alignment -> render -> QC -> report.

No research or fact-check runs (the script is yours), but the technical QC and the hard
narration checks still decide the result: the run is ``success`` only if the video
rendered and passed both, as in topic mode.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from src.audio.audio_qc import narration_qc
from src.audio.music_engine import LICENSE as MUSIC_LICENSE
from src.audio.sound_effects import LICENSE as SFX_LICENSE, ensure_library
from src.audio.tts_engine import SceneContext, TTSEngine, resolve_voice
from src.audio.word_aligner import align_all
from src.config.settings import Settings
from src.rendering.horizontal_renderer import OUTPUT_NAME as LONG_NAME, HorizontalRenderer
from src.rendering.quality_control import check_video
from src.rendering.renderer import plan_timeline
from src.rendering.vertical_renderer import OUTPUT_NAME as SHORT_NAME, VerticalRenderer
from src.script_mode.builder import build_storyboard
from src.script_mode.schema import load_user_script
from src.utils.ffmpeg import require_binaries
from src.utils.text import slugify

log = logging.getLogger(__name__)
DURATION_RANGE = {"short": (3.0, 180.0), "long": (30.0, 1800.0)}   # your script decides the length


def output_dir(settings: Settings, title: str, style: str, root: Optional[Path] = None) -> Path:
    slug = slugify(title)
    return (root or settings.paths.generated) / (slug if style == "whiteboard" else f"{slug}_{style}")


def render_script(path: Path, settings: Settings, style: str = "whiteboard", out_root: Optional[Path] = None,
                  voice: Optional[str] = None, subtitles: Optional[bool] = None) -> Dict:
    t0 = time.time()
    us = load_user_script(path)                      # raises ScriptFileError with readable problems
    require_binaries()
    if voice or us.voice:
        resolve_voice(settings, voice or us.voice)
    settings.render.burn_subtitles = us.subtitles if subtitles is None else subtitles
    renderer = VerticalRenderer(settings) if us.format == "short" else HorizontalRenderer(settings)
    out_name = SHORT_NAME if us.format == "short" else LONG_NAME
    sb = build_storyboard(us, renderer.profile, style, str(path))
    root = output_dir(settings, us.title, style, out_root)
    work, audio_dir = root / "work", root / "audio"
    for d in (root, work, audio_dir, root / "subtitles"):
        d.mkdir(parents=True, exist_ok=True)
    report: Dict = {"title": us.title, "script_file": str(path), "style": style, "format": us.format,
                    "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": "failed"}
    try:
        ensure_library()
        tts = TTSEngine(settings)
        report["voice"] = tts.voice_report()
        n = len(sb.scenes)
        audios = {sc.scene_id: tts.synthesize_scene(sc.scene_id, sc.narration, audio_dir, settings.tts.length_scale,
                                                    sb.fps, context=SceneContext(i, n, sc.role))
                  for i, sc in enumerate(sb.scenes)}
        if style in ("whiteboard", "lively"):
            report["word_alignment"] = align_all(audios, settings.tts.word_alignment)
        timings = plan_timeline(sb, audios, sb.fps, settings.tts.scene_lead_in_s, settings.tts.scene_tail_s)
        for sc, tm in zip(sb.scenes, timings):
            sc.duration = round(tm.duration, 3)
        (root / "storyboard.json").write_text(sb.model_dump_json(indent=2), encoding="utf-8")
        nqc = narration_qc(audios, {sc.scene_id: sc.duration for sc in sb.scenes}, settings.tts.asr_check, 0)
        report["narration_qc"] = nqc
        srt = root / "subtitles" / f"{out_name.rsplit('.', 1)[0]}.srt"
        out = root / out_name
        res = renderer.render(sb, audios, out, work, srt)
        rng: Tuple[float, float] = DURATION_RANGE[us.format]
        qc = check_video(out, renderer.profile.width, renderer.profile.height, renderer.profile.fps, rng,
                         settings.audio.target_lufs, srt)
        report["qc"] = qc
        reasons = [f"technical: {c['check']} (got {c.get('value')}, expected {c.get('expected')})"
                   for c in qc["checks"] if not c["passed"]]
        reasons += [f"voice: {c['check']} ({c['detail']})" for c in nqc["checks"]
                    if not c["passed"] and c.get("severity") == "hard"]
        report.update({"video": out_name, "subtitles": str(srt.relative_to(root)), "duration_s": round(res.duration, 2),
                       "frames": res.frames, "scenes": len(sb.scenes), "render_seconds": res.render_seconds,
                       "audio_mix": res.audio_report, "failed_checks": reasons,
                       "segments": [{k: r[k] for k in ("scene_id", "seconds", "ms_per_frame")}
                                    for r in res.segment_stats],
                       "licenses": {"narration_voice": tts.provider.license_note, "music": MUSIC_LICENSE,
                                    "sound_effects": SFX_LICENSE,
                                    "visual_assets": "Original Curious Minds SVG artwork"},
                       "status": "success" if not reasons else "qc_failed"})
    except Exception as exc:  # noqa: BLE001 - recorded in the report, then re-raised for the CLI
        report["error"] = f"{type(exc).__name__}: {exc}"
        log.error("script render failed: %s", exc)
        raise
    finally:
        report["total_seconds"] = round(time.time() - t0, 1)
        (root / "production_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
        shutil.rmtree(work, ignore_errors=True)
    return report
