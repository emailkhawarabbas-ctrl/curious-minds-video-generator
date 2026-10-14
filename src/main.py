"""Curious Minds command-line interface.

Examples:
  python -m src.main generate --topic "Why Do We Dream?" --niche psychology
  python -m src.main generate --topic "Why Do We Hiccup?" --niche human_body --no-long
  python -m src.main research --topic "How Do Magnets Work?"
  python -m src.main qc --video generated/why_do_we_dream/curious_minds_shorts_9x16.mp4 --profile vertical
  python -m src.main voice preview --extra am_puck am_fenrir
  python -m src.main assets index
  python -m src.main analytics import --platform youtube --csv export.csv
  python -m src.main analytics report
  python -m src.main topics suggest --n 6
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

import src  # noqa: F401  (font bootstrap)
from src.config.settings import PROJECT_ROOT, load_settings
from src.utils.logging_setup import setup_logging


def _bool(v: str) -> bool:
    if isinstance(v, bool):
        return v
    if v.lower() in ("1", "true", "yes", "y", "on"):
        return True
    if v.lower() in ("0", "false", "no", "n", "off"):
        return False
    raise argparse.ArgumentTypeError(f"expected true/false, got {v!r}")


def cmd_generate(a, settings) -> int:
    from src.pipeline import GenerationRequest, Pipeline
    voice = a.voice.strip() if a.voice else None   # profile label/key, Kokoro voice or Piper id (see tts_engine)
    req = GenerationRequest(topic=a.topic, niche=a.niche, generate_short=a.short, generate_long=a.long,
                            short_duration=a.short_duration, long_duration=a.long_duration * 60 if a.long_duration <= 10
                            else a.long_duration, voice=voice, subtitles=a.subtitles, thumbnail=a.thumbnail,
                            script_source=a.script_source, output_root=Path(a.out) if a.out else None)
    manifest = Pipeline(settings).run(req)
    print(json.dumps({"status": manifest["status"], "outputs": manifest["outputs"],
                      "report": str((Path(a.out) if a.out else settings.paths.generated) / manifest["slug"] /
                                    "production_report.json")}, indent=2))
    return 0 if manifest["status"] == "success" else 1


def cmd_voice(a, settings) -> int:
    from src.audio.tts_engine import resolve_voice
    from src.audio.voice_preview import preview
    if a.voice:
        resolve_voice(settings, a.voice)
    out = Path(a.out) if a.out else settings.paths.generated / "voice_preview"
    rep = preview(settings, out, extra_voices=a.extra or [], asr=not a.no_asr)
    print((out / "voice_comparison.md").read_text(encoding="utf-8"))
    return 0 if any("error" not in r for r in rep["candidates"]) else 1


def cmd_research(a, settings) -> int:
    from src.research.researcher import Researcher
    pack = Researcher(settings).research(a.topic, a.niche)
    out = Path(a.out) if a.out else None
    text = pack.model_dump_json(indent=2)
    if out:
        out.write_text(text)
    print(json.dumps({"status": pack.status, "providers": pack.providers, "sources": len(pack.sources),
                      "facts": len(pack.facts)}, indent=2))
    return 0 if pack.status != "unavailable" else 1


def cmd_qc(a, settings) -> int:
    from src.rendering.quality_control import check_video
    p = settings.profile(a.profile)
    rng = settings.content.short_duration if p.is_vertical else settings.content.long_duration
    rep = check_video(Path(a.video), p.width, p.height, p.fps, rng, settings.audio.target_lufs,
                      Path(a.srt) if a.srt else None)
    print(json.dumps(rep, indent=2))
    return 0 if rep["passed"] else 1


def cmd_assets(a, settings) -> int:
    from src.animation.asset_manager import AssetManager
    m = AssetManager()
    if a.action == "index":
        print("wrote", m.write_manifest(), f"({len(m.ids())} assets)")
    elif a.action == "list":
        for i in m.ids():
            r = m.record(i)
            print(f"{r.category:12s} {i:24s} {', '.join(r.tags[:6])}")
    elif a.action == "search":
        print(m.search(a.query or "", 8))
    return 0


def cmd_analytics(a, settings) -> int:
    from src.analytics.csv_importer import import_csv
    from src.analytics.weekly_report import build_weekly_report
    store = settings.paths.generated / "analytics"
    if a.action == "import":
        n = import_csv(Path(a.csv), a.platform, store)
        print(f"imported {n} rows from {a.csv} ({a.platform})")
        return 0
    if a.action == "report":
        path = build_weekly_report(store, settings.paths.generated)
        print("wrote", path)
        return 0
    return 1


def cmd_topics(a, settings) -> int:
    from src.analytics.performance_analyzer import load_metrics, pillar_performance
    from src.content.topic_generator import suggest_topics
    store = settings.paths.generated / "analytics"
    perf = pillar_performance(load_metrics(store)) if store.exists() else None
    print(json.dumps(suggest_topics(a.n, settings.paths.generated, perf or None), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="curious-minds", description="Curious Minds educational video generator")
    ap.add_argument("--config", help="optional YAML config overriding config/default.yaml")
    ap.add_argument("--log-level", default="INFO")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="research, write, animate, narrate and render an episode")
    g.add_argument("--topic", required=True)
    g.add_argument("--niche", default="mixed", choices=["science", "psychology", "human_body", "mixed"])
    g.add_argument("--short", type=_bool, default=True, help="generate the 9:16 short (true/false)")
    g.add_argument("--long", type=_bool, default=True, help="generate the 16:9 long-form video (true/false)")
    g.add_argument("--no-short", dest="short", action="store_false")
    g.add_argument("--no-long", dest="long", action="store_false")
    g.add_argument("--short-duration", type=float, default=75, help="seconds (60-90)")
    g.add_argument("--long-duration", type=float, default=8, help="minutes (6-10) or seconds (360-600)")
    g.add_argument("--voice", default=None,
                   help="voice profile label/key (e.g. 'US English Friendly Male', energetic), a Kokoro voice "
                        "(am_michael or a blend) or a Piper voice id")
    g.add_argument("--subtitles", type=_bool, default=True)
    g.add_argument("--thumbnail", type=_bool, default=True)
    g.add_argument("--script-source", choices=["auto", "llm", "curated", "offline"], default=None)
    g.add_argument("--out", default=None, help="output root (default: generated/)")
    g.set_defaults(func=cmd_generate)

    v = sub.add_parser("voice", help="narration voice tools")
    v.add_argument("action", choices=["preview"])
    v.add_argument("--voice", help="profile/voice to treat as the default for this preview")
    v.add_argument("--extra", nargs="*", help="extra voices to compare, e.g. am_puck am_fenrir")
    v.add_argument("--out", help="output dir (default: generated/voice_preview)")
    v.add_argument("--no-asr", action="store_true", help="skip the Whisper intelligibility measurement")
    v.set_defaults(func=cmd_voice)

    r = sub.add_parser("research", help="run topic research only")
    r.add_argument("--topic", required=True)
    r.add_argument("--niche", default="mixed")
    r.add_argument("--out")
    r.set_defaults(func=cmd_research)

    q = sub.add_parser("qc", help="quality-check a rendered video")
    q.add_argument("--video", required=True)
    q.add_argument("--profile", choices=["vertical", "horizontal"], required=True)
    q.add_argument("--srt")
    q.set_defaults(func=cmd_qc)

    s = sub.add_parser("assets", help="asset library tools")
    s.add_argument("action", choices=["index", "list", "search"])
    s.add_argument("--query")
    s.set_defaults(func=cmd_assets)

    an = sub.add_parser("analytics", help="import platform CSV exports / build weekly reports")
    an.add_argument("action", choices=["import", "report"])
    an.add_argument("--csv")
    an.add_argument("--platform", choices=["youtube", "tiktok"])
    an.set_defaults(func=cmd_analytics)

    t = sub.add_parser("topics", help="suggest next topics")
    t.add_argument("action", choices=["suggest"])
    t.add_argument("--n", type=int, default=6)
    t.set_defaults(func=cmd_topics)
    return ap


def main(argv=None) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    a = build_parser().parse_args(argv)
    settings = load_settings(Path(a.config) if a.config else None)
    log_file = None
    if a.cmd == "generate":
        from src.utils.text import slugify
        root = Path(a.out) if a.out else settings.paths.generated
        log_file = root / slugify(a.topic) / "logs" / "generation.log"
    setup_logging(a.log_level, log_file)
    return a.func(a, settings)


if __name__ == "__main__":
    sys.exit(main())
