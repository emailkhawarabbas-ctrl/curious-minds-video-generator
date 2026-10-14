"""Automated quality control of rendered outputs (never trust, always verify).

Checks (each recorded as pass/fail with the measured value):
  * file exists and is non-trivial
  * container/codec: H.264 video (yuv420p) + AAC audio
  * resolution and frame rate match the profile
  * duration within the requested range
  * audio/video stream durations agree (sync)
  * no blank frames (sampled 2 fps, low-res luminance variance)
  * frame-to-frame motion exists (it is an animation, not a still)
  * integrated loudness near the target
  * SRT: parses, monotonic, no overlaps, ends within the video
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.utils.ffmpeg import FFmpegError, probe


def _check(name: str, ok: bool, value, expected) -> Dict:
    return {"check": name, "passed": bool(ok), "value": value, "expected": expected}


def sample_frames(path: Path, fps: float = 2.0, width: int = 96) -> np.ndarray:
    """Grey low-res frames sampled at `fps` -> array (n, h, w)."""
    info = probe(path)
    v = info.video
    if v is None:
        return np.zeros((0, 1, 1))
    h = int(round(width * v.height / v.width / 2) * 2)
    proc = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-vf",
                           f"fps={fps},scale={width}:{h}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                          capture_output=True, timeout=900)
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.decode(errors="ignore")[-500:])
    data = np.frombuffer(proc.stdout, np.uint8)
    n = len(data) // (width * h)
    return data[: n * width * h].reshape(n, h, width).astype(np.float32)


def measure_loudness(path: Path) -> Optional[float]:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0", "-af",
                           "ebur128", "-f", "null", "-"], capture_output=True, text=True, timeout=900)
    m = re.findall(r"I:\s+(-?\d+(?:\.\d+)?) LUFS", proc.stderr)
    return float(m[-1]) if m else None


def parse_srt(path: Path) -> List[Tuple[float, float, str]]:
    def ts(s: str) -> float:
        h, m, rest = s.split(":")
        sec, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000
    out = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            raise ValueError(f"malformed SRT block: {block[:80]!r}")
        a, b = [x.strip() for x in lines[1].split("-->")]
        out.append((ts(a), ts(b), " ".join(lines[2:])))
    return out


def check_video(path: Path, width: int, height: int, fps: int, duration_range: Tuple[float, float],
                target_lufs: float = -14.0, srt: Optional[Path] = None) -> Dict:
    checks: List[Dict] = []
    path = Path(path)
    exists = path.exists() and path.stat().st_size > 50_000
    checks.append(_check("file_exists", exists, path.stat().st_size if path.exists() else 0, "> 50 kB"))
    if not exists:
        return {"file": str(path), "passed": False, "checks": checks}
    info = probe(path, count_frames=True)
    v, a = info.video, info.audio
    checks.append(_check("video_stream_h264", bool(v and v.codec_name == "h264"), v.codec_name if v else None, "h264"))
    checks.append(_check("pixel_format", bool(v and v.pix_fmt == "yuv420p"), v.pix_fmt if v else None, "yuv420p"))
    checks.append(_check("audio_stream_aac", bool(a and a.codec_name == "aac"), a.codec_name if a else None, "aac"))
    checks.append(_check("resolution", bool(v and (v.width, v.height) == (width, height)),
                         f"{v.width}x{v.height}" if v else None, f"{width}x{height}"))
    checks.append(_check("frame_rate", bool(v and v.fps and abs(v.fps - fps) < 0.01), v.fps if v else None, fps))
    lo, hi = duration_range
    checks.append(_check("duration_in_range", lo <= info.duration <= hi, round(info.duration, 2), [lo, hi]))
    if v and a and v.duration and a.duration:
        diff = abs(v.duration - a.duration)
        checks.append(_check("av_sync_durations", diff <= 0.1, round(diff, 3), "<= 0.1 s"))
    if v and v.nb_frames:
        exp = info.duration * fps
        checks.append(_check("frame_count", abs(v.nb_frames - exp) <= 2, v.nb_frames, round(exp)))
    checks.append(_check("color_space_bt709", bool(v and v.color_space == "bt709"), v.color_space if v else None,
                         "bt709"))
    frames = sample_frames(path)
    if len(frames):
        stds = frames.reshape(len(frames), -1).std(axis=1)
        blank = int((stds < 3.0).sum())
        checks.append(_check("no_blank_frames", blank == 0, blank, 0))
        diffs = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2)) if len(frames) > 1 else np.zeros(1)
        moving = float((diffs > 0.15).mean())
        checks.append(_check("animated_motion", moving > 0.85, round(moving, 3), "> 0.85 of sampled steps change"))
        longest_still = 0
        run_len = 0
        for d in diffs:
            run_len = run_len + 1 if d <= 0.15 else 0
            longest_still = max(longest_still, run_len)
        checks.append(_check("no_frozen_video", longest_still < 6, longest_still / 2.0, "< 3 s without motion"))
    lufs = measure_loudness(path)
    checks.append(_check("loudness_lufs", lufs is not None and abs(lufs - target_lufs) <= 1.5, lufs,
                         f"{target_lufs} ± 1.5"))
    if srt is not None:
        try:
            cues = parse_srt(srt)
            mono = all(cues[i][0] <= cues[i + 1][0] for i in range(len(cues) - 1))
            overlap = sum(1 for i in range(len(cues) - 1) if cues[i][1] > cues[i + 1][0] + 1e-3)
            checks.append(_check("srt_valid", bool(cues) and mono, len(cues), "> 0 monotonic cues"))
            checks.append(_check("srt_no_overlaps", overlap == 0, overlap, 0))
            checks.append(_check("srt_within_video", bool(cues) and cues[-1][1] <= info.duration + 0.05,
                                 cues[-1][1] if cues else None, f"<= {round(info.duration, 2)}"))
        except Exception as exc:  # noqa: BLE001
            checks.append(_check("srt_valid", False, str(exc), "parsable SRT"))
    return {"file": str(path), "passed": all(c["passed"] for c in checks), "duration": round(info.duration, 3),
            "size_mb": round(info.size_bytes / 1e6, 2), "checks": checks}
