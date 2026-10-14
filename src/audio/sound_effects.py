"""Procedurally synthesised cartoon sound-effect library.

All effects are generated from scratch with numpy (sine/noise synthesis + envelopes),
so they are original works with no third-party licensing. They are cached as WAV
files in ``assets/sound_effects`` (regenerated if missing).
"""
from __future__ import annotations

import wave
from pathlib import Path
from typing import Callable, Dict

import numpy as np

from src.animation.registry import SFX
from src.config.settings import PROJECT_ROOT

SR = 44100
SFX_DIR = PROJECT_ROOT / "assets" / "sound_effects"
LICENSE = "Original procedural synthesis (Curious Minds), no third-party material"


def _t(d: float) -> np.ndarray:
    return np.arange(int(SR * d)) / SR


def _env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-t / max(decay, 1e-4))


def _tone(freq, d: float, decay: float, harmonics=((1, 1.0),), attack: float = 0.003) -> np.ndarray:
    t = _t(d)
    f = freq(t) if callable(freq) else np.full_like(t, freq)
    ph = 2 * np.pi * np.cumsum(f) / SR
    y = sum(a * np.sin(k * ph) for k, a in harmonics)
    return y * _env(len(t), attack, decay)


def _noise(d: float, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).uniform(-1, 1, int(SR * d))


def _lowpass(x: np.ndarray, alpha: float) -> np.ndarray:
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc += alpha * (v - acc)
        y[i] = acc
    return y


def _pop() -> np.ndarray:
    return _tone(lambda t: 900 * np.exp(-t * 40) + 260, 0.12, 0.035, ((1, 1), (2, 0.3)))


def _whoosh() -> np.ndarray:
    d = 0.55
    n = _noise(d, 1)
    t = _t(d)
    sweep = 0.02 + 0.25 * np.sin(np.pi * t / d) ** 2
    y = np.empty_like(n)
    acc = 0.0
    for i, v in enumerate(n):
        acc += sweep[i] * (v - acc)
        y[i] = acc
    return y * np.sin(np.pi * t / d) ** 1.5 * 2.2


def _ding() -> np.ndarray:
    return _tone(1568, 1.1, 0.35, ((1, 1), (2.76, 0.35), (5.4, 0.12))) + 0.5 * _tone(2093, 1.1, 0.25)


def _sparkle() -> np.ndarray:
    out = np.zeros(int(SR * 0.9))
    rng = np.random.default_rng(3)
    for k in range(9):
        f = 2000 + 2600 * rng.random()
        s = _tone(f, 0.25, 0.06, ((1, 1), (2, 0.2)))
        start = int(SR * (0.06 * k + 0.02 * rng.random()))
        out[start:start + len(s)] += s * (0.9 - 0.07 * k)
    return out


def _boing() -> np.ndarray:
    return _tone(lambda t: 180 + 220 * np.exp(-t * 6) * (1 + 0.35 * np.sin(2 * np.pi * 18 * t)), 0.6, 0.25,
                 ((1, 1), (2, 0.25)))


def _click() -> np.ndarray:
    return _tone(2400, 0.04, 0.008) * 0.8 + _noise(0.04, 5) * _env(int(SR * 0.04), 0.0005, 0.004) * 0.3


def _chime() -> np.ndarray:
    out = np.zeros(int(SR * 1.6))
    for k, f in enumerate((1046.5, 1318.5, 1568.0)):
        s = _tone(f, 1.2, 0.45, ((1, 1), (3, 0.08)))
        st = int(SR * 0.13 * k)
        out[st:st + len(s)] += s * 0.7
    return out


def _tick() -> np.ndarray:
    return _tone(3200, 0.03, 0.006) + _tone(1600, 0.03, 0.01) * 0.4


def _bubble() -> np.ndarray:
    out = np.zeros(int(SR * 0.7))
    for k in range(4):
        s = _tone(lambda t, k=k: 400 + 120 * k + 900 * t / 0.12, 0.12, 0.05)
        st = int(SR * (0.13 * k))
        out[st:st + len(s)] += s * 0.7
    return out


def _magic() -> np.ndarray:
    d = 1.4
    y = _tone(lambda t: 300 * 2 ** (2.5 * t / d), d, 0.8, ((1, 1), (2, 0.3), (3, 0.1)), attack=0.3) * 0.6
    sp = _sparkle()
    n = min(len(y), len(sp))
    y[:n] += sp[:n] * 0.5
    return y


def _snore() -> np.ndarray:
    d = 1.2
    t = _t(d)
    n = _lowpass(_noise(d, 9), 0.05) * 6
    body = np.sin(2 * np.pi * 70 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 23 * t))
    env = np.sin(np.pi * t / d) ** 2
    return (n + body * 0.5) * env


def _heartbeat() -> np.ndarray:
    out = np.zeros(int(SR * 1.3))
    for st in (0.0, 0.18, 0.75, 0.93):
        s = _tone(lambda t: 55 + 40 * np.exp(-t * 30), 0.18, 0.05)
        i = int(SR * st)
        out[i:i + len(s)] += s
    return out


def _success() -> np.ndarray:
    out = np.zeros(int(SR * 1.0))
    for k, f in enumerate((523.25, 659.25, 783.99, 1046.5)):
        s = _tone(f, 0.5, 0.18, ((1, 1), (2, 0.25)))
        st = int(SR * 0.08 * k)
        out[st:st + len(s)] += s * 0.6
    return out


GENERATORS: Dict[str, Callable[[], np.ndarray]] = {
    "pop": _pop, "whoosh": _whoosh, "ding": _ding, "sparkle": _sparkle, "boing": _boing, "click": _click,
    "chime": _chime, "tick": _tick, "bubble": _bubble, "magic": _magic, "snore": _snore,
    "heartbeat": _heartbeat, "success": _success,
}
assert set(GENERATORS) == set(SFX), "SFX registry and generators out of sync"


def _write(path: Path, y: np.ndarray) -> None:
    y = y / (np.max(np.abs(y)) + 1e-9) * 0.89            # peak -1 dBFS
    fade = min(len(y), int(SR * 0.01))
    y[-fade:] *= np.linspace(1, 0, fade)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((y * 32767).astype(np.int16).tobytes())


def ensure_library() -> Dict[str, Path]:
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, gen in GENERATORS.items():
        p = SFX_DIR / f"{name}.wav"
        if not p.exists():
            _write(p, gen().astype(np.float64))
        paths[name] = p
    return paths


def load_sfx(name: str) -> np.ndarray:
    """Float32 mono samples at 44.1 kHz."""
    p = ensure_library()[name]
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
