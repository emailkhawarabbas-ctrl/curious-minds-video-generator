"""Provider-independent LLM interface with an Anthropic (Claude) implementation.

The LLM only ever returns *data* (JSON validated against a schema and then against
our Pydantic models). Nothing it returns is executed.
"""
from __future__ import annotations

import json
import logging
import re
from string import Template
from typing import Any, Dict, Optional

from src.config.settings import PROJECT_ROOT, Settings

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    """No API key / provider configured."""


class LLMError(RuntimeError):
    """The provider failed, refused, or returned unusable output."""


def load_prompt(name: str, **values: Any) -> str:
    """Load prompts/<name>.md and substitute $placeholders (safe_substitute)."""
    text = (PROJECT_ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8")
    return Template(text).safe_substitute(**{k: (v if isinstance(v, str) else json.dumps(v, indent=1))
                                              for k, v in values.items()})


class LLMClient:
    name = "base"

    def generate_json(self, system: str, user: str, schema: Dict[str, Any], max_tokens: Optional[int] = None) -> Dict:
        raise NotImplementedError


class AnthropicClient(LLMClient):
    """Claude via the official Anthropic SDK.

    * model / effort from settings (default ``claude-opus-5-5``, effort ``high``)
    * adaptive thinking (default on this model), streaming for long outputs
    * JSON-schema structured output (``output_config.format``)
    * optional server-side refusal fallback (``fallbacks: "default"``)
    """

    name = "anthropic"

    def __init__(self, settings: Settings):
        key = settings.llm_api_key
        if not key:
            raise LLMUnavailable("LLM_API_KEY (or ANTHROPIC_API_KEY) is not set")
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise LLMUnavailable("the 'anthropic' package is not installed") from exc
        import anthropic
        self._anthropic = anthropic
        self.cfg = settings.llm
        self.client = anthropic.Anthropic(api_key=key, timeout=self.cfg.timeout_s, max_retries=self.cfg.max_retries)

    def _request(self, system: str, user: str, schema: Dict[str, Any], max_tokens: int, fallback: bool):
        params: Dict[str, Any] = dict(
            model=self.cfg.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={"effort": self.cfg.effort, "format": {"type": "json_schema", "schema": schema}},
        )
        if fallback:
            with self.client.beta.messages.stream(betas=["server-side-fallback-2026-07-01"],
                                                  extra_body={"fallbacks": "default"}, **params) as stream:
                return stream.get_final_message()
        with self.client.messages.stream(**params) as stream:
            return stream.get_final_message()

    def generate_json(self, system: str, user: str, schema: Dict[str, Any], max_tokens: Optional[int] = None) -> Dict:
        a = self._anthropic
        max_tokens = max_tokens or self.cfg.max_tokens
        try:
            try:
                msg = self._request(system, user, schema, max_tokens, self.cfg.server_side_fallback)
            except a.BadRequestError as exc:
                if self.cfg.server_side_fallback and "fallback" in str(exc).lower():
                    log.warning("server-side fallback not accepted (%s); retrying without it", exc.message)
                    msg = self._request(system, user, schema, max_tokens, False)
                else:
                    raise
        except a.AuthenticationError as exc:
            raise LLMError("LLM authentication failed (check LLM_API_KEY)") from exc
        except a.RateLimitError as exc:
            raise LLMError("LLM rate limited; try again later") from exc
        except a.APIConnectionError as exc:
            raise LLMError(f"LLM connection error: {exc}") from exc
        except a.APIStatusError as exc:
            raise LLMError(f"LLM API error {exc.status_code}: {exc.message}") from exc
        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            raise LLMError(f"LLM declined the request ({getattr(details, 'category', None)})")
        if msg.stop_reason == "max_tokens":
            raise LLMError("LLM output truncated (max_tokens); increase llm.max_tokens")
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                return json.loads(m.group())
            raise LLMError("LLM returned non-JSON output")


def get_llm(settings: Settings) -> Optional[LLMClient]:
    """Return a configured client, or None when no provider is available."""
    if settings.llm.provider == "none":
        return None
    try:
        return AnthropicClient(settings)
    except LLMUnavailable as exc:
        log.info("LLM unavailable: %s", exc)
        return None
