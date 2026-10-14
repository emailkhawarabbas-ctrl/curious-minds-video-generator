"""Video rendering pipeline.

  storyboard + per-scene narration
      -> timeline (scene durations from *actual* audio, snapped to whole frames)
      -> parallel scene workers: Cairo frames -> raw BGRA pipe -> libx264 segment
      -> lossless concat (stream copy)
      -> audio mix (narration + SFX + ducked music) -> two-pass loudnorm -> AAC
      -> MP4 (H.264 High, yuv420p, BT.709, 30 fps, faststart)

Scenes are independent (transitions are cover/reveal halves), so they render in
parallel processes and the result is deterministic.
"""
from __future__ import annotations

import json
import logging
import math
import multiprocessing as mp
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from src.audio.mixer import NarrationClip, SfxEvent, mix_episode
from src.audio.tts_engine import SceneAudio, envelope_for
from src.config.settings import RenderProfile, Settings
from src.content.models import Storyboard
from src.rendering.subtitle_engine import (CapWord, CaptionChunk, burn_chunks, scene_chunks, srt_chunks,
                                           write_srt)
from src.utils.ffmpeg import FFmpegError, run

log = logging.getLogger(__name__)


@dataclass
class SceneTiming:
    scene_id: str
    start: float          # episode time (s)
    frames: int
    fps: int
    lead_in: float        # narration starts this long after the scene start

    @property
    def duration(self) -> float:
        return self.frames / self.fps


@dataclass
class RenderResult:
    video_path: Path
    srt_path: Path
    duration: float
    frames: int
    timings: List[SceneTiming]
    audio_report: Dict
    render_seconds: float
    segment_stats: List[Dict] = field(default_factory=list)
    loudness: Dict = field(default_factory=dict)


def plan_timeline(storyboard: Storyboard, audios: Dict[str, SceneAudio], fps: int, lead: float,
                  tail: float) -> List[SceneTiming]:
    out, t = [], 0.0
    for sc in storyboard.scenes:
        a = audios[sc.scene_id]
        d = max(1.6, lead + a.duration + tail)
        frames = int(math.ceil(d * fps))
        out.append(SceneTiming(sc.scene_id, round(t, 4), frames, fps, lead))
        t += frames / fps
    return out


def episode_words(timings: Sequence[SceneTiming], audios: Dict[str, SceneAudio]) -> List[CapWord]:
    words: List[CapWord] = []
    for tm in timings:
        for w in audios[tm.scene_id].words:
            words.append(CapWord(w.word, tm.start + tm.lead_in + w.start, tm.start + tm.lead_in + w.end))
    return words


# --------------------------------------------------------------------------- worker
def _render_segment(job: Dict) -> Dict:
    """Runs in a worker process: render one scene to an H.264 segment."""
    import src  # noqa: F401  (fontconfig bootstrap in the child)
    import cairo

    from src.animation.scene_engine import LayoutContext, WordTiming, compose_scene
    from src.animation.transition_engine import coverage, draw_transition
    from src.content.models import Scene
    from src.rendering.subtitle_engine import CaptionRenderer

    t0 = time.time()
    scene = Scene.model_validate(job["scene"])
    p = job["profile"]
    W, H, fps, frames = p["width"], p["height"], p["fps"], job["frames"]
    dur = frames / fps
    words = [WordTiming(w["text"], w["start"], w["end"]) for w in job["words"]]
    L = LayoutContext(W=W, H=H, vertical=H > W, safe_top=p["safe"]["top"], safe_bottom=p["safe"]["bottom"],
                      safe_left=p["safe"]["left"], safe_right=p["safe"]["right"],
                      caption_top=job["caption_top"], caption_bottom=job["caption_bottom"], duration=dur,
                      words=words, speech_start=job["lead_in"], speech_end=job["speech_end"], seed=job["seed"],
                      brand_name=job["brand_name"], tagline=job["tagline"])
    comp = compose_scene(scene, L, envelope=job["envelope"], fps=fps, char_id=job["character"])
    caps = None
    if job["burn_subtitles"]:
        chunks = [CaptionChunk(c["start"], c["end"], [CapWord(**w) for w in c["words"]]) for c in job["captions"]]
        caps = CaptionRenderer(chunks, W, H, H > W, job["caption_center"], p["safe"]["left"], p["safe"]["right"])
    out = Path(job["out"])
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{W}x{H}",
           "-r", str(fps), "-i", "-", "-frames:v", str(frames),
           "-vf", "scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv420p",
           "-c:v", "libx264", "-preset", job["preset"], "-crf", str(job["crf"]), "-profile:v", "high",
           "-threads", str(job.get("threads", 2)),
           "-g", str(fps * 2), "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-color_range", "tv", "-video_track_timescale", "15360", "-an", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surf)
    blank = 0
    sample_every = max(1, fps // 2)
    try:
        preroll = job.get("preroll", 0.0)
        for i in range(frames):
            t = i / fps
            ctx.save()
            comp.draw(ctx, t + preroll)
            if caps:
                caps.draw(ctx, t)
            kind, cover = coverage(t, dur, scene.transition_in, scene.transition_out)
            if kind != "cut":
                draw_transition(ctx, kind, cover, W, H, seed=job["seed"])
            ctx.restore()
            surf.flush()
            data = surf.get_data()
            if i % sample_every == 0:
                arr = np.frombuffer(data, np.uint8)[::4 * 97]
                if arr.std() < 2.0:
                    blank += 1
            proc.stdin.write(bytes(data))
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="ignore")
        rc = proc.wait()
    except BrokenPipeError:
        err = proc.stderr.read().decode(errors="ignore")
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed for scene {scene.scene_id}: {err[-800:]}")
    events = [(job["start"] + t, name) for t, name in comp.events]
    return {"scene_id": scene.scene_id, "segment": str(out), "frames": frames,
            "seconds": round(time.time() - t0, 2), "ms_per_frame": round((time.time() - t0) / frames * 1000, 2),
            "blank_samples": blank, "events": events}


