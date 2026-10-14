"""Final audio mix: narration timeline + sound effects + ducked music bed.

* narration clips are placed at their scene offsets (never overlapping: each scene's
  narration is shorter than its scene by construction)
* music is generated to length, kept far below the voice, and ducked further while
  narration is active (smooth side-chain style envelope)
* a soft limiter prevents clipping; final loudness normalisation (EBU R128 / -14 LUFS)
  is done by FFmpeg's two-pass ``loudnorm`` when muxing
"""
from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

import numpy as np

from src.audio.music_engine import generate_music
from src.audio.sound_effects import load_sfx
from src.config.settings import AudioSettings

log = logging.getLogger(__name__)
SR = 44100


def db(x: float) -> float:
    return 10 ** (x / 20)


def read_wav_mono(path: str) -> Tuple[np.ndarray, int]:
    with wave.open(path) as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() == 2:
            data = data.reshape(-1, 2).mean(axis=1)
    return data, sr


def resample(x: np.ndarray, sr_in: int, sr_out: int = SR) -> np.ndarray:
    if sr_in == sr_out or x.size == 0:
        return x
    n_out = int(round(len(x) * sr_out / sr_in))
    t_in = np.arange(len(x)) / sr_in
    t_out = np.arange(n_out) / sr_out
    return np.interp(t_out, t_in, x).astype(np.float32)


@dataclass
class NarrationClip:
    path: str
    start: float          # seconds on the episode timeline


@dataclass
class SfxEvent:
    name: str
    time: float
    gain_db: float = 0.0


def _activity(voice: np.ndarray, attack: float = 0.05, release: float = 0.45) -> np.ndarray:
    """0..1 envelope that is ~1 while narration is audible (smoothed)."""
    win = int(SR * 0.03)
    n = len(voice) // win + 1
    pad = np.zeros(n * win, np.float32)
    pad[: len(voice)] = np.abs(voice)
    level = pad.reshape(n, win).max(axis=1)
    active = (level > 0.02).astype(np.float32)
    out = np.zeros_like(active)
    a_k, r_k = 0.03 / attack, 0.03 / release
    acc = 0.0
    for i, v in enumerate(active):
        acc += (a_k if v > acc else r_k) * (v - acc)
        out[i] = acc
    return np.repeat(out, win)[: len(voice)]


def mix_episode(clips: Sequence[NarrationClip], sfx: Sequence[SfxEvent], duration: float, mood: str,
                cfg: AudioSettings, out_wav: Path) -> dict:
    n = int(SR * duration)
    voice = np.zeros(n, np.float32)
    for c in clips:
        x, sr = read_wav_mono(c.path)
        x = resample(x, sr)
        rms = float(np.sqrt(np.mean(x[np.abs(x) > 0.01] ** 2))) if np.any(np.abs(x) > 0.01) else 0.0
        if rms > 0:
            x = x * (db(-18.0) / rms)               # consistent speech level across scenes
        s = int(c.start * SR)
        e = min(n, s + len(x))
        if e > s:
            voice[s:e] += x[: e - s]
    act = _activity(voice)
    music = generate_music(duration, mood)
    music_gain = db(cfg.music_gain_db) * (1 - act * (1 - db(cfg.music_duck_db)))
    music *= music_gain[:, None]
    fx = np.zeros(n, np.float32)
    placed: List[Tuple[float, str]] = []
    for ev in sorted(sfx, key=lambda e: e.time):
        if any(abs(ev.time - t) < 0.18 for t, _ in placed):   # avoid stacking effects
            continue
        x = load_sfx(ev.name) * db(cfg.sfx_gain_db + ev.gain_db)
        s = int(max(0.0, ev.time) * SR)
        e = min(n, s + len(x))
        if e > s:
            fx[s:e] += x[: e - s]
            placed.append((ev.time, ev.name))
    mixed = np.stack([voice, voice], axis=1) + music + np.stack([fx, fx], axis=1) * 0.9
    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    # soft limiter above -1 dBFS
    thr = db(-1.0)
    over = np.abs(mixed) > thr
    mixed[over] = np.sign(mixed[over]) * (thr + (1 - thr) * np.tanh((np.abs(mixed[over]) - thr) / (1 - thr)))
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(mixed, -1, 1) * 32767).astype(np.int16).tobytes())
    voice_rms = float(np.sqrt(np.mean(voice[np.abs(voice) > 0.01] ** 2))) if np.any(np.abs(voice) > 0.01) else 0.0
    music_rms = float(np.sqrt(np.mean(music ** 2)))
    return {"duration": duration, "sfx_placed": len(placed), "peak_before_limiter": round(peak, 3),
            "voice_rms_dbfs": round(20 * np.log10(voice_rms + 1e-9), 1),
            "music_rms_dbfs": round(20 * np.log10(music_rms + 1e-9), 1),
            "music_below_voice_db": round(20 * np.log10((voice_rms + 1e-9) / (music_rms + 1e-9)), 1)}
