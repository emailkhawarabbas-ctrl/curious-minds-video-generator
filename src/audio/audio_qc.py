"""Narration quality control: is the voice clear, clean, complete, expressive and in sync?

Runs on the per-scene narration WAVs *before* the video is rendered (cheap to fix there)
and is written to ``audio/narration_qc_<format>.json`` and the production report.

Checks (hard = fails the video, soft = warning):
  * sample rate >= 22.05 kHz                                    (soft)
  * clipping: < 0.05 % of samples at full scale                 (hard)
  * peak <= -0.5 dBFS                                           (soft)
  * DC offset                                                   (soft)
  * no sentence cut off (energy still high at the end)          (hard)
  * no long dead air inside a scene (> 1.6 s)                   (soft)
  * speech rate 2.0 - 3.6 words/s                               (soft)
  * pitch variation >= 1.6 semitones (monotone detector)        (soft)
  * consistent level across scenes (spread <= 4 dB)             (soft)
  * narration fits its scene (scene duration >= audio)          (hard)
  * intelligibility: Whisper word error rate <= 25 %            (hard when ASR runs; skipped if unavailable)
"""
from __future__ import annotations

import logging
import re
import wave
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

from src.utils.text import spoken_number_token

log = logging.getLogger(__name__)


def read_wav(path: str) -> tuple:
    with wave.open(str(path)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0
    return x, sr


# --------------------------------------------------------------------------- signal metrics
def pitch_track(x: np.ndarray, sr: int, fmin: float = 70.0, fmax: float = 320.0, with_peaks: bool = False):
    """F0 per 10 ms frame (Hz, 0 = unvoiced) by normalised autocorrelation; good enough for prosody stats.

    With ``with_peaks`` also returns the autocorrelation peak per frame (harmonicity: ~1 = clean tone,
    lower = breathy / buzzy / noisy voicing).
    """
    if x.size < sr // 10:
        return (np.zeros(0), np.zeros(0)) if with_peaks else np.zeros(0)
    # analyse at 8 kHz: plenty for male F0 and 3x faster
    step = max(1, sr // 8000)
    y = x[::step]
    fs = sr / step
    win, hop = int(fs * 0.04), int(fs * 0.01)
    lo, hi = int(fs / fmax), int(fs / fmin)
    n = (len(y) - win) // hop
    if n <= 0:
        return (np.zeros(0), np.zeros(0)) if with_peaks else np.zeros(0)
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    frames = y[idx] * np.hanning(win)[None, :]
    energy = np.sqrt((frames ** 2).mean(axis=1))
    gate = max(1e-4, np.percentile(energy, 90) * 0.15)
    spec = np.fft.rfft(frames, n=2 * win, axis=1)
    ac = np.fft.irfft(np.abs(spec) ** 2, axis=1)[:, :win]
    ac /= np.maximum(ac[:, :1], 1e-9)
    seg = ac[:, lo:hi]
    lag = seg.argmax(axis=1) + lo
    peak = seg.max(axis=1)
    f0 = np.where((peak > 0.45) & (energy > gate), fs / lag, 0.0)
    return (f0, np.where(f0 > 0, peak, 0.0)) if with_peaks else f0


def prosody_stats(f0: np.ndarray, peaks: np.ndarray) -> Dict:
    """Phrase-level pitch movement vs. frame-level instability.

    * octave errors (frames > 0.7 octave from the running median) are discarded;
    * ``prosody_std``: std (semitones) of the 50 ms median-smoothed contour — intonation;
    * ``jitter``: median |Δ| between consecutive raw voiced frames (semitones) — roughness / warble;
    * ``harmonicity``: mean autocorrelation peak of voiced frames — tonal clarity.
    """
    v = f0 > 0
    if v.sum() < 20:
        return {"prosody_std": 0.0, "prosody_range": 0.0, "jitter": 0.0, "harmonicity": 0.0, "octave_errors": 0.0}
    med = np.median(f0[v])
    st = np.where(v, 12 * np.log2(np.maximum(f0, 1e-3) / med), np.nan)
    k = 15
    pad = np.pad(st, k, constant_values=np.nan)
    run_med = np.array([np.nanmedian(pad[i:i + 2 * k + 1]) if v[i] else np.nan for i in range(len(st))])
    bad = v & (np.abs(st - run_med) > 8.4)
    good = v & ~bad
    clean = np.where(good, st, np.nan)
    pad = np.pad(clean, 2, constant_values=np.nan)
    smooth = np.array([np.nanmedian(pad[i:i + 5]) if good[i] else np.nan for i in range(len(clean))])
    s = smooth[~np.isnan(smooth)]
    pairs = good[1:] & good[:-1]
    d = np.abs(np.diff(st))[pairs]
    return {"prosody_std": round(float(s.std()), 2) if s.size else 0.0,
            "prosody_range": round(float(np.percentile(s, 95) - np.percentile(s, 5)), 2) if s.size else 0.0,
            "jitter": round(float(np.median(d)), 3) if d.size else 0.0,
            "harmonicity": round(float(peaks[good].mean()), 3),
            "octave_errors": round(float(bad.sum() / max(1, v.sum())), 3)}


def signal_metrics(x: np.ndarray, sr: int) -> Dict:
    if x.size == 0:
        return {"duration": 0.0}
    f0, peaks = pitch_track(x, sr, with_peaks=True)
    voiced = f0[f0 > 0]
    semis = 12 * np.log2(voiced / np.median(voiced)) if voiced.size > 10 else np.zeros(0)
    pros = prosody_stats(f0, peaks) if f0.size else {}
    win = max(1, int(sr * 0.02))
    n = len(x) // win
    rms = np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(axis=1)) if n else np.zeros(1)
    speech = rms[rms > max(1e-4, rms.max() * 0.1)]
    silent = rms < max(1e-4, (np.median(speech) if speech.size else 0) * 0.05)
    longest, run = 0, 0
    for s in silent:
        run = run + 1 if s else 0
        longest = max(longest, run)
    return {
        "duration": round(len(x) / sr, 3),
        "sample_rate": sr,
        "peak_dbfs": round(20 * np.log10(max(1e-9, float(np.abs(x).max()))), 2),
        "clip_ratio": round(float((np.abs(x) >= 0.999).mean()), 6),
        "dc_offset": round(float(x.mean()), 5),
        "speech_rms_dbfs": round(20 * np.log10(max(1e-9, float(np.sqrt((speech ** 2).mean())) if speech.size else 1e-9)), 2),
        "longest_silence_s": round(longest * win / sr, 2),
        "f0_median_hz": round(float(np.median(voiced)), 1) if voiced.size else 0.0,
        "f0_std_semitones": round(float(semis.std()), 2) if semis.size else 0.0,
        "f0_range_semitones": round(float(np.percentile(semis, 95) - np.percentile(semis, 5)), 2) if semis.size else 0.0,
        "voiced_ratio": round(float((f0 > 0).mean()), 3) if f0.size else 0.0,
        **pros,
    }


# --------------------------------------------------------------------------- intelligibility (optional ASR)
_ASR = None


def _asr_model():
    global _ASR
    if _ASR is None:
        from faster_whisper import WhisperModel  # optional dependency
        _ASR = WhisperModel("base.en", device="cpu", compute_type="int8")
    return _ASR


def asr_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _norm_tokens(text: str) -> List[str]:
    out: List[str] = []
    for w in text.split():
        w = spoken_number_token(w) if re.search(r"\d", w) else w
        out += re.findall(r"[a-z']+", w.lower().replace("-", " "))
    return [t.strip("'") for t in out if t.strip("'")]


def word_error_rate(reference: str, hypothesis: str) -> float:
    r, h = _norm_tokens(reference), _norm_tokens(hypothesis)
    if not r:
        return 0.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / len(r)


def transcribe(path: str) -> str:
    segs, _ = _asr_model().transcribe(str(path), language="en", beam_size=1, vad_filter=False)
    return " ".join(s.text.strip() for s in segs)


# --------------------------------------------------------------------------- report
def _check(name: str, passed: bool, detail: str, hard: bool) -> Dict:
    return {"check": name, "passed": bool(passed), "severity": "hard" if hard else "soft", "detail": detail}


def narration_qc(audios: Dict, scene_durations: Optional[Dict[str, float]] = None, asr: str = "auto",
                 asr_scenes: int = 0) -> Dict:
    """QC for a set of SceneAudio objects. ``asr_scenes`` > 0 limits ASR to that many scenes (spread out)."""
    per_scene: Dict[str, Dict] = {}
    all_x: List[np.ndarray] = []
    sr0 = 0
    words = 0
    for sid, a in audios.items():
        x, sr = read_wav(a.wav_path)
        sr0 = sr
        m = signal_metrics(x, sr)
        m["flags"] = list(getattr(a, "flags", []))
        m["intents"] = [d.get("intent") for d in getattr(a, "deliveries", [])]
        per_scene[sid] = m
        all_x.append(x)
        words += sum(len(re.findall(r"[A-Za-z0-9']+", s.text)) for s in a.sentences)
    x_all = np.concatenate(all_x) if all_x else np.zeros(1)
    overall = signal_metrics(x_all, sr0 or 24000)
    speech_time = sum(m["duration"] for m in per_scene.values())
    rate = words / speech_time if speech_time else 0.0
    levels = [m["speech_rms_dbfs"] for m in per_scene.values() if m.get("duration", 0) > 1.0]
    spread = (max(levels) - min(levels)) if levels else 0.0
    flagged = [f"{sid}: {f}" for sid, m in per_scene.items() for f in m["flags"]]
    checks = [
        _check("sample_rate", (sr0 or 0) >= 22050, f"{sr0} Hz", False),
        _check("no_clipping", overall.get("clip_ratio", 0) < 0.0005, f"clip ratio {overall.get('clip_ratio')}", True),
        _check("peak_headroom", overall.get("peak_dbfs", 0) <= -0.5, f"peak {overall.get('peak_dbfs')} dBFS", False),
        _check("dc_offset", abs(overall.get("dc_offset", 0)) < 0.01, f"{overall.get('dc_offset')}", False),
        _check("no_cut_off_sentences", not flagged, "; ".join(flagged[:4]) or "all sentences end cleanly", True),
        _check("no_dead_air", max((m["longest_silence_s"] for m in per_scene.values()), default=0) <= 1.6,
               f"longest pause {max((m['longest_silence_s'] for m in per_scene.values()), default=0)} s", False),
        _check("speech_rate", 2.0 <= rate <= 3.6, f"{rate:.2f} words/s", False),
        _check("expressive_intonation", overall.get("prosody_std", 0) >= 1.6,
               f"intonation {overall.get('prosody_std')} st std (range {overall.get('prosody_range')} st); "
               "< 1.6 st sounds monotone", False),
        _check("stable_voice", overall.get("jitter", 0) <= 0.45 and overall.get("octave_errors", 0) <= 0.05,
               f"jitter {overall.get('jitter')} st, octave breaks {overall.get('octave_errors')}", False),
        _check("consistent_level", spread <= 4.0, f"scene level spread {spread:.1f} dB", False),
    ]
    if scene_durations:
        over = [sid for sid, a in audios.items() if scene_durations.get(sid, 1e9) + 1e-3 < a.duration]
        checks.append(_check("narration_fits_scenes", not over, f"overrun: {over}" if over else "all scenes fit", True))
    asr_report: Dict = {"ran": False}
    want_asr = asr == "on" or (asr == "auto" and asr_available())
    if want_asr:
        try:
            ids = list(audios)
            if asr_scenes and len(ids) > asr_scenes:
                step = len(ids) / asr_scenes
                ids = [ids[int(i * step)] for i in range(asr_scenes)]
            refs, hyps, rows = [], [], []
            for sid in ids:
                a = audios[sid]
                ref = " ".join(s.text for s in a.sentences)
                hyp = transcribe(a.wav_path)
                w = word_error_rate(ref, hyp)
                rows.append({"scene": sid, "wer": round(w, 3), "heard": hyp})
                refs.append(ref)
                hyps.append(hyp)
            wer = word_error_rate(" ".join(refs), " ".join(hyps))
            asr_report = {"ran": True, "model": "faster-whisper base.en", "scenes_checked": len(ids),
                          "wer": round(wer, 3), "worst": sorted(rows, key=lambda r: -r["wer"])[:3]}
            checks.append(_check("intelligibility", wer <= 0.25, f"Whisper WER {wer:.1%} over {len(ids)} scenes", True))
        except Exception as exc:  # noqa: BLE001 - ASR is optional; never block on it
            asr_report = {"ran": False, "error": f"{type(exc).__name__}: {exc}"}
            log.warning("ASR intelligibility check unavailable: %s", exc)
    passed = all(c["passed"] for c in checks if c["severity"] == "hard")
    return {"passed": passed, "checks": checks, "overall": overall, "words_per_second": round(rate, 2),
            "asr": asr_report, "scenes": per_scene}


def voice_score(r: Dict) -> float:
    """0..100 composite: intelligibility, tonal clarity, stability, natural intonation, comfortable pace."""
    wer = r.get("wer", 0.05)
    s = 40 * max(0.0, 1 - wer / 0.1)                                     # clarity of words
    s += 20 * min(1.0, max(0.0, (r.get("harmonicity", 0) - 0.6) / 0.3))  # clean, non-buzzy tone
    s += 15 * min(1.0, max(0.0, (0.6 - r.get("jitter", 0.6)) / 0.4))     # steady, no warble
    p = r.get("prosody_std", 0)
    s += 15 * (1.0 if 2.0 <= p <= 4.5 else max(0.0, 1 - min(abs(p - 2.0), abs(p - 4.5)) / 2))  # lively, not erratic
    w = r.get("words_per_second", 2.8)
    s += 10 * (1.0 if 2.5 <= w <= 3.1 else max(0.0, 1 - min(abs(w - 2.5), abs(w - 3.1)) / 0.6))
    return round(s, 1)


def compare_voices(rows: Sequence[Dict]) -> List[Dict]:
    """Rank voice previews by :func:`voice_score` (best first)."""
    return sorted(rows, key=lambda r: -voice_score(r))
