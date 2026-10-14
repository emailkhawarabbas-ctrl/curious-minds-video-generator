"""Thin, safe wrappers around the ffmpeg / ffprobe executables (no shell=True)."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

log = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    pass


def require_binaries() -> None:
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        raise FFmpegError(f"missing required executables: {', '.join(missing)} (install FFmpeg)")


def run(cmd: Sequence[str], timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    log.debug("exec: %s", " ".join(map(str, cmd)))
    proc = subprocess.run(list(map(str, cmd)), capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise FFmpegError(f"command failed ({proc.returncode}): {cmd[0]} ...\n{tail}")
    return proc


@dataclass
class StreamInfo:
    codec_type: str
    codec_name: str
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    pix_fmt: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    duration: Optional[float] = None
    nb_frames: Optional[int] = None
    color_space: Optional[str] = None


@dataclass
class MediaInfo:
    path: Path
    format_name: str
    duration: float
    size_bytes: int
    streams: List[StreamInfo] = field(default_factory=list)

    @property
    def video(self) -> Optional[StreamInfo]:
        return next((s for s in self.streams if s.codec_type == "video"), None)

    @property
    def audio(self) -> Optional[StreamInfo]:
        return next((s for s in self.streams if s.codec_type == "audio"), None)


def _rate(text: Optional[str]) -> Optional[float]:
    if not text or text in ("0/0",):
        return None
    if "/" in text:
        n, d = text.split("/")
        return float(n) / float(d) if float(d) else None
    return float(text)


def probe(path: Path, count_frames: bool = False) -> MediaInfo:
    path = Path(path)
    if not path.exists():
        raise FFmpegError(f"file not found: {path}")
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    if count_frames:
        cmd += ["-count_packets"]
    proc = run(cmd + [str(path)], timeout=120)
    data = json.loads(proc.stdout)
    streams = []
    for s in data.get("streams", []):
        nb = s.get("nb_read_packets") or s.get("nb_frames")
        streams.append(StreamInfo(
            codec_type=s.get("codec_type", ""), codec_name=s.get("codec_name", ""),
            width=s.get("width"), height=s.get("height"),
            fps=_rate(s.get("avg_frame_rate")) if s.get("codec_type") == "video" else None,
            pix_fmt=s.get("pix_fmt"),
            sample_rate=int(s["sample_rate"]) if s.get("sample_rate") else None,
            channels=s.get("channels"),
            duration=float(s["duration"]) if s.get("duration") else None,
            nb_frames=int(nb) if nb else None,
            color_space=s.get("color_space"),
        ))
    fmt = data.get("format", {})
    return MediaInfo(path=path, format_name=fmt.get("format_name", ""),
                     duration=float(fmt.get("duration", 0.0)),
                     size_bytes=int(fmt.get("size", 0)), streams=streams)


def audio_duration(path: Path) -> float:
    return probe(path).duration
