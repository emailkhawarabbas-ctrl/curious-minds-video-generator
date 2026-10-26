"""Exact word timestamps for captions: align the script words to faster-whisper's word timings.

TTS providers here only report sentence timing, so word times are otherwise estimated from
phoneme counts. This module transcribes each scene's narration with faster-whisper
(``word_timestamps=True``, the script given as the prompt), aligns the recognised tokens
to the script's own words (difflib on normalised tokens, numbers spelled out on both sides)
and moves every matched word to its measured time. Words Whisper missed are interpolated
between their matched neighbours. The caption text is always the script text, never the
transcript. If too few words match, the estimates are kept and the report says so.
"""
from __future__ import annotations

import difflib
import logging
from typing import Dict, List, Sequence, Tuple

from src.audio.audio_qc import _asr_model, _norm_tokens, asr_available
from src.audio.tts_engine import SceneAudio, WordTime

log = logging.getLogger(__name__)
MIN_MATCH = 0.6


def _recognised(path: str, prompt: str) -> List[Tuple[str, float, float]]:
    segs, _ = _asr_model().transcribe(str(path), language="en", beam_size=5, word_timestamps=True,
                                      initial_prompt=prompt[:600], condition_on_previous_text=False,
                                      vad_filter=False)
    out = []
    for s in segs:
        for w in s.words or []:
            out.append((w.word, float(w.start), float(w.end)))
    return out


def align_words(script_words: Sequence[WordTime], recognised: Sequence[Tuple[str, float, float]],
                duration: float) -> Tuple[List[WordTime], float]:
    """Return (aligned words, fraction of script words matched)."""
    # script tokens -> word index
    s_tok: List[str] = []
    s_idx: List[int] = []
    for i, w in enumerate(script_words):
        for tok in _norm_tokens(w.word) or [w.word.lower()]:
            s_tok.append(tok)
            s_idx.append(i)
    # recognised tokens with times (a word that expands to several tokens shares its span)
    r_tok: List[str] = []
    r_time: List[Tuple[float, float]] = []
    for text, a, b in recognised:
        toks = _norm_tokens(text)
        for k, tok in enumerate(toks):
            f0, f1 = k / len(toks), (k + 1) / len(toks)
            r_tok.append(tok)
            r_time.append((a + (b - a) * f0, a + (b - a) * f1))
    times: Dict[int, List[Tuple[float, float]]] = {}
    sm = difflib.SequenceMatcher(a=s_tok, b=r_tok, autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            times.setdefault(s_idx[blk.a + k], []).append(r_time[blk.b + k])
    n = len(script_words)
    matched = {i: (min(a for a, _ in v), max(b for _, b in v)) for i, v in times.items()}
    ratio = len(matched) / n if n else 0.0
    if not n or ratio < MIN_MATCH:
        return list(script_words), ratio
    out: List[WordTime] = []
    for i, w in enumerate(script_words):
        if i in matched:
            a, b = matched[i]
        else:   # interpolate between matched neighbours using the estimated proportions
            p = max((j for j in matched if j < i), default=None)
            q = min((j for j in matched if j > i), default=None)
            lo_t = matched[p][1] if p is not None else 0.0
            hi_t = matched[q][0] if q is not None else duration
            lo_e = script_words[p].end if p is not None else 0.0
            hi_e = script_words[q].start if q is not None else max(duration, script_words[-1].end)
            span_e = max(1e-3, hi_e - lo_e)
            a = lo_t + (hi_t - lo_t) * (w.start - lo_e) / span_e
            b = lo_t + (hi_t - lo_t) * (w.end - lo_e) / span_e
        out.append(WordTime(w.word, round(a, 3), round(b, 3)))
    # monotonic, non-overlapping, inside the clip
    prev_start = 0.0
    for w in out:
        w.start = round(min(max(w.start, prev_start), duration), 3)
        w.end = round(min(max(w.end, w.start + 0.06), duration), 3)
        prev_start = w.start
    return out, ratio


def align_scene(audio: SceneAudio) -> Dict:
    """Replace ``audio.words`` with aligned times; returns a small report."""
    if not audio.words:
        return {"scene": audio.scene_id, "aligned": False, "reason": "no words"}
    text = " ".join(w.word for w in audio.words)
    try:
        rec = _recognised(audio.wav_path, text)
    except Exception as exc:  # noqa: BLE001 - alignment is an upgrade; estimates stay usable
        return {"scene": audio.scene_id, "aligned": False, "reason": f"{type(exc).__name__}: {exc}"}
    words, ratio = align_words(audio.words, rec, audio.duration)
    ok = ratio >= MIN_MATCH
    if ok:
        audio.words = words
    return {"scene": audio.scene_id, "aligned": ok, "matched": round(ratio, 3)}


def align_all(audios: Dict[str, SceneAudio], mode: str = "auto") -> Dict:
    """mode: auto (align when faster-whisper is installed) | on (required) | off."""
    if mode == "off":
        return {"ran": False, "reason": "disabled"}
    if not asr_available():
        if mode == "on":
            raise RuntimeError("word alignment requires faster-whisper (pip install faster-whisper)")
        return {"ran": False, "reason": "faster-whisper not installed; using estimated word times"}
    scenes = [align_scene(a) for a in audios.values()]
    aligned = sum(1 for s in scenes if s["aligned"])
    log.info("word alignment: %d/%d scenes aligned", aligned, len(scenes))
    return {"ran": True, "model": "faster-whisper base.en", "aligned_scenes": aligned, "scenes": scenes}
