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
    short_duration: Tuple[float, float] = (60, 90)
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


class TTSSettings(BaseModel):
    provider: Literal["piper"] = "piper"
    voice: str
    voice_label: str = "US English Friendly Male"
    length_scale: float = Field(1.0, gt=0.5, lt=2.0)
    noise_scale: float = 0.667
    noise_w_scale: float = 0.8
    sentence_pause_s: float = Field(0.22, ge=0, le=2)
    scene_lead_in_s: float = Field(0.3, ge=0, le=3)
    scene_tail_s: float = Field(0.45, ge=0, le=3)
    speed_fit_range: Tuple[float, float] = (0.86, 1.18)
    voice_base_url: str


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
