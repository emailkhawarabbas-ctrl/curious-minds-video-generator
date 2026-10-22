"""Fact extraction from gathered sources and fact-checking of scripts.

Extraction is deliberately conservative and extractive: facts are sentences that
literally appear in a retrieved source, each linked to its source id. Status:

  * ``disputed``    — the sentence itself talks about debate / controversy / disagreement
  * ``hypothesis``  — hedged or theory language (theory, may, might, suggests, thought to ...)
  * ``established`` — unhedged statement from an authoritative or peer-reviewed source,
                      or the same claim corroborated by two independent sources
  * ``uncertain``   — everything else (e.g. single reference-tier source)

Script checking (``check_script``) flags:
  * numbers / statistics that do not appear in any retrieved source text
  * medical-advice phrasing (diagnosis, treatment, dosage, "you should take ...")
  * hypothesis-level claims stated without hedging (warning)
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

from src.content.models import Fact, ResearchPack, Script, Source

HEDGE = re.compile(r"\b(theor(y|ies|ize)|hypothes[ie]s|may|might|could|suggest(s|ed)?|believed?|thought to|"
                   r"possibl[ey]|perhaps|likely|unclear|unknown|propos(e|ed|es)|speculat\w*|some (researchers|scientists|experts))\b",
                   re.I)
DISPUTE = re.compile(r"\b(debat\w*|controvers\w*|disput\w*|disagree\w*|contested|no consensus|conflicting)\b", re.I)
NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:%|percent|per cent)?")
NUMBER_WORDS = {"two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
                "nine": "9", "ten": "10", "twenty": "20", "ninety": "90", "hundred": "100"}
MEDICAL_ADVICE = re.compile(r"\b(you should (take|stop|start)|take \d+ ?mg|dosage|prescri\w+ yourself|"
                            r"cures?|guaranteed to|diagnos(e|is) yourself|instead of (seeing|asking) (a|your) doctor)\b",
                            re.I)
# Health-page instructions to the reader ("stop exercising and seek help right away") are not facts to narrate;
# fact extraction skips them (scripts may still add a "talk to a doctor" disclaimer)
HEALTH_INSTRUCTION = re.compile(r"\b(seek (medical |professional |emergency )?(help|care|attention|treatment)|"
                                r"(see|call|talk to|talk with|consult|ask) (a|your) (doctor|health ?care provider)|"
                                r"stop (exercising|taking)|call 911)\b", re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _sentences(text: str) -> List[str]:
    out: List[str] = []
    # split on line breaks first so section headings never merge into sentences
    for para in re.split(r"\n+", text or ""):
        para = re.sub(r"\[\d+\]", "", re.sub(r"\s+", " ", para)).strip()
        if not para or not re.search(r"[.!?][\"')]*$", para):
            continue
        out += [s.strip() for s in SENT_SPLIT.split(para) if s.strip()]
    return out


def _norm_tokens(s: str) -> set:
    return {w for w in re.findall(r"[a-z]{4,}", s.lower())}


def extract_facts(topic: str, sources: List[Source], texts: Dict[str, str],
                  max_facts: int = 60) -> Tuple[List[Fact], List[str]]:
    from src.research.researcher import _stem, keywords  # local import to avoid a cycle
    kws = [_stem(k) for k in keywords(topic)]
    cands: List[Tuple[float, str, Source]] = []
    for src in sources:
        for sent in _sentences(texts.get(src.id, "")):
            n_words = len(sent.split())
            if n_words < 7 or n_words > 45:
                continue
            low = sent.lower()
            if not any(k in low for k in kws):
                continue
            if re.search(r"(==|\bsee also\b|\bisbn\b|\bdoi\b|http)", low):
                continue
            if MEDICAL_ADVICE.search(sent):   # a script quoting it would fail the fact-check
                continue
            if HEALTH_INSTRUCTION.search(sent):
                continue
            if re.match(r"^(here,? we|in this (review|study|paper|article)|this (review|study|paper)|we (review|discuss|summari[sz]e)|finally,? we)", low):
                continue
            score = {"peer_reviewed": 3, "authoritative": 3, "reference": 1.5, "general": 1}[src.tier]
            score += 0.5 if NUMBER.search(sent) else 0
            score -= 0.02 * abs(n_words - 20)
            cands.append((score, sent, src))
    cands.sort(key=lambda x: -x[0])
    facts: List[Fact] = []
    seen: List[set] = []
    uncertain: List[str] = []
    for score, sent, src in cands:
        toks = _norm_tokens(sent)
        dup_of = None
        for i, prev in enumerate(seen):
            if toks and len(toks & prev) / max(1, len(toks | prev)) > 0.55:
                dup_of = i
                break
        if dup_of is not None:
            f = facts[dup_of]
            if src.id not in f.source_ids:
                f.source_ids.append(src.id)
                if f.status == "uncertain":
                    f.status = "established"
                    f.note = "corroborated by multiple sources"
            continue
        if len(facts) >= max_facts:
            continue
        if DISPUTE.search(sent):
            status = "disputed"
        elif HEDGE.search(sent):
            status = "hypothesis"
        elif src.tier in ("authoritative", "peer_reviewed"):
            status = "established"
        else:
            status = "uncertain"
        nums = [m.group().strip() for m in NUMBER.finditer(sent)]
        facts.append(Fact(id=f"F{len(facts) + 1}", text=sent, source_ids=[src.id], status=status, numbers=nums))
        seen.append(toks)
        if status in ("disputed", "hypothesis"):
            uncertain.append(sent)
    return facts, uncertain[:25]


def _numbers_in(text: str) -> List[str]:
    # "23%", "23 %", "23 percent" and "23 per cent" are the same number
    out = [re.sub(r"\s*(%|percent|per cent)$", "", m.group().strip()).replace(",", "") for m in NUMBER.finditer(text)]
    for w, d in NUMBER_WORDS.items():
        if re.search(rf"\b{w}\b", text, re.I):
            out.append(d)
    return out


def check_script(script: Script, research: ResearchPack, source_texts: Optional[Dict[str, str]] = None,
                 allowed_numbers: Iterable[str] = ()) -> Dict:
    """Return a fact-check report. ``passed`` is False when unsupported numbers or medical advice appear."""
    corpus = " ".join([f.text for f in research.facts] + [s.snippet for s in research.sources]
                      + list((source_texts or {}).values()))
    corpus_nums = set(_numbers_in(corpus)) | set(allowed_numbers)
    issues, warnings = [], []
    hyp_terms = set()
    for f in research.facts:
        if f.status in ("hypothesis", "disputed"):
            hyp_terms |= {w for w in re.findall(r"[a-z]{7,}", f.text.lower())}
    for beat in script.beats:
        text = beat.narration
        for n in set(_numbers_in(text)):
            # small counting numbers used for structure ("three reasons") are not statistics
            if n in {"1", "2", "3", "4", "5"} and not re.search(rf"{n}\s?(%|percent|hours?|minutes?|years?)", text):
                continue
            if n not in corpus_nums:
                issues.append({"beat": beat.id, "type": "unsupported_number", "detail": n, "text": text})
        if MEDICAL_ADVICE.search(text):
            issues.append({"beat": beat.id, "type": "medical_advice", "detail": MEDICAL_ADVICE.search(text).group(),
                           "text": text})
        if beat.fact_ids:
            missing = [fid for fid in beat.fact_ids if not any(f.id == fid for f in research.facts)]
            if missing:
                warnings.append({"beat": beat.id, "type": "unknown_fact_ids", "detail": missing})
        low = text.lower()
        if hyp_terms and not HEDGE.search(text) and len({w for w in re.findall(r"[a-z]{7,}", low)} & hyp_terms) >= 3:
            warnings.append({"beat": beat.id, "type": "possibly_unhedged_hypothesis", "text": text})
    cited = sorted({fid for b in script.beats for fid in b.fact_ids})
    return {"passed": not issues, "issues": issues, "warnings": warnings, "cited_fact_ids": cited,
            "beats_checked": len(script.beats), "research_status": research.status}
