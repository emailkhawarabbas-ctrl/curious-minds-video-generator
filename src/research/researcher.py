"""Topic research through configurable providers.

Keyless providers (always available when online):
  * wikipedia   — MediaWiki search + plain-text extracts (reference tier; used for context)
  * medlineplus — U.S. National Library of Medicine health topics web service (authoritative)
  * pubmed      — NCBI E-utilities, review articles + abstracts (peer-reviewed)
Optional:
  * tavily      — web search restricted to authoritative domains (needs RESEARCH_API_KEY)

Every provider failure is recorded verbatim in the research pack; nothing is ever
invented when a provider is unavailable. If no provider returns anything the pack
status is ``unavailable`` and downstream script generation refuses to run (unless
``content.allow_unresearched`` is set explicitly).
"""
from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from typing import Callable, Dict, List, Optional

import requests

from src.config.settings import Settings
from src.content.models import ResearchPack
from src.research.fact_checker import extract_facts
from src.research.source_manager import SourceManager

log = logging.getLogger(__name__)

STOPWORDS = set("""a an the do does did why how what when where who which is are was were be been being we you
your our us i me my it its this that these those of in on at to for from by with about into over under can
could should would will just really actually ever happen happens happening there their they them and or
but if so as than then too very much many most more some any all every each make makes made get gets""".split())


