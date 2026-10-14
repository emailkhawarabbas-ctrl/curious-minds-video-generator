"""TikTok / YouTube Shorts rendering profile (1080x1920, 9:16, 30 fps, H.264)."""
from __future__ import annotations

from src.config.settings import Settings
from src.rendering.renderer import EpisodeRenderer

OUTPUT_NAME = "curious_minds_shorts_9x16.mp4"


class VerticalRenderer(EpisodeRenderer):
    def __init__(self, settings: Settings):
        super().__init__(settings, "vertical")
        if not self.profile.is_vertical:
            raise ValueError("vertical profile must be portrait")
