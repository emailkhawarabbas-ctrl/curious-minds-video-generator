"""Project-local font registration for Cairo (via fontconfig).

Cairo's text API resolves families through fontconfig. Instead of installing fonts
system-wide we write a small fontconfig file that includes the system configuration
plus ``assets/fonts`` and point ``FONTCONFIG_FILE`` at it. This must happen before the
first text is drawn in the process (child processes inherit the environment).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = PROJECT_ROOT / "assets" / "fonts"

# Brand typography
TITLE_FONT = "Luckiest Guy"      # thumbnails, title cards (Apache-2.0)
CAPTION_FONT = "Lilita One"      # captions, labels (OFL)
HAND_FONT = "Patrick Hand"       # hand-written doodle notes (OFL)

_CONF = """<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>
  <dir>{font_dir}</dir>
  <cachedir>{cache_dir}</cachedir>
</fontconfig>
"""


def ensure_fontconfig() -> Path:
    cache_dir = PROJECT_ROOT / "generated" / ".cache" / "fontconfig"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        conf = cache_dir / "fonts.conf"
    except OSError:  # read-only checkout: fall back to temp dir
        cache_dir = Path(tempfile.gettempdir()) / "curious_minds_fontconfig"
        cache_dir.mkdir(parents=True, exist_ok=True)
        conf = cache_dir / "fonts.conf"
    text = _CONF.format(font_dir=FONT_DIR, cache_dir=cache_dir)
    if not conf.exists() or conf.read_text() != text:
        conf.write_text(text)
    os.environ["FONTCONFIG_FILE"] = str(conf)
    return conf
