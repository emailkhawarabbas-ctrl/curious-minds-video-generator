"""Curious Minds — automated colorful 2D cartoon & doodle educational video generator."""
from src.utils.fonts import ensure_fontconfig as _ensure_fontconfig

# Must run before Cairo touches fontconfig so the bundled brand fonts are found.
_ensure_fontconfig()

__version__ = "1.0.0"
