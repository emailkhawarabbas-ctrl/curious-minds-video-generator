"""Provider-independent narration engine (default provider: Piper, local & free).

* Narration is synthesised **per sentence**, so sentence boundaries are exact; word
  timings inside a sentence are distributed by phoneme counts (Piper returns the
  phonemes per word), giving phrase-accurate captions without a separate aligner.
* A pronunciation dictionary (``config/pronunciations.yaml``) rewrites the text sent to
  the TTS only; captions keep the original spelling.
* Leading/trailing silence of each sentence is trimmed and replaced by controlled
  pauses, so narration never overlaps and is never clipped.
* Each scene gets a lip-sync envelope (mouth openness per video frame).
"""
from __future__ import annotations

import json
import logging
import re
import wave
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import requests
import yaml

from src.config.settings import PROJECT_ROOT, Settings
from src.utils.text import split_sentences, spoken_number_token

log = logging.getLogger(__name__)
PRON_FILE = PROJECT_ROOT / "config" / "pronunciations.yaml"


@dataclass
class WordTime:
    word: str
    start: float
    end: float


@dataclass
class SentenceTime:
    text: str
    start: float
    end: float


@dataclass
class SceneAudio:
    scene_id: str
    wav_path: str
    sample_rate: int
    duration: float                       # narration length (s)
    sentences: List[SentenceTime] = field(default_factory=list)
    words: List[WordTime] = field(default_factory=list)
    envelope: List[float] = field(default_factory=list)   # per frame (fps), 0..1
    fps: int = 30
    length_scale: float = 1.0

    def to_json(self) -> Dict:
        return asdict(self)

    @staticmethod
    def from_json(d: Dict) -> "SceneAudio":
        return SceneAudio(**{**d, "sentences": [SentenceTime(**s) for s in d["sentences"]],
                             "words": [WordTime(**w) for w in d["words"]]})


class TTSError(RuntimeError):
    pass


# --------------------------------------------------------------------------- providers
class TTSProvider(ABC):
    name = "base"

    @abstractmethod
    def synth(self, text: str, length_scale: float) -> Tuple[np.ndarray, int, List[int]]:
        """Return (int16 mono samples, sample_rate, phoneme count per word)."""

    @property
    def license_note(self) -> str:
        return ""


