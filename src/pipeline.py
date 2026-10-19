"""End-to-end episode production pipeline.

  input -> research -> script (+fact-check) -> storyboard (+validation) -> narration (fit to
  duration using measured audio) -> render -> QC -> metadata + thumbnails -> manifest

Every stage records its status in ``production_report.json``. A failed stage never
produces a false success: the run status is ``success`` only if every requested video
was rendered and passed QC.
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.animation.asset_manager import get_asset_manager
from src.audio.music_engine import LICENSE as MUSIC_LICENSE
from src.audio.sound_effects import LICENSE as SFX_LICENSE, ensure_library
from src.audio.audio_qc import narration_qc
from src.audio.tts_engine import SceneAudio, SceneContext, TTSEngine, resolve_voice
from src.config.settings import Settings
from src.content.llm_client import get_llm
from src.content.models import Format, ResearchPack, Script, Storyboard
from src.content.retention_review import review as story_review
from src.rendering.quality_report import write_quality_report
from src.content.script_generator import ScriptError, ScriptGenerator
from src.content.seo_generator import SEOGenerator, write_metadata
from src.content.storyboard_generator import StoryboardGenerator
from src.rendering.horizontal_renderer import OUTPUT_NAME as LONG_NAME, HorizontalRenderer
from src.rendering.quality_control import check_video
from src.rendering.renderer import EpisodeRenderer, plan_timeline
from src.rendering.thumbnail_engine import ThumbnailConcept, default_concepts, render_thumbnails
from src.rendering.vertical_renderer import OUTPUT_NAME as SHORT_NAME, VerticalRenderer
from src.research.researcher import Researcher
from src.utils.ffmpeg import require_binaries
from src.utils.text import slugify

log = logging.getLogger(__name__)
NICHES = ("science", "psychology", "human_body", "mixed")


@dataclass
class GenerationRequest:
    topic: str
    niche: str = "mixed"
    generate_short: bool = True
    generate_long: bool = True
    short_duration: float = 75
    long_duration: float = 480
    voice: Optional[str] = None
    subtitles: bool = True
    thumbnail: bool = True
    script_source: Optional[str] = None
    output_root: Optional[Path] = None

    def validate(self, s: Settings) -> None:
        if not self.topic or len(self.topic.strip()) < 3 or len(self.topic) > 120:
            raise ValueError("topic must be 3-120 characters")
        if self.niche not in NICHES:
            raise ValueError(f"niche must be one of {NICHES}")
        if not (self.generate_short or self.generate_long):
            raise ValueError("nothing to generate: enable short and/or long output")
        lo, hi = s.content.short_duration
        if not lo <= self.short_duration <= hi:
            raise ValueError(f"short_duration must be within {lo}-{hi} s")
        lo, hi = s.content.long_duration
        if not lo <= self.long_duration <= hi:
            raise ValueError(f"long_duration must be within {lo}-{hi} s")


def acceptance_window(target: float, allowed: Tuple[float, float]) -> Tuple[float, float]:
    """Duration range a video must land in: within 20 % of its own target, never outside the allowed range.
    A 75 s Short is accepted at 60-90 s; a 30 s Short at 25-36 s (a 30 s request must not pass at 85 s)."""
    return max(allowed[0], round(target * 0.8, 1)), min(allowed[1], round(target * 1.2, 1))


@dataclass
class Stage:
    name: str
    status: str = "pending"
    seconds: float = 0.0
    detail: Dict = field(default_factory=dict)
    error: Optional[str] = None


class Pipeline:
    def __init__(self, settings: Settings):
        self.s = settings
        self.stages: List[Stage] = []
        self.llm = get_llm(settings)

    # ------------------------------------------------------------------ helpers
    def _stage(self, name: str):
        st = Stage(name)
        self.stages.append(st)
        return st

    def _run(self, name: str, fn, *a, critical: bool = True, **kw):
        st = self._stage(name)
        t0 = time.time()
        log.info("=== stage: %s ===", name)
        try:
            res = fn(*a, **kw)
            st.status = "ok"
            if isinstance(res, tuple) and len(res) == 2 and isinstance(res[1], dict) and name.startswith("detail:"):
                st.detail = res[1]
            return res
        except Exception as exc:  # noqa: BLE001 - recorded and re-raised for critical stages
            st.status = "failed"
            st.error = f"{type(exc).__name__}: {exc}"
            log.error("stage %s failed: %s", name, exc)
            log.debug(traceback.format_exc())
            if critical:
                raise
            return None
        finally:
            st.seconds = round(time.time() - t0, 2)

    # ------------------------------------------------------------------ narration fitting
    def narrate(self, tts: TTSEngine, storyboard: Storyboard, audio_dir: Path, target: float,
                rng: Tuple[float, float]) -> Tuple[Dict[str, SceneAudio], float, List[float]]:
        """Synthesise all scenes; adjust speaking speed (within limits) to land in the duration range."""
        ls = self.s.tts.length_scale
        lo_ls, hi_ls = self.s.tts.speed_fit_range
        lead, tail = self.s.tts.scene_lead_in_s, self.s.tts.scene_tail_s
        history: List[float] = []
        audios: Dict[str, SceneAudio] = {}
        n = len(storyboard.scenes)
        for attempt in range(3):
            audios = {sc.scene_id: tts.synthesize_scene(sc.scene_id, sc.narration, audio_dir, ls, storyboard.fps,
                                                        context=SceneContext(i, n, sc.role))
                      for i, sc in enumerate(storyboard.scenes)}
            total = sum(t.duration for t in plan_timeline(storyboard, audios, storyboard.fps, lead, tail))
            history.append(round(total, 2))
            log.info("narration pass %d: length_scale=%.3f -> %.1f s (target %.0f, range %s)", attempt + 1, ls,
                     total, target, rng)
            # keep the natural pace whenever the result is in range and reasonably near the target
            if rng[0] <= total <= rng[1] and abs(total - target) / target <= 0.2:
                break
            fixed = len(storyboard.scenes) * (lead + tail)
            speech = max(1.0, total - fixed)
            want = min(max(target, rng[0] + 1), rng[1] - 1)
            new_ls = max(lo_ls, min(hi_ls, ls * (want - fixed) / speech))
            if abs(new_ls - ls) < 0.005:
                break
            ls = new_ls
        for sc in storyboard.scenes:
            sc.duration = None
        return audios, ls, history

    # ------------------------------------------------------------------ main
    def run(self, req: GenerationRequest) -> Dict:
        t_start = time.time()
        require_binaries()
        req.validate(self.s)
        if req.voice:
            resolve_voice(self.s, req.voice)
        if req.script_source:
            self.s.content.script_source = req.script_source  # type: ignore[assignment]
        self.s.render.burn_subtitles = req.subtitles
        slug = slugify(req.topic)
        root = (req.output_root or self.s.paths.generated) / slug
        dirs = {k: root / k for k in ("research", "scripts", "storyboards", "assets", "audio", "subtitles",
                                      "thumbnails", "metadata", "review", "work")}
        for d in dirs.values():
            d.mkdir(parents=True, exist_ok=True)
        (root / "logs").mkdir(exist_ok=True)
        manifest: Dict = {
            "brand": self.s.brand.name, "tagline": self.s.brand.tagline, "topic": req.topic, "slug": slug,
            "niche": req.niche, "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "request": {k: (str(v) if isinstance(v, Path) else v) for k, v in req.__dict__.items()},
            "configuration": {"llm": {"provider": self.s.llm.provider, "model": self.s.llm.model,
                                      "available": self.llm is not None},
                              "tts": {"provider": self.s.tts.provider, "profile": self.s.tts.profile,
                                      "voice": self.s.tts.voice or self.s.tts.active.kokoro_voice,
                                      "label": self.s.tts.voice_label},
                              "render": json.loads(self.s.render.model_dump_json()),
                              "audio": json.loads(self.s.audio.model_dump_json())},
            "outputs": {}, "qc": {}, "files": [], "stages": [], "status": "running",
        }
        status = "failed"
        try:
            research: ResearchPack = self._run("research", self._research, req, dirs)
            ensure_library()
            tts = self._run("tts_init", TTSEngine, self.s)
            manifest["licenses"] = self._licenses(tts)
            manifest["configuration"]["tts"] = tts.voice_report()
            manifest["narration_qc"], manifest["review"] = {}, {}
            formats: List[Tuple[Format, EpisodeRenderer, float, Tuple[float, float], str]] = []
            if req.generate_short:
                formats.append(("short", VerticalRenderer(self.s), req.short_duration, self.s.content.short_duration,
                                SHORT_NAME))
            if req.generate_long:
                formats.append(("long", HorizontalRenderer(self.s), req.long_duration, self.s.content.long_duration,
                                LONG_NAME))
            all_ok = True
            used_assets: set = set()
            for fmt, renderer, target, allowed, out_name in formats:
                rng = acceptance_window(target, allowed)
                try:
                    ok = self._produce(fmt, renderer, target, rng, out_name, req, research, tts, dirs, root,
                                       manifest, used_assets)
                except Exception as exc:  # noqa: BLE001 - one format failing must not hide the other
                    ok = False
                    manifest["outputs"][fmt] = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:2000]}
                all_ok = all_ok and ok
            self._copy_assets(used_assets, dirs["assets"], manifest)
            status = "success" if all_ok else "failed"
        except Exception as exc:  # noqa: BLE001
            manifest["error"] = f"{type(exc).__name__}: {exc}"
            log.error("pipeline aborted: %s", exc)
        finally:
            manifest["stages"] = [s.__dict__ for s in self.stages]
            manifest["status"] = status
            manifest["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            manifest["total_seconds"] = round(time.time() - t_start, 1)
            manifest["files"] = sorted(str(p.relative_to(root)) for p in root.rglob("*")
                                       if p.is_file() and "work" not in p.parts)
            (root / "production_report.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
            shutil.rmtree(dirs["work"], ignore_errors=True)
        return manifest

    # ------------------------------------------------------------------ stages
    def _research(self, req: GenerationRequest, dirs: Dict[str, Path]) -> ResearchPack:
        r = Researcher(self.s)
        pack = r.research(req.topic, req.niche)
        (dirs["research"] / "research.json").write_text(pack.model_dump_json(indent=2))
        (dirs["research"] / "source_texts.json").write_text(json.dumps(r.source_texts, indent=1, ensure_ascii=False))
        sources = [json.loads(s.model_dump_json()) for s in pack.sources]
        (dirs["research"].parent / "sources.json").write_text(json.dumps(
            {"topic": req.topic, "research_status": pack.status, "providers": pack.providers, "sources": sources},
            indent=2, ensure_ascii=False))
        self._texts = r.source_texts
        if pack.status == "unavailable":
            log.error("research unavailable: %s", pack.providers)
        return pack

    def _produce(self, fmt: Format, renderer: EpisodeRenderer, target: float, rng: Tuple[float, float],
                 out_name: str, req: GenerationRequest, research: ResearchPack, tts: TTSEngine,
                 dirs: Dict[str, Path], root: Path, manifest: Dict, used_assets: set) -> bool:
        tag = fmt
        sg = ScriptGenerator(self.s, self.llm)
        try:
            script, fc = self._run(f"script_{tag}", sg.generate, req.topic, req.niche, fmt, research, target,
                                   self.s.content.script_source, self._texts)
        except ScriptError as exc:
            manifest["outputs"][fmt] = {"status": "failed", "error": str(exc)}
            return False
        (dirs["scripts"] / f"script_{fmt}.json").write_text(script.model_dump_json(indent=2))
        (dirs["scripts"] / f"script_{fmt}.txt").write_text(_script_text(script), encoding="utf-8")
        (dirs["research"] / f"fact_check_{fmt}.json").write_text(json.dumps(fc, indent=2))
        if not fc["passed"]:
            log.error("fact-check failed for %s script: %s", fmt, fc["issues"])
            manifest["outputs"][fmt] = {"status": "failed", "error": "fact-check failed", "issues": fc["issues"]}
            return False
        sb: Storyboard = self._run(f"storyboard_{tag}", StoryboardGenerator().build, script, renderer.profile)
        audios, ls, hist = self._run(f"narration_{tag}", self.narrate, tts, sb, dirs["audio"] / fmt, target, rng)
        lead, tail = self.s.tts.scene_lead_in_s, self.s.tts.scene_tail_s
        timings = plan_timeline(sb, audios, sb.fps, lead, tail)
        for sc, tm in zip(sb.scenes, timings):
            sc.duration = round(tm.duration, 3)
        sb_name = f"storyboard_{'vertical' if renderer.profile.is_vertical else 'horizontal'}.json"
        (dirs["storyboards"] / sb_name).write_text(sb.model_dump_json(indent=2))
        (dirs["audio"] / f"narration_{fmt}.json").write_text(json.dumps(
            {"length_scale": ls, "fit_history_s": hist, "voice": tts.voice_report(),
             "scenes": {k: v.to_json() for k, v in audios.items()}}, indent=1))
        # narration preview (first scenes) + narration QC, before spending time on video rendering
        _write_preview(audios, [sc.scene_id for sc in sb.scenes[:3]], dirs["audio"] / f"preview_{fmt}.wav")
        nqc = self._run(f"narration_qc_{tag}", narration_qc, audios, {sc.scene_id: sc.duration for sc in sb.scenes},
                        self.s.tts.asr_check, 0 if fmt == "short" else 12, critical=False) or {"passed": True,
                                                                                               "checks": []}
        manifest["narration_qc"][fmt] = nqc
        (dirs["audio"] / f"narration_qc_{fmt}.json").write_text(json.dumps(nqc, indent=2))
        rev = self._run(f"review_{tag}", story_review, script, sb, {sc.scene_id: sc.duration for sc in sb.scenes},
                        critical=False) or {"passed": True, "checks": []}
        manifest["review"][fmt] = rev
        (dirs["review"] / f"storytelling_{fmt}.json").write_text(json.dumps(rev, indent=2, ensure_ascii=False))
        out = root / out_name
        srt = dirs["subtitles"] / f"{out_name.rsplit('.', 1)[0]}.srt"
        res = self._run(f"render_{tag}", renderer.render, sb, audios, out, dirs["work"], srt)
        qc = self._run(f"qc_{tag}", check_video, out, renderer.profile.width, renderer.profile.height,
                       renderer.profile.fps, rng, self.s.audio.target_lufs, srt)
        manifest["qc"][fmt] = qc
        for sc in sb.scenes:
            used_assets.update(o.asset for o in sc.objects)
            used_assets.update(i.asset for i in sc.items if i.asset)
        starts = {tm.scene_id: tm.start for tm in res.timings}
        pack_dir = sg.pack_dir(req.topic)
        meta = self._run(f"metadata_{tag}", SEOGenerator(self.s, self.llm).generate, script, sb, research, starts,
                         pack_dir, critical=False)
        thumbs: List[str] = []
        if meta:
            write_metadata(meta, dirs["metadata"], f"metadata_{fmt}")
        if req.thumbnail:
            concepts = self._concepts(meta, sb, req.topic)
            shutil.rmtree(dirs["thumbnails"] / fmt, ignore_errors=True)   # no stale thumbnails from an earlier run
            paths = self._run(f"thumbnail_{tag}", render_thumbnails, concepts, dirs["thumbnails"] / fmt,
                              sb.character, critical=False) or []
            thumbs = [str(p.relative_to(root)) for p in paths]
        block = self.s.content.block_on_review_fail
        reasons = [f"technical: {c['check']} (got {c.get('value')}, expected {c.get('expected')})" for c in qc["checks"]
                   if not c["passed"]]
        reasons += [f"voice: {c['check']} ({c['detail']})" for c in nqc["checks"]
                    if not c["passed"] and c.get("severity") == "hard"]
        if block:
            reasons += [f"{c['area']}: {c['check']} ({c['detail']})" for c in rev["checks"] if c["level"] == "fail"]
        passed = not reasons
        report_md = write_quality_report(dirs["review"] / f"quality_report_{fmt}.md", req.topic, fmt, out_name,
                                         nqc, rev, qc, tts.voice_report(), passed, reasons)
        manifest["outputs"][fmt] = {
            "status": "rendered" if passed else "qc_failed", "video": out_name,
            "quality_report": str(report_md.relative_to(root)), "failed_checks": reasons,
            "theme": sb.theme,
            "subtitles": str(srt.relative_to(root)), "duration_s": round(res.duration, 2), "frames": res.frames,
            "scenes": len(sb.scenes), "script_source": script.source, "script_words": script.word_count,
            "length_scale": round(ls, 3), "render_seconds": res.render_seconds, "audio_mix": res.audio_report,
            "loudness_pre_norm": res.loudness, "thumbnails": thumbs,
            "storyboard": f"storyboards/{sb_name}", "storyboard_notes": sb.notes,
            "fact_check_warnings": len(fc["warnings"]),
        }
        return passed

    @staticmethod
    def _concepts(meta: Optional[Dict], sb: Storyboard, topic: str) -> List[ThumbnailConcept]:
        am = get_asset_manager()
        mains = [o.asset for sc in sb.scenes for o in sc.objects if o.role == "main"]
        main = mains[0] if mains else am.best_match(topic)
        alt = next((a for a in mains[1:] if a != main), None)
        cs = (meta or {}).get("thumbnail_concepts") or []
        out: List[ThumbnailConcept] = []
        for i, c in enumerate(cs[:2]):
            asset = c.get("asset") or am.best_match(c.get("main_visual", topic), main)
            expr = c.get("expression", "surprised")
            from src.animation.expression_engine import load_expressions
            expr = expr if expr in load_expressions() else "surprised"
            out.append(ThumbnailConcept(c.get("name", f"concept{i + 1}"), c.get("text", topic)[:28], asset, expr,
                                        "surprised" if i == 0 else "point_forward",
                                        ("burst_purple", "burst_teal")[i % 2], ("yellow", "orange")[i % 2],
                                        c.get("rationale", "")))
        return out or default_concepts(topic, main, alt)

    def _licenses(self, tts: TTSEngine) -> Dict:
        return {"narration_voice": tts.provider.license_note, "music": MUSIC_LICENSE, "sound_effects": SFX_LICENSE,
                "fonts": {"Luckiest Guy": "Apache-2.0", "Lilita One": "SIL OFL 1.1", "Patrick Hand": "SIL OFL 1.1"},
                "visual_assets": "Original Curious Minds SVG artwork (see assets/asset_licenses.json)"}

    def _copy_assets(self, used: set, dest: Path, manifest: Dict) -> None:
        am = get_asset_manager()
        lic = {}
        for a in sorted(used):
            if am.exists(a):
                rec = am.record(a)
                shutil.copy2(am.root / rec.file, dest / Path(rec.file).name)
                lic[a] = rec.license
        (dest / "asset_licenses.json").write_text(json.dumps(lic, indent=2))
        manifest["assets_used"] = sorted(used)


def _write_preview(audios: Dict[str, SceneAudio], ids: List[str], path: Path) -> None:
    """Concatenate the first scenes' narration into a quick listening preview."""
    import wave
    import numpy as np
    chunks, sr = [], None
    for sid in ids:
        a = audios.get(sid)
        if a is None:
            continue
        with wave.open(a.wav_path) as w:
            sr = w.getframerate()
            chunks += [np.frombuffer(w.readframes(w.getnframes()), np.int16), np.zeros(int(sr * 0.5), np.int16)]
    if not chunks:
        return
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.concatenate(chunks).tobytes())


def _script_text(script: Script) -> str:
    out = [f"{script.title}", f"Topic: {script.topic} | Format: {script.format} | Source: {script.source}",
           f"Words: {script.word_count}", ""]
    for sec in script.sections:
        out.append(f"## {sec.title}")
        for b in sec.beats:
            out.append(f"[{b.id}{' · ' + b.role if b.role else ''}] {b.narration}")
        out.append("")
    return "\n".join(out)
