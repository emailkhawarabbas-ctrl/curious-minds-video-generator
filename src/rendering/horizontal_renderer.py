"""YouTube long-form rendering profile (1920x1080, 16:9, 30 fps, H.264)."""
from __future__ import annotations

from src.config.settings import Settings
from src.rendering.renderer import EpisodeRenderer

OUTPUT_NAME = "curious_minds_youtube_16x9.mp4"


class HorizontalRenderer(EpisodeRenderer):
    def __init__(self, settings: Settings):
        super().__init__(settings, "horizontal")
        if self.profile.is_vertical:
            raise ValueError("horizontal profile must be landscape")
