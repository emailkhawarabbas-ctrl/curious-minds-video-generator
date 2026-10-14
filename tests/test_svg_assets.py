import math

import cairo
import pytest

from src.animation.asset_manager import ASSET_CATEGORIES, AssetManager
from src.animation.svg_loader import SvgError, load_svg_string, parse_path_d, parse_transform


def test_path_parser_commands():
    segs = parse_path_d("M10 10 h20 v20 H10 Z m5 5 c1 1 2 2 3 3 s4 4 5 5 q1 1 2 2 t3 3 a5 5 0 0 1 10 0")
    kinds = {s[0] for s in segs}
    assert kinds <= {"M", "L", "C", "Z"} and "C" in kinds


def test_compact_arc_flags():
    segs = parse_path_d("M0 0a10 10 0 0110 10")
    assert segs[-1][-2:] == pytest.approx((10, 10))


def test_transforms_compose():
    m = parse_transform("translate(10,20) scale(2) rotate(90)")
    a, b, c, d, e, f = m
    assert (e, f) == (10, 20)
    assert a == pytest.approx(0, abs=1e-9) and b == pytest.approx(2)


def test_anchor_and_meta():
    a = load_svg_string('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" data-tags="a,b">'
                        '<circle cx="50" cy="50" r="40" fill="#fff" stroke="#000" stroke-width="4"/>'
                        '<circle id="anchor-top" cx="50" cy="10" r="2"/></svg>')
    assert a.tags == ("a", "b") and "top" in a.anchors and len(a.shapes) == 1
    assert a.anchor("top", 0, 0, 100) == pytest.approx((0, -40))


def test_invalid_svg_rejected():
    with pytest.raises(SvgError):
        load_svg_string("<svg><text>no shapes</text></svg>")


@pytest.fixture(scope="module")
def library():
    return AssetManager()


def test_library_coverage(library):
    ids = set(library.ids())
    required = {"brain", "heart", "lungs", "stomach", "eye", "nervous_system", "blood_cells", "dna",  # human body
                "brain_activity", "memory_photos", "dream_cloud", "zzz", "thought_cloud", "habit_loop",
                "attention_target", "emotion_happy",                                                 # psychology
                "planet_saturn", "star", "lightning", "molecule", "atom", "weather_cloud_rain", "tree",
                "microscope",                                                                        # science
                "computer", "phone", "book", "building", "car", "clock", "chart_bars"}               # objects
    assert required <= ids, required - ids
    assert len(ids) >= 70


def test_every_asset_has_metadata_and_anchors(library):
    for aid in library.ids():
        rec = library.record(aid)
        assert rec.category in ASSET_CATEGORIES
        assert len(rec.tags) >= 4, aid
        assert "center" in rec.anchors and "top" in rec.anchors, aid
        assert rec.license


def test_every_asset_renders_and_draws_on(library):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 64)
    ctx = cairo.Context(surf)
    for aid in library.ids():
        a = library.get(aid)
        assert a.total_length > 0, aid
        for p in (0.3, 1.0):
            a.draw(ctx, 32, 32, 60, draw_progress=p)


def test_search_finds_relevant_assets(library):
    assert "brain" in library.search("how memories form in the brain", 4)
    assert "heart" in library.search("heart beat blood pump", 3)
