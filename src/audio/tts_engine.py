"""Provider-independent narration engine.

Providers (``tts.provider``):
  * ``kokoro``     — Kokoro-82M neural TTS, local, free (Apache-2.0). Default: natural prosody, 24 kHz.
  * ``piper``      — Piper VITS voices, local and lightweight; flatter delivery (kept as an opt-in fallback).
  * ``elevenlabs`` — cloud; needs ``ELEVENLABS_API_KEY`` (or ``TTS_API_KEY``) and a voice id.
  * ``openai``     — cloud; needs ``OPENAI_API_KEY`` (or ``TTS_API_KEY``). Delivery intents are passed as
                     spoken instructions.

The engine never switches voices silently: if the configured provider cannot start, it raises,
unless ``tts.fallback_provider`` is set — in which case the fallback is logged and recorded in
:meth:`TTSEngine.voice_report` (and therefore in ``production_report.json``).

* Narration is synthesised **per sentence**, each with a delivery chosen by
  :mod:`src.audio.narration_director` (hook / question / surprise / discovery / ending ...),
  so sentence boundaries are exact and pacing follows the story.
* Each sentence is loudness-normalised on its *speech* frames (consistent level across
  providers and sentences), then given a small intent-dependent emphasis offset; peaks are
  kept below -1 dBFS by gain, never by clipping.
* Leading/trailing silence is trimmed with generous tails and short fades, so soft final
  consonants are never cut and joins never click.
* Word timings inside a sentence are distributed by phoneme counts where the provider exposes
  them, giving phrase-accurate captions without a separate aligner.
* A pronunciation dictionary (``config/pronunciations.yaml``) rewrites the text sent to the TTS
  only; captions keep the original spelling.
* Each scene gets a lip-sync envelope (mouth openness per video frame).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
import wave
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import requests
import yaml

from src.audio.narration_director import Delivery, delivery_for, direct_scene, shape_for_speech
from src.config.settings import PROJECT_ROOT, Settings
from src.utils.text import split_sentences, spoken_number_token

log = logging.getLogger(__name__)
PRON_FILE = PROJECT_ROOT / "config" / "pronunciations.yaml"

SPEECH_RMS_DBFS = -20.0       # per-sentence speech level before the final -14 LUFS mix normalisation
PEAK_CEILING = 0.89           # -1 dBFS

VOICE_ALIASES = {
    "us english friendly male": "friendly",
    "professional friendly male": "friendly",
    "us english male (energetic)": "energetic",
    "energetic educational male": "energetic",
    "us english male (calm)": "documentary",
    "calm documentary male": "documentary",
    "us english male (narrator)": "documentary",
}
PIPER_VOICE_RE = re.compile(r"^([a-z]{2})_([A-Z]{2})-([a-zA-Z0-9_]+)-(x_low|low|medium|high)$")
KOKORO_VOICE_RE = re.compile(r"^[abejfhipz][fm]_[a-z]+(:[0-9.]+)?(,[abejfhipz][fm]_[a-z]+(:[0-9.]+)?)*$")


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
    deliveries: List[Dict] = field(default_factory=list)  # per sentence: intent, speed, pauses, gain
    flags: List[str] = field(default_factory=list)        # per-sentence synthesis warnings (e.g. abrupt end)

    def to_json(self) -> Dict:
        return asdict(self)

    @staticmethod
    def from_json(d: Dict) -> "SceneAudio":
        d = dict(d)
        d.setdefault("deliveries", [])
        d.setdefault("flags", [])
        return SceneAudio(**{**d, "sentences": [SentenceTime(**s) for s in d["sentences"]],
                             "words": [WordTime(**w) for w in d["words"]]})


@dataclass
class SceneContext:
    """Where a scene sits in the story; drives sentence delivery."""
    index: int = 1
    count: int = 3
    role: Optional[str] = None


class TTSError(RuntimeError):
    pass


# --------------------------------------------------------------------------- providers
class TTSProvider(ABC):
    name = "base"
    voice_name = ""
    native_pitch = False

    @abstractmethod
    def synth(self, text: str, length_scale: float, delivery: Optional[Delivery] = None
              ) -> Tuple[np.ndarray, int, List[int]]:
        """Return (int16 mono samples, sample_rate, phoneme count per word or [])."""

    @property
    def license_note(self) -> str:
        return ""


def _download(url: str, path: Path) -> None:
    log.info("downloading %s", url)
    r = requests.get(url, timeout=600, stream=True)
    if r.status_code != 200:
        raise TTSError(f"download failed ({r.status_code}): {url}")
    tmp = path.with_suffix(path.suffix + ".part")
    with open(tmp, "wb") as fh:
        for chunk in r.iter_content(1 << 20):
            fh.write(chunk)
    tmp.replace(path)


def _word_phoneme_counts(phonemes: str) -> List[int]:
    counts: List[int] = []
    for tok in re.split(r"\s+", phonemes.strip()):
        n = len([c for c in tok if c not in "ˈˌː,.;:!?—–-\"'()…"])
        if n:
            counts.append(n)
    return counts


class KokoroProvider(TTSProvider):
    name = "kokoro"

    def __init__(self, settings: Settings, voice: Optional[str] = None):
        self.s = settings
        self.voice_name = voice or settings.tts.voice or settings.tts.active.kokoro_voice
        if not KOKORO_VOICE_RE.match(self.voice_name):
            raise TTSError(f"{self.voice_name!r} is not a Kokoro voice (e.g. am_michael or am_michael:0.7,am_puck:0.3)")
        model, voices = self.ensure_model(settings)
        logging.getLogger("phonemizer").setLevel(logging.ERROR)   # benign espeak word-alignment notices
        try:
            from kokoro_onnx import Kokoro
        except ImportError as exc:  # pragma: no cover
            raise TTSError("kokoro-onnx is not installed (pip install kokoro-onnx)") from exc
        self.k = Kokoro(str(model), str(voices))
        self.style = self._style(self.voice_name)

    @staticmethod
    def ensure_model(settings: Settings) -> Tuple[Path, Path]:
        d = settings.paths.models / "kokoro"
        d.mkdir(parents=True, exist_ok=True)
        model, voices = d / "kokoro-v1.0.onnx", d / "voices-v1.0.bin"
        for url, path in ((settings.tts.kokoro_model_url, model), (settings.tts.kokoro_voices_url, voices)):
            if not path.exists():
                _download(url, path)
        return model, voices

    def _style(self, spec: str) -> np.ndarray:
        """A voice id, or a weighted blend of voices ("am_michael:0.7,am_puck:0.3")."""
        parts = []
        for p in spec.split(","):
            name, _, w = p.partition(":")
            if name not in self.k.get_voices():
                raise TTSError(f"unknown Kokoro voice {name!r}")
            parts.append((self.k.get_voice_style(name), float(w or 1.0)))
        total = sum(w for _, w in parts)
        return sum(v * (w / total) for v, w in parts).astype(np.float32)

    def synth(self, text, length_scale, delivery=None):
        speed = self.s.tts.active.speed * (delivery.speed if delivery else 1.0) / max(0.5, length_scale)
        audio, sr = self.k.create(text, voice=self.style, speed=float(np.clip(speed, 0.6, 1.6)), lang="en-us")
        if audio.size == 0:
            raise TTSError(f"TTS produced no audio for: {text!r}")
        try:
            counts = _word_phoneme_counts(self.k.tokenizer.phonemize(text, "en-us"))
        except Exception:  # noqa: BLE001 - timing falls back to letter weights
            counts = []
        return (np.clip(audio, -1, 1) * 32767).astype(np.int16), sr, counts

    @property
    def license_note(self) -> str:
        return f"Kokoro-82M voice {self.voice_name} (model and voices Apache-2.0, hexgrad/Kokoro-82M)"


class PiperProvider(TTSProvider):
    name = "piper"

    def __init__(self, settings: Settings, voice: Optional[str] = None):
        self.s = settings
        v = voice or settings.tts.voice
        self.voice_name = v if v and PIPER_VOICE_RE.match(v) else settings.tts.active.piper_voice
        self.model_path = self.ensure_voice(settings, self.voice_name)
        try:
            from piper import PiperVoice, SynthesisConfig
        except ImportError as exc:  # pragma: no cover
            raise TTSError("piper-tts is not installed (pip install piper-tts)") from exc
        self._SynthesisConfig = SynthesisConfig
        self.voice = PiperVoice.load(str(self.model_path))
        self.meta = json.loads(Path(str(self.model_path) + ".json").read_text(encoding="utf-8"))

    @staticmethod
    def ensure_voice(settings: Settings, voice: str) -> Path:
        """Download the voice model on first use (cached under models/piper)."""
        d = settings.paths.models / "piper"
        d.mkdir(parents=True, exist_ok=True)
        onnx = d / f"{voice}.onnx"
        cfg = d / f"{voice}.onnx.json"
        if onnx.exists() and cfg.exists():
            return onnx
        m = PIPER_VOICE_RE.match(voice)
        if not m:
            raise TTSError(f"cannot derive download path for voice {voice!r}")
        lang, region, name, quality = m.groups()
        base = f"{settings.tts.voice_base_url}/{lang}/{lang}_{region}/{name}/{quality}/{voice}"
        for url, path in ((base + ".onnx.json", cfg), (base + ".onnx", onnx)):
            _download(url, path)
        try:
            card = requests.get(base.rsplit("/", 1)[0] + "/MODEL_CARD", timeout=30)
            if card.ok:
                (d / f"{voice}.MODEL_CARD").write_text(card.text, encoding="utf-8")
        except requests.RequestException:
            pass
        return onnx

    def synth(self, text, length_scale, delivery=None):
        ls = length_scale / (self.s.tts.active.speed * (delivery.speed if delivery else 1.0))
        cfg = self._SynthesisConfig(length_scale=ls, noise_scale=self.s.tts.noise_scale,
                                    noise_w_scale=self.s.tts.noise_w_scale, normalize_audio=True)
        audio: List[np.ndarray] = []
        counts: List[int] = []
        sr = self.voice.config.sample_rate
        for chunk in self.voice.synthesize(text, syn_config=cfg):
            audio.append(chunk.audio_int16_array.astype(np.int16))
            sr = chunk.sample_rate
            counts += _word_phoneme_counts("".join(chunk.phonemes))
        if not audio:
            raise TTSError(f"TTS produced no audio for: {text!r}")
        return np.concatenate(audio), sr, counts

    @property
    def license_note(self) -> str:
        card = self.s.paths.models / "piper" / f"{self.voice_name}.MODEL_CARD"
        lic = ""
        if card.exists():
            m = re.search(r"License:\s*(.+)", card.read_text(encoding="utf-8"))
            lic = m.group(1).strip() if m else ""
        return f"Piper voice {self.voice_name} (dataset license: {lic or 'see MODEL_CARD'})"


class ElevenLabsProvider(TTSProvider):
    """ElevenLabs cloud TTS (raw 24 kHz PCM). Delivery -> style / stability / speed voice settings."""
    name = "elevenlabs"

    def __init__(self, settings: Settings, voice: Optional[str] = None):
        import os
        self.s = settings
        self.key = settings.tts_key_for("elevenlabs")
        if not self.key:
            raise TTSError("tts.provider=elevenlabs needs ELEVENLABS_API_KEY (or TTS_API_KEY)")
        self.voice_name = voice or os.environ.get("ELEVENLABS_VOICE_ID") or settings.tts.active.elevenlabs_voice_id
        if not self.voice_name:
            raise TTSError("tts.provider=elevenlabs needs a voice id (ELEVENLABS_VOICE_ID or profile.elevenlabs_voice_id)")

    def synth(self, text, length_scale, delivery=None):
        d = delivery or delivery_for("explanation", self.s.tts.active.expressiveness)
        speed = float(np.clip(self.s.tts.active.speed * d.speed / length_scale, 0.7, 1.2))
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_name}",
            params={"output_format": "pcm_24000"}, headers={"xi-api-key": self.key}, timeout=120,
            json={"text": text, "model_id": self.s.tts.elevenlabs_model,
                  "voice_settings": {"stability": round(0.65 - 0.35 * d.style, 2), "similarity_boost": 0.8,
                                     "style": d.style, "use_speaker_boost": True, "speed": speed}})
        if r.status_code != 200:
            raise TTSError(f"ElevenLabs error {r.status_code}: {r.text[:300]}")
        return np.frombuffer(r.content, np.int16).copy(), 24000, []

    @property
    def license_note(self) -> str:
        return f"ElevenLabs voice {self.voice_name} (commercial use per your ElevenLabs plan)"


class OpenAIProvider(TTSProvider):
    """OpenAI speech API (raw 24 kHz PCM). Delivery intents become spoken instructions."""
    name = "openai"

    def __init__(self, settings: Settings, voice: Optional[str] = None):
        self.s = settings
        self.key = settings.tts_key_for("openai")
        if not self.key:
            raise TTSError("tts.provider=openai needs OPENAI_API_KEY (or TTS_API_KEY)")
        self.voice_name = voice or settings.tts.active.openai_voice

    def synth(self, text, length_scale, delivery=None):
        d = delivery or delivery_for("explanation", self.s.tts.active.expressiveness)
        prof = self.s.tts.active
        body = {"model": self.s.tts.openai_model, "voice": self.voice_name, "input": text, "response_format": "pcm"}
        pace = prof.speed * d.speed / length_scale
        if self.s.tts.openai_model.startswith("gpt-4o"):
            body["instructions"] = (f"Voice: {prof.description or prof.label}; friendly American English educational "
                                    f"presenter. {d.instruction} Pace: "
                                    f"{'a little slower than usual' if pace < 0.97 else 'a little brisker than usual' if pace > 1.03 else 'natural'}.")
        else:
            body["speed"] = round(float(np.clip(pace, 0.5, 2.0)), 3)
        r = requests.post("https://api.openai.com/v1/audio/speech", headers={"Authorization": f"Bearer {self.key}"},
                          json=body, timeout=120)
        if r.status_code != 200:
            raise TTSError(f"OpenAI TTS error {r.status_code}: {r.text[:300]}")
        return np.frombuffer(r.content, np.int16).copy(), 24000, []

    @property
    def license_note(self) -> str:
        return f"OpenAI TTS voice {self.voice_name} (AI-generated voice; disclose per OpenAI usage policies)"


PROVIDERS = {"kokoro": KokoroProvider, "piper": PiperProvider, "elevenlabs": ElevenLabsProvider,
             "openai": OpenAIProvider}


def get_provider(settings: Settings) -> Tuple[TTSProvider, Optional[Dict]]:
    """(provider, fallback record or None). Raises unless a fallback is explicitly configured."""
    name = settings.tts.provider
    try:
        return PROVIDERS[name](settings), None
    except Exception as exc:  # noqa: BLE001
        fb = settings.tts.fallback_provider
        if fb == "none" or fb == name:
            raise TTSError(f"TTS provider {name!r} unavailable: {exc}. Refusing to switch to another voice "
                           f"silently; set tts.fallback_provider to allow a fallback.") from exc
        log.warning("TTS provider %s unavailable (%s); using configured fallback %s", name, exc, fb)
        return PROVIDERS[fb](settings), {"requested": name, "used": fb, "reason": f"{type(exc).__name__}: {exc}"}


def resolve_voice(settings: Settings, value: Optional[str]) -> None:
    """Apply a --voice value: a profile key/label, a Piper voice id or a Kokoro voice (blend)."""
    if not value:
        return
    v = value.strip()
    low = v.lower()
    t = settings.tts
    for key, prof in t.profiles.items():
        if low in (key.lower(), prof.label.lower()):
            t.profile = key
            return
    if low in VOICE_ALIASES and VOICE_ALIASES[low] in t.profiles:
        t.profile = VOICE_ALIASES[low]
        return
    if PIPER_VOICE_RE.match(v):
        t.provider, t.voice = "piper", v
        return
    if KOKORO_VOICE_RE.match(v):
        t.provider, t.voice = "kokoro", v
        return
    raise ValueError(f"unknown voice {value!r}: use a profile ({', '.join(p.label for p in t.profiles.values())}), "
                     "a Piper voice id or a Kokoro voice id")


# --------------------------------------------------------------------------- signal helpers
def load_pronunciations() -> Dict[str, str]:
    if PRON_FILE.exists():
        return {str(k): str(v) for k, v in (yaml.safe_load(PRON_FILE.read_text(encoding="utf-8")) or {}).items()}
    return {}


def apply_pronunciations(text: str, table: Dict[str, str]) -> str:
    for word, say in sorted(table.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", say, text)
    return text


def _frame_rms(f: np.ndarray, win: int) -> np.ndarray:
    n = len(f) // win
    if n == 0:
        return np.zeros(0)
    return np.sqrt((f[: n * win].reshape(n, win) ** 2).mean(axis=1))


def _trim(x: np.ndarray, sr: int, thresh: float = 0.008) -> np.ndarray:
    """Trim silence; keep 40 ms before the first and 160 ms after the last voiced frame, with fades.

    The generous tail keeps soft final consonants ("-s", "-f", "-th") that sit below the gate.
    """
    if x.size == 0:
        return x
    f = x.astype(np.float32) / 32768.0
    win = max(1, int(sr * 0.01))
    rms = _frame_rms(f, win)
    if rms.size == 0:
        return x
    idx = np.where(rms > thresh)[0]
    if idx.size == 0:
        return x
    a = max(0, idx[0] * win - int(sr * 0.04))
    b = min(len(x), (idx[-1] + 1) * win + int(sr * 0.16))
    y = f[a:b].copy()
    fi, fo = min(len(y), int(sr * 0.008)), min(len(y), int(sr * 0.03))
    if fi:
        y[:fi] *= np.linspace(0, 1, fi)
    if fo:
        y[-fo:] *= np.linspace(1, 0, fo)
    return (y * 32767).astype(np.int16)


def normalise_speech(x: np.ndarray, sr: int, gain_db: float = 0.0) -> Tuple[np.ndarray, Dict]:
    """Bring speech frames to SPEECH_RMS_DBFS (+ emphasis), peaks <= -1 dBFS by gain only."""
    f = x.astype(np.float32) / 32768.0
    rms = _frame_rms(f, max(1, int(sr * 0.02)))
    voiced = rms[rms > max(1e-4, rms.max() * 0.1)] if rms.size else rms
    level = float(np.sqrt((voiced ** 2).mean())) if voiced.size else 0.0
    if level <= 1e-5:
        return x, {"speech_dbfs": -120.0, "gain_db": 0.0}
    target = 10 ** ((SPEECH_RMS_DBFS + gain_db) / 20)
    g = target / level
    peak = float(np.abs(f).max()) * g
    if peak > PEAK_CEILING:
        g *= PEAK_CEILING / peak
    return (np.clip(f * g, -1, 1) * 32767).astype(np.int16), {"speech_dbfs": round(20 * np.log10(level), 2),
                                                               "gain_db": round(20 * np.log10(g), 2)}


def abrupt_ending(x: np.ndarray, sr: int) -> bool:
    """True if speech energy is still high at the very end (a sentence cut off mid-sound)."""
    f = x.astype(np.float32) / 32768.0
    rms = _frame_rms(f, max(1, int(sr * 0.01)))
    if rms.size < 10:
        return False
    speech = np.median(rms[rms > rms.max() * 0.1]) if (rms > rms.max() * 0.1).any() else 0
    return bool(speech > 0 and rms[-3:].mean() > 0.6 * speech)


def pitch_shift(samples: np.ndarray, sr: int, semitones: float) -> np.ndarray:
    """Formant-aware pitch shift via FFmpeg rubberband when available, else a clean resample+tempo pair."""
    if abs(semitones) < 0.05 or not shutil.which("ffmpeg"):
        return samples
    r = 2 ** (semitones / 12)
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.wav", Path(td) / "out.wav"
        _write_wav(src, samples, sr)
        filters = [f"rubberband=pitch={r:.5f}:formant=preserved",
                   f"asetrate={int(sr * r)},aresample={sr},atempo={1 / r:.5f}"]
        for af in filters:
            p = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", af, "-ar", str(sr),
                                "-ac", "1", str(dst)], capture_output=True)
            if p.returncode == 0 and dst.exists():
                with wave.open(str(dst)) as w:
                    return np.frombuffer(w.readframes(w.getnframes()), np.int16).copy()
    log.warning("pitch shift unavailable; narration left at natural pitch")
    return samples


def _write_wav(path: Path, samples: np.ndarray, sr: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(samples.astype(np.int16).tobytes())


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


# --------------------------------------------------------------------------- engine
class TTSEngine:
    def __init__(self, settings: Settings, provider: Optional[TTSProvider] = None):
        self.s = settings
        self.fallback: Optional[Dict] = None
        if provider is None:
            provider, self.fallback = get_provider(settings)
        self.provider = provider
        self.pron = load_pronunciations()
        self.cache_dir = settings.paths.cache / "tts" if settings.tts.cache else None

    def voice_report(self) -> Dict:
        p = self.s.tts.active
        return {"provider": self.provider.name, "voice": self.provider.voice_name, "profile": self.s.tts.profile,
                "label": p.label, "description": p.description, "base_speed": p.speed,
                "pitch_semitones": p.pitch_semitones, "expressiveness": p.expressiveness,
                "fallback": self.fallback, "license": self.provider.license_note}

    # ------------------------------------------------------------------ sentence synthesis (cached)
    def _synth_cached(self, text: str, length_scale: float, d: Delivery) -> Tuple[np.ndarray, int, List[int]]:
        key = None
        if self.cache_dir is not None:
            raw = json.dumps([self.provider.name, self.provider.voice_name, text, round(length_scale, 4),
                              round(d.speed, 4), d.intent if self.provider.name in ("openai", "elevenlabs") else "",
                              round(self.s.tts.active.speed, 4)])
            key = hashlib.sha1(raw.encode()).hexdigest()
            hit = self.cache_dir / f"{key}.npz"
            if hit.exists():
                z = np.load(hit)
                return z["a"], int(z["sr"]), z["c"].tolist()
        a, sr, counts = self.provider.synth(text, length_scale, d)
        if key is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            np.savez(self.cache_dir / f"{key}.npz", a=a, sr=sr, c=np.array(counts, dtype=np.int32))
        return a, sr, counts

    def synthesize_scene(self, scene_id: str, narration: str, out_dir: Path, length_scale: float,
                         fps: int = 30, context: Optional[SceneContext] = None) -> SceneAudio:
        out_dir.mkdir(parents=True, exist_ok=True)
        ctx = context or SceneContext()
        sentences = split_sentences(narration)
        deliveries = direct_scene(sentences, scene_index=ctx.index, scene_count=ctx.count, role=ctx.role,
                                  expressiveness=self.s.tts.active.expressiveness)
        pieces: List[np.ndarray] = []
        stimes: List[SentenceTime] = []
        wtimes: List[WordTime] = []
        flags: List[str] = []
        dlog: List[Dict] = []
        sr = 24000
        t = 0.0
        base_pause = self.s.tts.sentence_pause_s
        for k, (sent, d) in enumerate(zip(sentences, deliveries)):
            per_word = [apply_pronunciations(spoken_number_token(w), self.pron) for w in sent.split()]
            spoken = shape_for_speech(" ".join(per_word))
            samples, sr, ph_counts = self._synth_cached(spoken, length_scale, d)
            samples = _trim(samples, sr)
            samples, lvl = normalise_speech(samples, sr, d.gain_db)
            if abrupt_ending(samples, sr):
                flags.append(f"sentence {k + 1} may end abruptly: {sent[:60]!r}")
            if k > 0 and d.pause_before > 0:
                pieces.append(np.zeros(int(sr * d.pause_before), dtype=np.int16))
                t += d.pause_before
            dur = len(samples) / sr
            stimes.append(SentenceTime(sent, round(t, 3), round(t + dur, 3)))
            wtimes += self._word_times(sent, per_word, ph_counts, t, dur)
            pieces.append(samples)
            dlog.append({**d.to_json(), **lvl, "sentence": sent})
            t += dur
            if k < len(sentences) - 1:
                pause = max(base_pause * 0.6, d.pause_after if d.pause_after > 0 else base_pause)
                pieces.append(np.zeros(int(sr * pause), dtype=np.int16))
                t += pause
        audio = np.concatenate(pieces) if pieces else np.zeros(1, dtype=np.int16)
        semis = self.s.tts.active.pitch_semitones
        if semis and not self.provider.native_pitch:
            shifted = pitch_shift(audio, sr, semis)
            if len(shifted) and abs(len(shifted) - len(audio)) / len(audio) < 0.02:
                audio = np.pad(shifted, (0, max(0, len(audio) - len(shifted))))[:len(audio)]
        path = out_dir / f"{scene_id}.wav"
        _write_wav(path, audio, sr)
        duration = len(audio) / sr
        return SceneAudio(scene_id=scene_id, wav_path=str(path), sample_rate=sr, duration=round(duration, 3),
                          sentences=stimes, words=wtimes, fps=fps, length_scale=length_scale,
                          deliveries=dlog, flags=flags)

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
