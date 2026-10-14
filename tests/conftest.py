import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import src  # noqa: E402,F401  (fontconfig bootstrap)

from src.config.settings import load_settings  # noqa: E402


@pytest.fixture(scope="session")
def settings():
    return load_settings(environ={})


@pytest.fixture
def small_settings(tmp_path):
    """Settings with tiny render profiles for fast integration tests."""
    s = load_settings(environ={
        "CM__RENDER__WORKERS": "2", "CM__RENDER__PRESET": "ultrafast",
        "CM__PATHS__GENERATED": str(tmp_path / "generated"),
    })
    from src.config.settings import RenderProfile, SafeArea
    s.render.profiles["vertical"] = RenderProfile(width=270, height=480, fps=30,
                                                  safe=SafeArea(top=58, bottom=105, left=18, right=38),
                                                  caption_zone_y=0.695)
    s.render.profiles["horizontal"] = RenderProfile(width=480, height=270, fps=30,
                                                    safe=SafeArea(top=15, bottom=18, left=24, right=24),
                                                    caption_zone_y=0.885)
    return s


@pytest.fixture(scope="session")
def research_pack():
    from src.content.models import Fact, ResearchPack, Source
    src_ = [Source(id="S1", title="Dream — Wikipedia", url="https://en.wikipedia.org/wiki/Dream", provider="wikipedia",
                   tier="reference", snippet="Humans generally spend more than two hours dreaming per night."),
            Source(id="S2", title="Review", url="https://pubmed.ncbi.nlm.nih.gov/1/", provider="pubmed",
                   tier="peer_reviewed", snippet="People often cannot recall their dreams.")]
    facts = [Fact(id="F1", text="Humans generally spend more than two hours dreaming per night, and each dream lasts "
                              "around 5–20 minutes.", source_ids=["S1"], status="uncertain", numbers=["5", "20"]),
             Fact(id="F2", text="Dreams occur mainly in the rapid-eye movement (REM) stage of sleep.",
                  source_ids=["S1", "S2"], status="established"),
             Fact(id="F3", text="Several hypotheses suggest dreams may be associated with memory and emotions.",
                  source_ids=["S2"], status="hypothesis"),
             Fact(id="F4", text="One sleep cycle lasts about 90 minutes in adult humans.", source_ids=["S1"],
                  status="uncertain", numbers=["90"])]
    return ResearchPack(topic="Why Do We Dream?", niche="psychology", status="ok", sources=src_, facts=facts)
