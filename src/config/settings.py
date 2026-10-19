"""Typed application settings.

Load order (later wins):
  1. ``config/default.yaml``
  2. optional user YAML passed with ``--config``
  3. environment variables ``CM__SECTION__KEY=value`` (values parsed as YAML scalars)

Secrets are *never* stored in YAML: they are read from the environment only
(``LLM_API_KEY`` / ``ANTHROPIC_API_KEY``, ``RESEARCH_API_KEY``, ``TTS_API_KEY``).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "default.yaml"


class BrandSettings(BaseModel):
    name: str
    tagline: str
    mascot: str = "milo"


class PathSettings(BaseModel):
    assets: Path
    generated: Path
    models: Path
    prompts: Path
    content_packs: Path
    cache: Path

    @model_validator(mode="after")
    def _absolute(self) -> "PathSettings":
        for name in type(self).model_fields:
            p = getattr(self, name)
            if not p.is_absolute():
                setattr(self, name, (PROJECT_ROOT / p).resolve())
        return self


class ContentSettings(BaseModel):
    script_source: Literal["auto", "llm", "curated", "offline"] = "auto"
    storyboard_source: Literal["auto", "llm", "rules"] = "auto"
    allow_unresearched: bool = False
    block_on_review_fail: bool = True          # a failed storytelling / visual review check fails the video
    short_duration: Tuple[float, float] = (25, 90)
    long_duration: Tuple[float, float] = (360, 600)

    @field_validator("short_duration", "long_duration")
    @classmethod
    def _range(cls, v: Tuple[float, float]) -> Tuple[float, float]:
        if v[0] <= 0 or v[1] < v[0]:
            raise ValueError(f"invalid duration range {v}")
        return v


class LLMSettings(BaseModel):
    provider: Literal["anthropic", "none"] = "anthropic"
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    max_tokens: int = Field(32000, ge=1024)
    server_side_fallback: bool = True
    timeout_s: float = 600
    max_retries: int = 2


class ResearchSettings(BaseModel):
    providers: List[str]
    timeout_s: float = 20
    max_sources_per_provider: int = Field(4, ge=1, le=20)
    user_agent: str
    authoritative_domains: List[str]


class VoiceProfile(BaseModel):
    """A narrator persona, mapped onto every provider's own voice id."""
    label: str
    description: str = ""
    kokoro_voice: str = "am_michael"          # Kokoro voice id or a blend "am_michael:0.7,am_fenrir:0.3"
    piper_voice: str = "en_US-joe-medium"
    elevenlabs_voice_id: str = ""             # or env ELEVENLABS_VOICE_ID
    openai_voice: str = "ash"
    speed: float = Field(1.0, gt=0.6, lt=1.5)            # base speaking rate (1.0 = the voice's natural pace)
    pitch_semitones: float = Field(0.0, ge=-3, le=3)     # provider-native where supported, else a clean resample
    expressiveness: float = Field(0.6, ge=0, le=1)       # how strongly delivery intents shape pace / pauses
    words_per_second: float = Field(2.7, gt=1.5, lt=4.5)  # measured pace incl. pauses (drives script length)


class TTSSettings(BaseModel):
    provider: Literal["kokoro", "piper", "elevenlabs", "openai"] = "kokoro"
    # Never switch voices silently: a fallback is used only when configured here, and it is recorded.
    fallback_provider: Literal["none", "kokoro", "piper"] = "none"
    profile: str = "friendly"
    profiles: Dict[str, VoiceProfile]
    voice: Optional[str] = None               # explicit provider voice id (overrides the profile's)
    length_scale: float = Field(1.0, gt=0.5, lt=2.0)    # tempo multiplier on top of the profile (>1 = slower)
    noise_scale: float = 0.667
    noise_w_scale: float = 0.8
    sentence_pause_s: float = Field(0.22, ge=0, le=2)
    scene_lead_in_s: float = Field(0.3, ge=0, le=3)
    scene_tail_s: float = Field(0.45, ge=0, le=3)
    speed_fit_range: Tuple[float, float] = (0.86, 1.18)
    voice_base_url: str
    kokoro_model_url: str = ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
                             "kokoro-v1.0.onnx")
    kokoro_voices_url: str = ("https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
                              "voices-v1.0.bin")
    elevenlabs_model: str = "eleven_multilingual_v2"
    openai_model: str = "gpt-4o-mini-tts"
    cache: bool = True                        # reuse identical sentence renders across narration-fit passes
    asr_check: Literal["auto", "on", "off"] = "auto"   # intelligibility check with faster-whisper if installed

    @model_validator(mode="after")
    def _profile_exists(self) -> "TTSSettings":
        if self.profile not in self.profiles:
            raise ValueError(f"unknown voice profile {self.profile!r}; have {sorted(self.profiles)}")
        return self

    @property
    def active(self) -> VoiceProfile:
        return self.profiles[self.profile]

    @property
    def voice_label(self) -> str:
        return self.active.label


