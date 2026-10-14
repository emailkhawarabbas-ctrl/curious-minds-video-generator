"""Weekly performance report (Markdown + JSON) built only from imported analytics."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

from src.analytics.performance_analyzer import analyze, best, enrich, load_metrics, pillar_performance
from src.content.topic_generator import suggest_topics


def _in_week(r: Dict, start: date) -> bool:
    for f in ("published", "period_end", "imported_at"):
        v = r.get(f)
        if not v:
            continue
        try:
            d = datetime.fromisoformat(str(v)[:10]).date()
        except ValueError:
            continue
        return d >= start
    return True


def build_weekly_report(store: Path, generated: Path, today: date = None) -> Path:
    today = today or date.today()
    start = today - timedelta(days=7)
    rows = enrich(load_metrics(store), generated)
    week = [r for r in rows if _in_week(r, start)]
    analysis = analyze(week or rows)
    perf = pillar_performance(week or rows)
    suggestions = suggest_topics(6, generated, perf or None)
    store.mkdir(parents=True, exist_ok=True)
    report = {"week_start": start.isoformat(), "week_end": today.isoformat(), "rows_this_week": len(week),
              "rows_total": len(rows), "analysis": analysis, "pillar_scores": perf, "topic_suggestions": suggestions}
    jpath = store / f"weekly_report_{today.isoformat()}.json"
    jpath.write_text(json.dumps(report, indent=2))
    md: List[str] = [f"# Curious Minds — weekly report ({start} → {today})", ""]
    if analysis["status"] != "ok":
        md += [analysis["message"], ""]
    else:
        t = analysis["totals"]
        md += [f"Videos analysed: **{analysis['videos']}** (this week: {len(week)})", "",
               f"Views {t['views']:.0f} · Likes {t['likes']:.0f} · Comments {t['comments']:.0f} · "
               f"Shares {t['shares']:.0f} · Followers +{t['followers_gained']:.0f} · "
               f"Subscribers +{t['subscribers_gained']:.0f} · Watch time {t['watch_time_hours']:.1f} h", ""]
        for title, key in (("Best content pillar", "by_pillar"), ("Best hook style", "by_hook_type"),
                           ("Best video length", "by_length")):
            b = best(analysis[key])
            md.append(f"- **{title}:** {b or 'insufficient data (need ≥2 linked videos per group)'}")
        md += ["", "## Top videos", ""] + [
            f"- {v['title']} ({v['platform']}): {v['views']:.0f} views"
            + (f", completion {v['completion_rate']:.0%}" if v.get("completion_rate") is not None else "")
            for v in analysis["top_videos"]]
        md += ["", "## By pillar", "", "| Pillar | Videos | Avg views | Avg completion |", "|---|---|---|---|"]
        for k, v in analysis["by_pillar"].items():
            comp = f"{v['avg_completion_rate']:.0%}" if v["avg_completion_rate"] is not None else "—"
            md.append(f"| {k} | {v['videos']} | {v['avg_views'] or 0:.0f} | {comp} |")
    md += ["", "## Suggested next topics", ""] + [f"- {s['topic']} ({s['niche']})" for s in suggestions]
    md += ["", "_All numbers come from imported platform CSV exports; nothing is estimated._"]
    mpath = store / f"weekly_report_{today.isoformat()}.md"
    mpath.write_text("\n".join(md), encoding="utf-8")
    return mpath
