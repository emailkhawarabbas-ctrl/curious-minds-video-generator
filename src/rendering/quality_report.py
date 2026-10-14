"""Human-readable quality-control report for one rendered video.

Combines the four review areas the channel cares about, each check with PASS / WARN / FAIL
and the reason, so a reviewer can see in one page *why* a video passed or failed:

  VOICE      narration QC (clarity, clipping, cut-offs, pacing, intonation, intelligibility)
  VISUALS    topic-specific illustrations, niche identity, demonstrations, repetition, character
  STORY      hook strength, curiosity gap, mini-hooks, discoveries, payoff, repetition
  TECHNICAL  ffprobe: resolution, fps, duration, A/V sync, blank/frozen frames, loudness, subtitles

Written to ``review/quality_report_<format>.md`` next to the machine-readable JSON files.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List


def _icon(level: str) -> str:
    return {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}[level]


def _voice_rows(nqc: Dict) -> List[str]:
    rows = []
    for c in nqc.get("checks", []):
        level = "pass" if c["passed"] else ("fail" if c.get("severity") == "hard" else "warn")
        rows.append(f"| {_icon(level)} | {c['check']} | {c['detail']} |")
    return rows


def write_quality_report(path: Path, topic: str, fmt: str, video: str, nqc: Dict, review: Dict, qc: Dict,
                         voice: Dict, passed: bool, reasons: List[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    story = [c for c in review.get("checks", []) if c.get("area") == "story"]
    visual = [c for c in review.get("checks", []) if c.get("area") in ("visuals", "pacing")]
    o = nqc.get("overall", {})
    lines = [
        f"# Quality report — {topic} ({fmt})", "",
        f"**Video:** `{video}`  ",
        f"**Result:** {'PASSED' if passed else 'FAILED'}", "",
    ]
    if reasons:
        lines += ["**Why it failed:**", ""] + [f"- {r}" for r in reasons] + [""]
    lines += [
        "## Voice", "",
        f"Narrator: {voice.get('label')} — {voice.get('provider')} `{voice.get('voice')}` "
        f"(profile `{voice.get('profile')}`, expressiveness {voice.get('expressiveness')})"
        + (f" — **fallback used**: {voice['fallback']}" if voice.get("fallback") else ""), "",
        f"Pace {nqc.get('words_per_second')} words/s · intonation {o.get('prosody_std')} st · "
        f"harmonicity {o.get('harmonicity')} · jitter {o.get('jitter')} st · peak {o.get('peak_dbfs')} dBFS"
        + (f" · Whisper WER {nqc['asr']['wer']:.1%}" if nqc.get("asr", {}).get("ran") else ""), "",
        "| Result | Check | Detail |", "|---|---|---|", *_voice_rows(nqc), "",
        "## Visuals & pacing", "",
        f"Theme: **{review.get('visuals', {}).get('theme', '?')}** · mean asset relevance "
        f"{review.get('visuals', {}).get('mean_asset_relevance', '?')} · demonstrations: "
        f"{', '.join(review.get('visuals', {}).get('demos', [])) or 'none'}", "",
        "| Result | Check | Detail |", "|---|---|---|",
        *[f"| {_icon(c['level'])} | {c['check']} | {c['detail']} |" for c in visual], "",
        "## Storytelling", "",
        f"Hook: “{review.get('story', {}).get('hook', {}).get('first_sentence', '')}” "
        f"({review.get('story', {}).get('hook', {}).get('score', '?')}/10)", "",
        "| Result | Check | Detail |", "|---|---|---|",
        *[f"| {_icon(c['level'])} | {c['check']} | {c['detail']} |" for c in story], "",
        "## Technical", "",
        "| Result | Check | Value | Expected |", "|---|---|---|---|",
        *[f"| {'PASS' if c['passed'] else 'FAIL'} | {c['check']} | {c.get('value')} | {c.get('expected')} |"
          for c in qc.get("checks", [])], "",
        "_Storytelling and visual checks are a heuristic pre-render checklist. Actual audience retention is only "
        "known from platform analytics (`python -m src.main analytics ...`)._",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