class AudioSettings(BaseModel):
    sample_rate: int = 44100
    target_lufs: float = -14.0
    true_peak_db: float = -1.5
    music_gain_db: float = -23.0
    music_duck_db: float = -8.0
    sfx_gain_db: float = -11.0
    music_mood: str = "curious"

    @field_validator("music_gain_db")
    @classmethod
    def _music_below_voice(cls, v: float) -> float:
        if v >= -6:
            raise ValueError("music must stay well below narration (music_gain_db < -6 dB)")
        return v


class SafeArea(BaseModel):
    top: int
    bottom: int
    left: int
    right: int


class RenderProfile(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(30, gt=0, le=60)
    safe: SafeArea
    caption_zone_y: float = Field(gt=0, lt=1)

    @property
    def is_vertical(self) -> bool:
        return self.height > self.width

    @model_validator(mode="after")
    def _even(self) -> "RenderProfile":
        if self.width % 2 or self.height % 2:
            raise ValueError("H.264 yuv420p requires even dimensions")
        return self


class RenderSettings(BaseModel):
    workers: int = 0
    crf: int = Field(20, ge=0, le=51)
    preset: str = "medium"
    audio_bitrate: str = "192k"
    burn_subtitles: bool = True
    profiles: Dict[str, RenderProfile]

    def worker_count(self) -> int:
        if self.workers > 0:
            return self.workers
        return max(1, min(6, (os.cpu_count() or 2) - 1))


class ThumbnailSettings(BaseModel):
    width: int = 1280
    height: int = 720


class Settings(BaseModel):
    brand: BrandSettings
    paths: PathSettings
    content: ContentSettings
    llm: LLMSettings
    research: ResearchSettings
    tts: TTSSettings
    audio: AudioSettings
    render: RenderSettings
    thumbnail: ThumbnailSettings

    # ---- secrets (environment only) -------------------------------------------------
    @property
    def llm_api_key(self) -> Optional[str]:
        return os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or None

    @property
    def research_api_key(self) -> Optional[str]:
        return os.environ.get("RESEARCH_API_KEY") or None

    @property
    def tts_api_key(self) -> Optional[str]:
        return os.environ.get("TTS_API_KEY") or None

    def tts_key_for(self, provider: str) -> Optional[str]:
        """Provider-specific key (ELEVENLABS_API_KEY / OPENAI_API_KEY), else the generic TTS_API_KEY."""
        specific = {"elevenlabs": "ELEVENLABS_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider)
        return (os.environ.get(specific) if specific else None) or self.tts_api_key

    def profile(self, name: str) -> RenderProfile:
        if name not in self.render.profiles:
            raise KeyError(f"unknown render profile {name!r}; have {sorted(self.render.profiles)}")
        return self.render.profiles[name]


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _env_overrides(environ: Dict[str, str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, raw in environ.items():
        if not key.startswith("CM__"):
            continue
        parts = [p.lower() for p in key[4:].split("__") if p]
        if not parts:
            continue
        node = result
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = yaml.safe_load(raw)
    return result


def load_settings(config_path: Optional[Path] = None,
                  environ: Optional[Dict[str, str]] = None) -> Settings:
    data = yaml.safe_load(DEFAULT_CONFIG.read_text()) or {}
    if config_path:
        user = yaml.safe_load(Path(config_path).read_text()) or {}
        data = _deep_merge(data, user)
    data = _deep_merge(data, _env_overrides(dict(os.environ if environ is None else environ)))
    return Settings.model_validate(data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