def keywords(topic: str) -> List[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-']+", topic.lower())
    out = []
    for w in words:
        if w in STOPWORDS or len(w) < 3:
            continue
        out.append(w)
    return out or [topic.lower()]


# Small related-term map used for query expansion when no LLM is available.
RELATED = {
    "dream": ["REM sleep", "sleep"], "nightmare": ["sleep", "REM sleep"], "sleep": ["sleep"],
    "memory": ["memory consolidation", "brain"], "memories": ["memory", "brain"], "heart": ["heart"],
    "habit": ["habit formation", "behavior"], "habits": ["habit formation", "behavior"],
    "emotion": ["emotion", "brain"], "emotions": ["emotion", "brain"], "yawn": ["yawning"],
    "hiccup": ["hiccups"], "hiccups": ["hiccups"], "goosebumps": ["goose bumps"],
}


def related_terms(topic: str) -> List[str]:
    out: List[str] = []
    for k in keywords(topic):
        for key, vals in RELATED.items():
            if k.startswith(key):
                out += [v for v in vals if v not in out]
    return out


def relevance(text: str, topic: str) -> int:
    stems = [k[:5] for k in keywords(topic)]
    low = (text or "").lower()
    return sum(low.count(st) for st in stems)


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


class ResearchError(RuntimeError):
    pass


class Researcher:
    def __init__(self, settings: Settings, session: Optional[requests.Session] = None):
        self.s = settings
        self.http = session or requests.Session()
        self.http.headers.update({"User-Agent": settings.research.user_agent})
        self.timeout = settings.research.timeout_s
        self.n = settings.research.max_sources_per_provider
        self.source_texts: Dict[str, str] = {}

    # ------------------------------------------------------------------ providers
    def _wikipedia(self, topic: str, sm: SourceManager) -> int:
        api = "https://en.wikipedia.org/w/api.php"
        titles: List[str] = []
        for q in [" ".join(keywords(topic))] + related_terms(topic)[:1]:
            r = self.http.get(api, params={"action": "query", "list": "search", "srsearch": q, "srlimit": 3,
                                           "format": "json"}, timeout=self.timeout)
            r.raise_for_status()
            for h in r.json().get("query", {}).get("search", []):
                if "disambiguation" not in h["title"].lower() and h["title"] not in titles:
                    titles.append(h["title"])
        added = 0
        for title in titles[: self.n]:
            r2 = self.http.get(api, params={"action": "query", "prop": "extracts|info|revisions", "explaintext": 1,
                                            "exsectionformat": "plain", "titles": title, "inprop": "url",
                                            "rvprop": "timestamp", "format": "json", "redirects": 1},
                               timeout=self.timeout)
            r2.raise_for_status()
            for page in r2.json().get("query", {}).get("pages", {}).values():
                text = (page.get("extract") or "")[:15000]
                if not text or relevance(text, topic) < 3:
                    continue
                ts = (page.get("revisions") or [{}])[0].get("timestamp", "")[:10] or None
                sm.add(title=f"{page.get('title')} — Wikipedia", url=page.get("fullurl"), provider="wikipedia",
                       publisher="Wikipedia", published=ts, text=text)
                added += 1
        return added

    def _medlineplus(self, topic: str, sm: SourceManager) -> int:
        kws = keywords(topic)
        added = 0
        for term in [" ".join(kws)] + related_terms(topic):
            r = self.http.get("https://wsearch.nlm.nih.gov/ws/query",
                              params={"db": "healthTopics", "term": term, "retmax": self.n}, timeout=self.timeout)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            for doc in root.iter("document"):
                fields: Dict[str, str] = {}
                for c in doc.findall("content"):
                    fields.setdefault(c.get("name", ""), _strip_html("".join(c.itertext())))
                url = doc.get("url", "")
                body = fields.get("FullSummary", "") or fields.get("snippet", "")
                if not url or relevance(fields.get("title", "") + " " + body, topic) < 2:
                    continue
                sm.add(title=f"{fields.get('title', 'MedlinePlus')} — MedlinePlus", url=url, provider="medlineplus",
                       publisher="U.S. National Library of Medicine (MedlinePlus)",
                       text=fields.get("FullSummary", "") or fields.get("snippet", ""),
                       snippet=fields.get("snippet", ""))
                added += 1
            if added >= self.n:
                break
        return added

    def _pubmed(self, topic: str, sm: SourceManager) -> int:
        kws = keywords(topic)
        main = " AND ".join(f"{k}*[ti]" if len(k) > 4 else f"{k}[ti]" for k in kws)
        rel = related_terms(topic)
        term = f"({main}) AND review[pt]" + (f" AND ({rel[0]}[tiab])" if rel else "")
        base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        r = self.http.get(base + "esearch.fcgi", params={"db": "pubmed", "term": term, "retmax": self.n,
                                                         "retmode": "json", "sort": "relevance"},
                          timeout=self.timeout)
        r.raise_for_status()
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return 0
        r2 = self.http.get(base + "efetch.fcgi", params={"db": "pubmed", "id": ",".join(ids), "retmode": "xml"},
                           timeout=self.timeout)
        r2.raise_for_status()
        root = ET.fromstring(r2.content)
        added = 0
        for art in root.iter("PubmedArticle"):
            pmid = art.findtext(".//PMID")
            title = _strip_html("".join(art.find(".//ArticleTitle").itertext())) if art.find(".//ArticleTitle") is not None else ""
            abstract = " ".join(_strip_html("".join(a.itertext())) for a in art.findall(".//AbstractText"))
            journal = art.findtext(".//Journal/Title") or ""
            y = art.findtext(".//JournalIssue/PubDate/Year") or art.findtext(".//JournalIssue/PubDate/MedlineDate") or ""
            m = art.findtext(".//JournalIssue/PubDate/Month") or ""
            published = f"{y} {m}".strip() or None
            if not pmid or not abstract or relevance(title + " " + abstract, topic) < 2:
                continue
            sm.add(title=title, url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", provider="pubmed",
                   publisher=journal, published=published, text=abstract)
            added += 1
        return added

    def _tavily(self, topic: str, sm: SourceManager) -> int:
        key = self.s.research_api_key
        if not key:
            raise ResearchError("skipped: RESEARCH_API_KEY not set")
        r = self.http.post("https://api.tavily.com/search", timeout=self.timeout, json={
            "api_key": key, "query": topic, "max_results": self.n, "search_depth": "advanced",
            "include_domains": self.s.research.authoritative_domains})
        r.raise_for_status()
        added = 0
        for res in r.json().get("results", []):
            sm.add(title=res.get("title", ""), url=res.get("url", ""), provider="tavily",
                   published=res.get("published_date"), text=res.get("content", ""))
            added += 1
        return added

    # ------------------------------------------------------------------ main
    def research(self, topic: str, niche: str) -> ResearchPack:
        sm = SourceManager(self.s.research.authoritative_domains)
        providers: Dict[str, Callable[[str, SourceManager], int]] = {
            "wikipedia": self._wikipedia, "medlineplus": self._medlineplus, "pubmed": self._pubmed,
            "tavily": self._tavily}
        status: Dict[str, str] = {}
        for name in self.s.research.providers:
            fn = providers.get(name)
            if fn is None:
                status[name] = "error: unknown provider"
                continue
            try:
                n = fn(topic, sm)
                status[name] = f"ok ({n} sources)"
                log.info("research provider %s: %d sources", name, n)
            except ResearchError as exc:
                status[name] = str(exc)
                log.info("research provider %s: %s", name, exc)
            except Exception as exc:  # network / parse errors are recorded, never hidden
                status[name] = f"error: {type(exc).__name__}: {str(exc)[:200]}"
                log.warning("research provider %s failed: %s", name, exc)
        sources = sm.sources
        self.source_texts = dict(sm.texts)
        facts, uncertain = extract_facts(topic, sources, sm.texts)
        ok_count = sum(1 for v in status.values() if v.startswith("ok") and not v.startswith("ok (0"))
        state = "unavailable" if not sources else ("ok" if ok_count >= 2 else "partial")
        notes = []
        if state == "unavailable":
            notes.append("No research provider returned sources. Script generation is blocked unless "
                         "content.allow_unresearched is enabled; no facts were invented.")
        return ResearchPack(topic=topic, niche=niche, status=state, providers=status,
                            queries=[topic, " ".join(keywords(topic))], sources=sources, facts=facts,
                            uncertain_claims=uncertain, notes=notes)
