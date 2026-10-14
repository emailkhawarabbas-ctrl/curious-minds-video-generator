"""Import manual CSV exports from YouTube Studio and TikTok analytics.

Column names differ between export versions and languages of the UI, so columns are
mapped through alias lists to one canonical schema. Rows are appended to
``generated/analytics/metrics.jsonl`` (de-duplicated by platform + video + date).
Only real exported numbers are stored; missing metrics stay empty (never estimated).
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

CANONICAL = ["platform", "video_id", "title", "published", "views", "avg_view_duration_s", "completion_rate",
             "watch_time_hours", "likes", "comments", "shares", "followers_gained", "subscribers_gained",
             "returning_viewers", "duration_s", "period_end"]

ALIASES: Dict[str, List[str]] = {
    "video_id": ["content", "video id", "video_id", "id", "video link", "post id"],
    "title": ["video title", "title", "video", "post title", "caption", "content title"],
    "published": ["video publish time", "publish time", "published", "post time", "date posted", "upload date",
                  "date"],
    "views": ["views", "video views", "total views", "plays"],
    "avg_view_duration_s": ["average view duration", "avg. view duration", "average watch time",
                            "avg watch time", "average watch time (s)"],
    "completion_rate": ["average percentage viewed (%)", "average percentage viewed", "watched full video (%)",
                        "completion rate", "watched full video", "full video watched rate"],
    "watch_time_hours": ["watch time (hours)", "watch time", "total play time (hours)", "total watch time (hours)"],
    "likes": ["likes", "likes (vs. dislikes)", "hearts"],
    "comments": ["comments added", "comments"],
    "shares": ["shares"],
    "followers_gained": ["new followers", "followers gained", "followers"],
    "subscribers_gained": ["subscribers", "subscribers gained", "new subscribers"],
    "returning_viewers": ["returning viewers", "returning viewer"],
    "duration_s": ["duration", "video length", "length"],
}


def _num(v: Optional[str]) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s or s in ("-", "—", "N/A"):
        return None
    if re.match(r"^\d+:\d{2}(:\d{2})?$", s):          # h:mm:ss or m:ss
        parts = [int(x) for x in s.split(":")]
        return float(sum(p * 60 ** i for i, p in enumerate(reversed(parts))))
    s = s.rstrip("%s").strip()
    m = re.match(r"^(-?\d+(?:\.\d+)?)([kKmM])?$", s)
    if not m:
        return None
    val = float(m.group(1))
    return val * (1e3 if m.group(2) in ("k", "K") else 1e6 if m.group(2) in ("m", "M") else 1)


def _map_columns(header: List[str]) -> Dict[str, str]:
    norm = {h: h.strip().lower() for h in header}
    out: Dict[str, str] = {}
    for canon, aliases in ALIASES.items():
        for h, n in norm.items():
            if n in aliases:
                out[canon] = h
                break
    return out


def parse_rows(csv_path: Path, platform: str) -> List[Dict]:
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")
        cols = _map_columns(reader.fieldnames)
        if "views" not in cols:
            raise ValueError(f"could not find a views column in {reader.fieldnames}")
        rows = []
        for raw in reader:
            title = (raw.get(cols.get("title", ""), "") or "").strip()
            vid = (raw.get(cols.get("video_id", ""), "") or "").strip()
            if title.lower() in ("total", "totals") or vid.lower() in ("total", "totals") or (not title and not vid):
                continue   # summary rows of the export
            r: Dict = {"platform": platform}
            for canon in CANONICAL[1:]:
                src = cols.get(canon)
                val = raw.get(src) if src else None
                r[canon] = (val.strip() if isinstance(val, str) else val) if canon in ("video_id", "title",
                                                                                       "published") else _num(val)
            if r.get("completion_rate") is not None and r["completion_rate"] > 1:
                r["completion_rate"] = r["completion_rate"] / 100.0
            r["video_id"] = r.get("video_id") or title
            rows.append(r)
        return rows


def import_csv(csv_path: Path, platform: str, store: Path) -> int:
    if platform not in ("youtube", "tiktok"):
        raise ValueError("platform must be youtube or tiktok")
    rows = parse_rows(csv_path, platform)
    store.mkdir(parents=True, exist_ok=True)
    db = store / "metrics.jsonl"
    existing = {}
    if db.exists():
        for line in db.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                existing[(d["platform"], d["video_id"], d.get("period_end"))] = d
    now = datetime.now(timezone.utc).date().isoformat()
    for r in rows:
        r["period_end"] = r.get("period_end") or now
        r["imported_at"] = now
        r["source_file"] = csv_path.name
        existing[(r["platform"], r["video_id"], r["period_end"])] = r
    db.write_text("".join(json.dumps(d) + "\n" for d in existing.values()))
    return len(rows)
