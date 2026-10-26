"""Render a user-written script file: narration -> word alignment -> render -> QC -> thumbnails -> report.

One script can produce both formats: the 9:16 Short and the 16:9 YouTube video share the same
narration (synthesised once), each gets its own storyboard, captions and QC. By default only the
script's own ``format`` is rendered; ``formats`` overrides that (the GitHub workflow passes its
generate_shorts / generate_long_video inputs). Thumbnails (16:9 and 9:16) use the topic-mode engine.

No research or fact-check runs (the script is yours), but the technical QC and the hard
narration checks still decide the result: the run is ``success`` only if every requested video
rendered and passed both, as in topic mode.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from src.audio.audio_qc import narration_qc
from src.audio.music_engine import LICENSE as MUSIC_LICENSE
from src.audio.sound_effects import LICENSE as SFX_LICENSE, ensure_library
from src.audio.tts_engine import SceneContext, TTSEngine, resolve_voice
from src.audio.word_aligner import align_all
from src.config.settings import Settings
from src.content.models import Storyboard
from src.rendering.horizontal_renderer import OUTPUT_NAME as LONG_NAME, HorizontalRenderer
from src.rendering.quality_control import check_video
from src.rendering.renderer import plan_timeline
from src.rendering.thumbnail_engine import default_concepts, render_thumbnails
from src.rendering.vertical_renderer import OUTPUT_NAME as SHORT_NAME, VerticalRenderer
from src.script_mode.builder import build_storyboard
from src.script_mode.schema import UserScript, load_user_script
from src.utils.ffmpeg import require_binaries
from src.utils.text import slugify

log = logging.getLogger(__name__)
DURATION_RANGE = {"short": (3.0, 180.0), "long": (3.0, 1800.0)}   # your script decides the length
FORMATS = ("short", "long")


def output_dir(settings: Settings, title: str, style: str, root: Optional[Path] = None) -> Path:
    slug = slugify(title)
    return (root or settings.paths.generated) / (slug if style == "whiteboard" else f"{slug}_{style}")


def _thumbnails(us: UserScript, sb: Storyboard, out_dir: Path, root: Path) -> List[str]:
    mains = [o.asset for sc in sb.scenes for o in sc.objects if o.role == "main"]
    alt = next((a for a in mains[1:] if a != mains[0]), None)
    head = sb.scenes[0].lively.headline if sb.scenes[0].lively else None
    short = head if head and len(head.split()) <= 4 else None
    shutil.rmtree(out_dir, ignore_errors=True)                        # no stale thumbnails from an earlier run
    paths = render_thumbnails(default_concepts(us.title, mains[0], alt, short), out_dir, sb.character)
    return [str(p.relative_to(root)).replace("\\", "/") for p in paths]


def render_script(path: Path, settings: Settings, style: str = "whiteboard", out_root: Optional[Path] = None,
                  voice: Optional[str] = None, subtitles: Optional[bool] = None,
                  formats: Optional[Sequence[str]] = None, thumbnail: bool = True) -> Dict:
    t0 = time.time()
    us = load_user_script(path)                      # raises ScriptFileError with readable problems
    fmts = [f for f in FORMATS if f in (formats or [us.format])]
    if not fmts:
        raise ValueError(f"no format to render (got {list(formats or [])}); use short and/or long")
    require_binaries()
    if voice or us.voice:
        resolve_voice(settings, voice or us.voice)
    settings.render.burn_subtitles = us.subtitles if subtitles is None else subtitles
    renderers = {"short": VerticalRenderer, "long": HorizontalRenderer}
    names = {"short": SHORT_NAME, "long": LONG_NAME}
    boards = {f: build_storyboard(us.model_copy(update={"format": f}), renderers[f](settings).profile, style,
                                  str(path)) for f in fmts}
    root = output_dir(settings, us.title, style, out_root)
    work, audio_dir = root / "work", root / "audio"
    for d in (root, work, audio_dir, root / "subtitles"):
        d.mkdir(parents=True, exist_ok=True)
    report: Dict = {"title": us.title, "script_file": str(path), "style": style, "formats": fmts,
                    "format": fmts[0], "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "status": "failed", "outputs": {}}
    try:
        ensure_library()
        tts = TTSEngine(settings)
        report["voice"] = tts.voice_report()
        first = boards[fmts[0]]
        n = len(first.scenes)
        audios = {sc.scene_id: tts.synthesize_scene(sc.scene_id, sc.narration, audio_dir, settings.tts.length_scale,
                                                    first.fps, context=SceneContext(i, n, sc.role))
                  for i, sc in enumerate(first.scenes)}
        if style in ("whiteboard", "lively"):
            report["word_alignment"] = align_all(audios, settings.tts.word_alignment)
        all_reasons: List[str] = []
        for f in fmts:
            sb, renderer = boards[f], renderers[f](settings)
            timings = plan_timeline(sb, audios, sb.fps, settings.tts.scene_lead_in_s, settings.tts.scene_tail_s)
            for sc, tm in zip(sb.scenes, timings):
                sc.duration = round(tm.duration, 3)
            sb_json = sb.model_dump_json(indent=2)
            (root / f"storyboard_{f}.json").write_text(sb_json, encoding="utf-8")
            if f == fmts[0]:
                (root / "storyboard.json").write_text(sb_json, encoding="utf-8")
                report["narration_qc"] = narration_qc(audios, {sc.scene_id: sc.duration for sc in sb.scenes},
                                                      settings.tts.asr_check, 0)
            nqc = report["narration_qc"]
            srt = root / "subtitles" / f"{names[f].rsplit('.', 1)[0]}.srt"
            out = root / names[f]
            res = renderer.render(sb, audios, out, work, srt)
            rng: Tuple[float, float] = DURATION_RANGE[f]
            qc = check_video(out, renderer.profile.width, renderer.profile.height, renderer.profile.fps, rng,
                             settings.audio.target_lufs, srt)
            reasons = [f"technical: {c['check']} (got {c.get('value')}, expected {c.get('expected')})"
                       for c in qc["checks"] if not c["passed"]]
            reasons += [f"voice: {c['check']} ({c['detail']})" for c in nqc["checks"]
                        if not c["passed"] and c.get("severity") == "hard"]
            all_reasons += [f"{f}: {r}" for r in reasons]
            report["outputs"][f] = {
                "video": names[f], "subtitles": str(srt.relative_to(root)).replace("\\", "/"),
                "duration_s": round(res.duration, 2), "frames": res.frames, "scenes": len(sb.scenes),
                "render_seconds": res.render_seconds, "audio_mix": res.audio_report, "qc": qc,
                "failed_checks": reasons, "status": "success" if not reasons else "qc_failed",
                "segments": [{k: r[k] for k in ("scene_id", "seconds", "ms_per_frame")} for r in res.segment_stats]}
        if thumbnail:
            report["thumbnails"] = _thumbnails(us, first, root / "thumbnails", root)
        main = report["outputs"][fmts[0]]
        report.update({"video": main["video"], "subtitles": main["subtitles"], "duration_s": main["duration_s"],
                       "scenes": main["scenes"], "qc": main["qc"],
                       "render_seconds": round(sum(o["render_seconds"] for o in report["outputs"].values()), 1),
                       "failed_checks": all_reasons,
                       "licenses": {"narration_voice": tts.provider.license_note, "music": MUSIC_LICENSE,
                                    "sound_effects": SFX_LICENSE,
                                    "visual_assets": "Original Curious Minds SVG artwork"},
                       "status": "success" if not all_reasons else "qc_failed"})
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
