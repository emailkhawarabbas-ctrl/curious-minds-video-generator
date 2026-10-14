"""Procedural background-music generator (original, royalty-free by construction).

Moods:
  * curious — light marimba arpeggios, warm bass, soft shaker (I–vi–IV–V), 100 BPM
  * dreamy  — soft pads, music-box bells, slow bass (Imaj7–vi7–IVmaj7–V), 78 BPM
  * upbeat  — brighter plucks with kick + shaker, 112 BPM
  * calm    — pads and sparse bells, 70 BPM

The music is generated at the exact length required, with fades, in stereo.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

SR = 44100
LICENSE = "Original procedural composition (Curious Minds), no third-party material"


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


MOODS: Dict[str, Dict] = {
    "curious": {"bpm": 100, "chords": [[60, 64, 67, 72], [57, 60, 64, 69], [53, 57, 60, 65], [55, 59, 62, 67]],
                "arp": "marimba", "pad": 0.10, "drums": "shaker", "bells": 0.0, "arp_gain": 0.30},
    "dreamy": {"bpm": 78, "chords": [[60, 64, 67, 71], [57, 60, 64, 67], [53, 57, 60, 64], [55, 59, 62, 65]],
               "arp": "musicbox", "pad": 0.22, "drums": None, "bells": 0.10, "arp_gain": 0.22},
    "upbeat": {"bpm": 112, "chords": [[60, 64, 67, 72], [55, 59, 62, 67], [57, 60, 64, 69], [53, 57, 60, 65]],
               "arp": "pluck", "pad": 0.08, "drums": "full", "bells": 0.0, "arp_gain": 0.28},
    "calm": {"bpm": 70, "chords": [[60, 64, 67, 71], [53, 57, 60, 64], [57, 60, 64, 67], [55, 59, 62, 65]],
             "arp": "musicbox", "pad": 0.25, "drums": None, "bells": 0.06, "arp_gain": 0.16},
}


def _note(freq: float, dur: float, kind: str) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    if kind == "marimba":
        y = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * freq * 4 * t) * np.exp(-t * 30)
        env = np.exp(-t * 6.0)
    elif kind == "musicbox":
        y = np.sin(2 * np.pi * freq * 2 * t) + 0.3 * np.sin(2 * np.pi * freq * 6 * t) * np.exp(-t * 8)
        env = np.exp(-t * 3.0)
    elif kind == "pluck":
        y = np.sign(np.sin(2 * np.pi * freq * t)) * 0.3 + np.sin(2 * np.pi * freq * t)
        env = np.exp(-t * 9.0)
    elif kind == "bass":
        y = np.sin(2 * np.pi * freq * t) + 0.2 * np.sin(2 * np.pi * freq * 2 * t)
        env = np.minimum(1, t / 0.01) * np.exp(-t * 1.6)
    elif kind == "pad":
        y = sum(np.sin(2 * np.pi * freq * d * t + p) for d, p in ((1.0, 0), (1.004, 1.3), (0.996, 2.1))) / 3
        env = np.minimum(1, t / (dur * 0.35)) * np.minimum(1, (dur - t) / (dur * 0.35))
    else:
        y, env = np.sin(2 * np.pi * freq * t), np.exp(-t * 4)
    attack = np.minimum(1, t / 0.006)
    release = np.minimum(1, (dur - t) / 0.03)          # no clicks at note ends
    return (y * env * attack * release).astype(np.float32)


def _drum(kind: str, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if kind == "shaker":
        n = int(SR * 0.08)
        t = np.arange(n) / SR
        noise = rng.uniform(-1, 1, n)
        hp = np.diff(noise, prepend=0)
        return (hp * np.exp(-t * 60)).astype(np.float32) * 0.5
    if kind == "kick":
        n = int(SR * 0.3)
        t = np.arange(n) / SR
        f = 45 + 90 * np.exp(-t * 35)
        return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)).astype(np.float32)
    return np.zeros(1, np.float32)


def _add(buf: np.ndarray, x: np.ndarray, start: int, gain: float, pan: float = 0.0) -> None:
    if start >= buf.shape[0]:
        return
    end = min(buf.shape[0], start + len(x))
    seg = x[: end - start] * gain
    buf[start:end, 0] += seg * (1 - max(0.0, pan))
    buf[start:end, 1] += seg * (1 + min(0.0, pan))


def generate_music(duration: float, mood: str = "curious", seed: int = 7) -> np.ndarray:
    """Return float32 stereo array (n, 2) at 44.1 kHz, peak-normalised to about -6 dBFS."""
    cfg = MOODS.get(mood, MOODS["curious"])
    rng = np.random.default_rng(seed)
    beat = 60.0 / cfg["bpm"]
    bar = beat * 4
    n = int(SR * (duration + 2))
    buf = np.zeros((n, 2), np.float32)
    chords: List[List[int]] = cfg["chords"]
    n_bars = int(np.ceil((duration + 2) / bar))
    patterns = [[0, 1, 2, 3, 2, 1, 2, 3], [0, 2, 1, 3, 2, 3, 1, 2], [0, 1, 2, 3, 3, 2, 1, 2]]
    for b in range(n_bars):
        chord = chords[b % len(chords)]
        t0 = b * bar
        s0 = int(t0 * SR)
        # bass on beats 1 and 3
        for k in (0, 2):
            _add(buf, _note(midi_hz(chord[0] - 24), beat * 1.8, "bass"), int((t0 + k * beat) * SR), 0.32)
        # pad
        if cfg["pad"] > 0:
            for m in chord[:3]:
                _add(buf, _note(midi_hz(m - 12), bar * 1.02, "pad"), s0, cfg["pad"] / 2, pan=0.0)
        # arpeggio (8th notes) with gentle variation every 4 bars
        pat = patterns[(b // 4) % len(patterns)]
        for k, idx in enumerate(pat):
            if cfg["arp"] == "musicbox" and k % 2 == 1 and rng.random() < 0.5:
                continue
            m = chord[idx] + (12 if (b % 8 >= 4 and k in (3, 7)) else 0)
            st = int((t0 + k * beat / 2) * SR)
            _add(buf, _note(midi_hz(m), beat * 1.5, cfg["arp"]), st, cfg["arp_gain"] * (0.85 + 0.15 * rng.random()),
                 pan=0.35 * np.sin(k))
        # bells sprinkle
        if cfg["bells"] > 0 and b % 2 == 1:
            m = chord[rng.integers(0, 4)] + 12
            _add(buf, _note(midi_hz(m), bar, "musicbox"), int((t0 + beat * 2.5) * SR), cfg["bells"], pan=-0.4)
        # drums
        if cfg["drums"]:
            for k in range(8):
                _add(buf, _drum("shaker", b * 8 + k), int((t0 + k * beat / 2) * SR), 0.10 if k % 2 else 0.06,
                     pan=0.3)
            if cfg["drums"] == "full":
                for k in (0, 2):
                    _add(buf, _drum("kick", b), int((t0 + k * beat) * SR), 0.35)
    out = buf[: int(SR * duration)]
    fade_in, fade_out = int(SR * 1.0), int(SR * 2.5)
    out[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    out[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    peak = np.max(np.abs(out)) + 1e-9
    return (out / peak * 0.5).astype(np.float32)


def describe(mood: str) -> Tuple[str, int]:
    cfg = MOODS.get(mood, MOODS["curious"])
    return mood, cfg["bpm"]
