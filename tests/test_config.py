import pytest
from pydantic import ValidationError

from src.config.settings import load_settings


def test_defaults_load(settings):
    assert settings.brand.name == "CURIOUS MINDS"
    assert settings.tts.voice == "en_US-joe-medium"
    v, h = settings.profile("vertical"), settings.profile("horizontal")
    assert (v.width, v.height, v.fps) == (1080, 1920, 30) and v.is_vertical
    assert (h.width, h.height, h.fps) == (1920, 1080, 30) and not h.is_vertical
    assert settings.content.short_duration == (60, 90)
    assert settings.content.long_duration == (360, 600)


def test_env_overrides():
    s = load_settings(environ={"CM__TTS__VOICE": "en_US-norman-medium", "CM__RENDER__CRF": "18"})
    assert s.tts.voice == "en_US-norman-medium" and s.render.crf == 18


def test_invalid_values_rejected():
    with pytest.raises(ValidationError):
        load_settings(environ={"CM__RENDER__CRF": "99"})
    with pytest.raises(ValidationError):
        load_settings(environ={"CM__AUDIO__MUSIC_GAIN_DB": "0"})   # music must stay below the voice


def test_secrets_only_from_env(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = load_settings(environ={})
    assert s.llm_api_key is None
    monkeypatch.setenv("LLM_API_KEY", "sk-ant-test-1234567890")
    assert s.llm_api_key == "sk-ant-test-1234567890"


def test_secret_redaction(monkeypatch, caplog):
    import logging
    from src.utils.logging_setup import RedactSecretsFilter
    monkeypatch.setenv("LLM_API_KEY", "supersecretvalue123")
    f = RedactSecretsFilter()
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "key=%s and sk-ant-abcdefghijkl", ("supersecretvalue123",), None)
    f.filter(rec)
    assert "supersecretvalue123" not in rec.getMessage() and "sk-ant-abcdefghijkl" not in rec.getMessage()
