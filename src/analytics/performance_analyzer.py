"""Performance analysis over imported (real) analytics rows.

Rows are linked to produced episodes by matching titles against the generated metadata,
which gives each row its content pillar, format, hook text, duration and layouts used.
All statistics are computed from the stored rows only; groups with too few videos are
reported as "insufficient data" instead of guessed.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional

MIN_GROUP = 2


def load_metrics(store: Path) -> List[Dict]:
    db = store / "metrics.jsonl"
    if not db.exists():
        return []
    return [json.loads(l) for l in db.read_text().splitlines() if l.strip()]


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip()


def episode_index(generated: Path) -> Dict[str, Dict]:
    """title (normalised) -> episode info, from generated/*/metadata and scripts."""
    idx: Dict[str, Dict] = {}
    for rep in generated.glob("*/production_report.json"):
        root = rep.parent
        try:
            report = json.loads(rep.read_text())
        except json.JSONDecodeError:
            continue
        for fmt in ("short", "long"):
            meta = root / "metadata" / f"metadata_{fmt}.json"
            script = root / "scripts" / f"script_{fmt}.json"
            if not meta.exists():
                continue
            m = json.loads(meta.read_text())
            hook = ""
            layouts: List[str] = []
            if script.exists():
                s = json.loads(script.read_text())
                hook = s.get("hook", "")
            sb = root / "storyboards" / ("storyboard_vertical.json" if fmt == "short" else "storyboard_horizontal.json")
            if sb.exists():
                layouts = [sc["layout"] for sc in json.loads(sb.read_text()).get("scenes", [])]
            info = {"slug": root.name, "topic": report.get("topic"), "niche": report.get("niche"), "format": fmt,
                    "hook": hook, "duration_s": report.get("outputs", {}).get(fmt, {}).get("duration_s"),
                    "layouts": layouts}
            for title in m.get("titles", []):
                idx[_norm(title)] = info
            idx[_norm(report.get("topic", ""))] = info
    return idx


def hook_type(hook: str) -> str:
    h = hook.strip().lower()
    if h.startswith(("have you ever", "ever wonder", "did you ever")):
        return "have-you-ever question"
    if h.startswith(("what if", "imagine")):
        return "imagine / what-if"
    if "?" in h[:120]:
        return "direct question"
    if re.search(r"\d", h[:80]):
        return "surprising number"
    return "statement"


def length_bucket(sec: Optional[float]) -> str:
    if not sec:
        return "unknown"
    if sec < 60:
        return "<60s"
    if sec <= 90:
        return "60-90s"
    if sec < 360:
        return "1.5-6min"
    if sec <= 600:
        return "6-10min"
    return ">10min"


def enrich(rows: List[Dict], generated: Path) -> List[Dict]:
    idx = episode_index(generated)
    out = []
    for r in rows:
        info = idx.get(_norm(r.get("title", ""))) or {}
        if not info:
            # fuzzy: topic words contained in the title
            for k, v in idx.items():
                if k and k in _norm(r.get("title", "")):
                    info = v
                    break
        rr = dict(r)
        rr.update({"pillar": info.get("niche", "unlinked"), "topic": info.get("topic"), "hook_type":
                   hook_type(info.get("hook", "")) if info else "unknown", "format": info.get("format"),
                   "length_bucket": length_bucket(r.get("duration_s") or info.get("duration_s")),
                   "layouts": info.get("layouts", [])})
        out.append(rr)
    return out


def _agg(rows: List[Dict], key: str) -> Dict[str, Dict]:
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        groups[str(r.get(key))].append(r)
    res = {}
    for k, g in groups.items():
        def m(field):
            vals = [x[field] for x in g if x.get(field) is not None]
            return round(mean(vals), 4) if vals else None
        res[k] = {"videos": len(g), "avg_views": m("views"), "avg_completion_rate": m("completion_rate"),
                  "avg_view_duration_s": m("avg_view_duration_s"), "avg_shares": m("shares"),
                  "avg_likes": m("likes"), "sufficient_data": len(g) >= MIN_GROUP}
    return res


def analyze(rows: List[Dict]) -> Dict:
    if not rows:
        return {"status": "no_data", "message": "No analytics imported yet. Export CSVs from YouTube Studio / TikTok "
                                                "and run `python -m src.main analytics import`."}
    rank = sorted(rows, key=lambda r: (r.get("views") or 0), reverse=True)
    return {
        "status": "ok", "videos": len(rows),
        "totals": {f: sum((r.get(f) or 0) for r in rows) for f in ("views", "likes", "comments", "shares",
                                                                   "followers_gained", "subscribers_gained",
                                                                   "watch_time_hours")},
        "by_pillar": _agg(rows, "pillar"), "by_hook_type": _agg(rows, "hook_type"),
        "by_length": _agg(rows, "length_bucket"), "by_platform": _agg(rows, "platform"),
        "top_videos": [{"title": r.get("title"), "platform": r["platform"], "views": r.get("views"),
                        "completion_rate": r.get("completion_rate")} for r in rank[:5]],
    }


def best(group: Dict[str, Dict], metric: str = "avg_completion_rate") -> Optional[str]:
    cands = [(v[metric], k) for k, v in group.items() if v["sufficient_data"] and v.get(metric) is not None
             and k not in ("unknown", "unlinked", "None")]
    return max(cands)[1] if cands else None


def pillar_performance(rows: List[Dict], generated: Optional[Path] = None) -> Dict[str, float]:
    """Relative pillar score (avg completion rate, fallback avg views) for topic steering."""
    if not rows:
        return {}
    if generated is not None:
        rows = enrich(rows, generated)
    elif rows and "pillar" not in rows[0]:
        return {}
    agg = _agg(rows, "pillar")
    out = {}
    for p, v in agg.items():
        if p in ("human_body", "psychology", "science") and v["sufficient_data"]:
            score = v["avg_completion_rate"] if v["avg_completion_rate"] is not None else v["avg_views"]
            if score is not None:
                out[p] = score
    return out
