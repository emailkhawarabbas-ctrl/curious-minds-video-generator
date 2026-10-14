"""Logging configuration with secret redaction."""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

_SECRET_ENV = ("LLM_API_KEY", "ANTHROPIC_API_KEY", "RESEARCH_API_KEY", "TTS_API_KEY")
_KEY_PATTERNS = [re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), re.compile(r"tvly-[A-Za-z0-9_\-]{8,}")]


class RedactSecretsFilter(logging.Filter):
    """Replaces any configured secret value (and well-known key shapes) with ***."""

    def __init__(self) -> None:
        super().__init__()
        self.secrets = [v for k in _SECRET_ENV if (v := os.environ.get(k)) and len(v) >= 6]

    def redact(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "***")
        for pat in _KEY_PATTERNS:
            text = pat.sub("***", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        red = self.redact(msg)
        if red != msg:
            record.msg, record.args = red, None
        return True


def setup_logging(level: str = "INFO", log_file: Optional[Path] = None) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%H:%M:%S")
    redact = RedactSecretsFilter()
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(fmt)
        h.addFilter(redact)
        root.addHandler(h)
    for noisy in ("urllib3", "httpx", "httpcore", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