class PiperProvider(TTSProvider):
    name = "piper"

    def __init__(self, settings: Settings):
        self.s = settings
        self.voice_name = settings.tts.voice
        self.model_path = self.ensure_voice(settings, self.voice_name)
        try:
            from piper import PiperVoice, SynthesisConfig
        except ImportError as exc:  # pragma: no cover
            raise TTSError("piper-tts is not installed (pip install piper-tts)") from exc
        self._SynthesisConfig = SynthesisConfig
        self.voice = PiperVoice.load(str(self.model_path))
        self.meta = json.loads(Path(str(self.model_path) + ".json").read_text())

    @staticmethod
    def ensure_voice(settings: Settings, voice: str) -> Path:
        """Download the voice model on first use (cached under models/piper)."""
        d = settings.paths.models / "piper"
        d.mkdir(parents=True, exist_ok=True)
        onnx = d / f"{voice}.onnx"
        cfg = d / f"{voice}.onnx.json"
        if onnx.exists() and cfg.exists():
            return onnx
        m = re.match(r"^([a-z]{2})_([A-Z]{2})-([a-zA-Z0-9_]+)-(x_low|low|medium|high)$", voice)
        if not m:
            raise TTSError(f"cannot derive download path for voice {voice!r}")
        lang, region, name, quality = m.groups()
        base = f"{settings.tts.voice_base_url}/{lang}/{lang}_{region}/{name}/{quality}/{voice}"
        for url, path in ((base + ".onnx.json", cfg), (base + ".onnx", onnx)):
            log.info("downloading voice model %s", url)
            r = requests.get(url, timeout=300, stream=True)
            if r.status_code != 200:
                raise TTSError(f"voice download failed ({r.status_code}): {url}")
            tmp = path.with_suffix(path.suffix + ".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
            tmp.rename(path)
        try:
            card = requests.get(base.rsplit("/", 1)[0] + "/MODEL_CARD", timeout=30)
            if card.ok:
                (d / f"{voice}.MODEL_CARD").write_text(card.text)
        except requests.RequestException:
            pass
        return onnx

    def synth(self, text: str, length_scale: float) -> Tuple[np.ndarray, int, List[int]]:
        cfg = self._SynthesisConfig(length_scale=length_scale, noise_scale=self.s.tts.noise_scale,
                                    noise_w_scale=self.s.tts.noise_w_scale, normalize_audio=True)
        audio: List[np.ndarray] = []
        counts: List[int] = []
        sr = self.voice.config.sample_rate
        for chunk in self.voice.synthesize(text, syn_config=cfg):
            audio.append(chunk.audio_int16_array.astype(np.int16))
            sr = chunk.sample_rate
            word_ph: List[int] = []
            cur = 0
            for ph in chunk.phonemes:
                if ph == " ":
                    if cur:
                        word_ph.append(cur)
                    cur = 0
                elif ph in ",.;:!?—–-\"'()":
                    if cur:
                        word_ph.append(cur)
                        cur = 0
                elif ph not in ("ˈ", "ˌ", "ː"):
                    cur += 1
            if cur:
                word_ph.append(cur)
            counts += word_ph
        if not audio:
            raise TTSError(f"TTS produced no audio for: {text!r}")
        return np.concatenate(audio), sr, counts

    @property
    def license_note(self) -> str:
        card = self.s.paths.models / "piper" / f"{self.voice_name}.MODEL_CARD"
        lic = ""
        if card.exists():
            m = re.search(r"License:\s*(.+)", card.read_text())
            lic = m.group(1).strip() if m else ""
        return f"Piper voice {self.voice_name} (dataset license: {lic or 'see MODEL_CARD'})"


def get_provider(settings: Settings) -> TTSProvider:
    if settings.tts.provider == "piper":
        return PiperProvider(settings)
    raise TTSError(f"unknown TTS provider {settings.tts.provider!r}")


# --------------------------------------------------------------------------- engine
def load_pronunciations() -> Dict[str, str]:
    if PRON_FILE.exists():
        return {str(k): str(v) for k, v in (yaml.safe_load(PRON_FILE.read_text()) or {}).items()}
    return {}


def apply_pronunciations(text: str, table: Dict[str, str]) -> str:
    for word, say in sorted(table.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", say, text)
    return text


def _trim(x: np.ndarray, sr: int, thresh: float = 0.012) -> np.ndarray:
    if x.size == 0:
        return x
    f = x.astype(np.float32) / 32768.0
    win = max(1, int(sr * 0.01))
    n = len(f) // win
    if n == 0:
        return x
    rms = np.sqrt((f[: n * win].reshape(n, win) ** 2).mean(axis=1))
    idx = np.where(rms > thresh)[0]
    if idx.size == 0:
        return x
    a = max(0, idx[0] * win - int(sr * 0.02))
    b = min(len(x), (idx[-1] + 1) * win + int(sr * 0.06))
    return x[a:b]


def envelope_for(samples: np.ndarray, sr: int, fps: int, total_frames: int, offset_s: float) -> List[float]:
    """Mouth openness per frame from the narration loudness (0..1, smoothed, gated)."""
    f = samples.astype(np.float32) / 32768.0
    hop = sr / fps
    vals = []
    for i in range(total_frames):
        t0 = (i / fps - offset_s) * sr
        a, b = int(t0), int(t0 + hop)
        if b <= 0 or a >= len(f):
            vals.append(0.0)
            continue
        seg = f[max(0, a):min(len(f), b)]
        vals.append(float(np.sqrt((seg ** 2).mean())) if seg.size else 0.0)
    v = np.array(vals)
    if v.max() <= 0:
        return [0.0] * total_frames
    ref = np.percentile(v[v > 0], 90) if (v > 0).any() else 1.0
    v = np.clip(v / (ref + 1e-9), 0, 1.2)
    v = np.where(v < 0.12, 0.0, v)
    sm = np.copy(v)
    for i in range(1, len(sm)):
        sm[i] = 0.55 * v[i] + 0.45 * sm[i - 1]
    return [round(float(min(1.0, x)), 3) for x in sm]


class TTSEngine:
    def __init__(self, settings: Settings, provider: Optional[TTSProvider] = None):
        self.s = settings
        self.provider = provider or get_provider(settings)
        self.pron = load_pronunciations()

    def synthesize_scene(self, scene_id: str, narration: str, out_dir: Path, length_scale: float,
                         fps: int = 30) -> SceneAudio:
        out_dir.mkdir(parents=True, exist_ok=True)
        sentences = split_sentences(narration)
        pieces: List[np.ndarray] = []
        stimes: List[SentenceTime] = []
        wtimes: List[WordTime] = []
        sr = 22050
        t = 0.0
        for k, sent in enumerate(sentences):
            per_word = [apply_pronunciations(spoken_number_token(w), self.pron) for w in sent.split()]
            spoken = " ".join(per_word)
            samples, sr, ph_counts = self.provider.synth(spoken, length_scale)
            samples = _trim(samples, sr)
            dur = len(samples) / sr
            stimes.append(SentenceTime(sent, round(t, 3), round(t + dur, 3)))
            wtimes += self._word_times(sent, per_word, ph_counts, t, dur)
            pieces.append(samples)
            t += dur
            if k < len(sentences) - 1:
                pause = self.s.tts.sentence_pause_s * (1.4 if sent.rstrip().endswith(("?", "!")) else 1.0)
                pieces.append(np.zeros(int(sr * pause), dtype=np.int16))
                t += pause
        audio = np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.int16)
        path = out_dir / f"{scene_id}.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(audio.tobytes())
        duration = len(audio) / sr
        return SceneAudio(scene_id=scene_id, wav_path=str(path), sample_rate=sr, duration=round(duration, 3),
                          sentences=stimes, words=wtimes, fps=fps, length_scale=length_scale)

    @staticmethod
    def _word_times(original: str, per_word: Sequence[str], ph_counts: Sequence[int], t0: float,
                    dur: float) -> List[WordTime]:
        """Distribute a sentence's duration over its words.

        `per_word` holds the spoken form of every original word (numbers expanded, pronunciation
        fixes applied), so phoneme groups can be mapped back to the original words.
        """
        words = original.split()
        if not words:
            return []
        groups = [len(re.findall(r"[A-Za-z0-9']+", sp)) or 1 for sp in per_word]
        if sum(groups) == len(ph_counts):
            weights, k = [], 0
            for g in groups:
                weights.append(max(1, sum(ph_counts[k:k + g])))
                k += g
        else:
            weights = [max(1, len(re.sub(r"[^A-Za-z0-9]", "", sp))) for sp in per_word]
        weights = [w + (2.5 if re.search(r"[,;:—–]$", words[i]) else 0) for i, w in enumerate(weights)]
        total = float(sum(weights))
        out, acc = [], 0.0
        for w, wt in zip(words, weights):
            s = t0 + dur * acc / total
            acc += wt
            e = t0 + dur * acc / total
            out.append(WordTime(w, round(s, 3), round(e, 3)))
        return out