# --------------------------------------------------------------------------- orchestration
class EpisodeRenderer:
    def __init__(self, settings: Settings, profile_name: str):
        self.s = settings
        self.profile_name = profile_name
        self.profile: RenderProfile = settings.profile(profile_name)

    def caption_band(self) -> Dict[str, float]:
        p = self.profile
        center = p.height * p.caption_zone_y
        band = 240 if p.is_vertical else 140
        return {"center": center, "top": center - band / 2, "bottom": center + band / 2}

    def render(self, storyboard: Storyboard, audios: Dict[str, SceneAudio], out_path: Path, work_dir: Path,
               srt_path: Path, extra_sfx: Sequence[SfxEvent] = ()) -> RenderResult:
        t_start = time.time()
        p, fps = self.profile, self.profile.fps
        if (storyboard.width, storyboard.height) != (p.width, p.height):
            raise ValueError(f"storyboard {storyboard.width}x{storyboard.height} does not match profile "
                             f"{self.profile_name} {p.width}x{p.height}")
        lead, tail = self.s.tts.scene_lead_in_s, self.s.tts.scene_tail_s
        timings = plan_timeline(storyboard, audios, fps, lead, tail)
        total_frames = sum(tm.frames for tm in timings)
        duration = total_frames / fps
        words = episode_words(timings, audios)
        write_srt(srt_chunks(words), srt_path)
        burn = burn_chunks(words, p.is_vertical)
        band = self.caption_band()
        seg_dir = work_dir / f"segments_{self.profile_name}"
        seg_dir.mkdir(parents=True, exist_ok=True)
        jobs = []
        for idx, (sc, tm) in enumerate(zip(storyboard.scenes, timings)):
            a = audios[sc.scene_id]
            samples = _read_int16(a.wav_path)
            env = envelope_for(samples, a.sample_rate, fps, tm.frames, tm.lead_in)
            sw = [{"text": w.word, "start": tm.lead_in + w.start, "end": tm.lead_in + w.end} for w in a.words]
            caps = scene_chunks(burn, tm.start, tm.start + tm.duration)
            jobs.append({
                "scene": json.loads(sc.model_dump_json()), "profile": json.loads(p.model_dump_json()),
                "frames": tm.frames, "start": tm.start, "lead_in": tm.lead_in,
                "speech_end": tm.lead_in + a.duration, "words": sw, "envelope": env,
                "captions": [{"start": c.start, "end": c.end, "words": [asdict(w) for w in c.words]} for c in caps],
                "caption_top": band["top"], "caption_bottom": band["bottom"], "caption_center": band["center"],
                "burn_subtitles": self.s.render.burn_subtitles, "seed": idx * 7 + 3,
                "character": storyboard.character, "brand_name": self.s.brand.name, "tagline": self.s.brand.tagline,
                "crf": self.s.render.crf, "preset": self.s.render.preset,
                "out": str(seg_dir / f"{idx:03d}_{sc.scene_id}.mp4"),
                # the very first frame of an episode should already show the title + mascot
                "preroll": 0.45 if idx == 0 else 0.0,
                "threads": max(1, (os.cpu_count() or 2) // max(1, self.s.render.worker_count())),
            })
        workers = self.s.render.worker_count()
        log.info("[%s] rendering %d scenes, %d frames (%.1f s) with %d workers", self.profile_name, len(jobs),
                 total_frames, duration, workers)
        stats: List[Dict] = []
        order = sorted(range(len(jobs)), key=lambda i: -jobs[i]["frames"])
        if workers > 1:
            ctx = mp.get_context("fork")
            with ctx.Pool(workers, maxtasksperchild=8) as pool:
                for k, r in enumerate(pool.imap_unordered(_render_segment, [jobs[i] for i in order]), 1):
                    stats.append(r)
                    log.info("[%s] scene %s done (%d/%d, %.1f ms/frame)", self.profile_name, r["scene_id"], k,
                             len(jobs), r["ms_per_frame"])
        else:
            for k, i in enumerate(order, 1):
                r = _render_segment(jobs[i])
                stats.append(r)
                log.info("[%s] scene %s done (%d/%d)", self.profile_name, r["scene_id"], k, len(jobs))
        stats.sort(key=lambda r: r["segment"])
        # concat (stream copy)
        list_file = seg_dir / "concat.txt"
        list_file.write_text("".join(f"file '{Path(r['segment']).resolve()}'\n" for r in stats))
        video_only = work_dir / f"video_only_{self.profile_name}.mp4"
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(list_file),
             "-c", "copy", str(video_only)], timeout=600)
        # audio
        clips = [NarrationClip(audios[tm.scene_id].wav_path, tm.start + tm.lead_in) for tm in timings]
        sfx: List[SfxEvent] = list(extra_sfx)
        for sc, tm in zip(storyboard.scenes, timings):
            for cue in sc.sfx:
                t = tm.start + cue.at * tm.duration
                if cue.cue:
                    w = next((w for w in audios[sc.scene_id].words if w.word.lower().startswith(cue.cue.lower())), None)
                    if w:
                        t = tm.start + tm.lead_in + w.start
                sfx.append(SfxEvent(cue.name, t, cue.gain_db))
            if sc.transition_in not in ("cut", "dip_cream"):
                sfx.append(SfxEvent("whoosh", max(0.0, tm.start - 0.3), -4.0))
        for r in stats:
            for t, name in r["events"]:
                sfx.append(SfxEvent(name, t, -5.0))
        mix_wav = work_dir / f"mix_{self.profile_name}.wav"
        audio_report = mix_episode(clips, sfx, duration, storyboard.music_mood, self.s.audio, mix_wav)
        loud = self._mux(video_only, mix_wav, out_path, duration)
        return RenderResult(video_path=out_path, srt_path=srt_path, duration=duration, frames=total_frames,
                            timings=timings, audio_report=audio_report, render_seconds=round(time.time() - t_start, 1),
                            segment_stats=stats, loudness=loud)

    def _mux(self, video: Path, wav: Path, out: Path, duration: float) -> Dict:
        a = self.s.audio
        target = f"I={a.target_lufs}:TP={a.true_peak_db}:LRA=11"
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(wav), "-af", f"loudnorm={target}:print_format=json",
                               "-f", "null", "-"], capture_output=True, text=True, timeout=600)
        m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
        if not m:
            raise FFmpegError("loudnorm measurement failed")
        meas = json.loads(m.group())
        af = (f"loudnorm={target}:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
              f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:"
              f"offset={meas['target_offset']}:linear=true,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo")
        out.parent.mkdir(parents=True, exist_ok=True)
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(wav), "-map", "0:v:0", "-map", "1:a:0",
             "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", self.s.render.audio_bitrate, "-ar", "48000",
             "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out)], timeout=900)
        return {"input_i": float(meas["input_i"]), "input_tp": float(meas["input_tp"]), "target_i": a.target_lufs}


def _read_int16(path: str) -> np.ndarray:
    import wave
    with wave.open(path) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16)


