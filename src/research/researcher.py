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
import time
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
but if so as than then too very much many most more some any all every each make makes made get gets
work works working everything anything something thing things kind happen""".split())
# Hype words in a title ("the weirdest substance") say nothing about the subject; as concepts they pull in folklore
STOPWORDS |= set("""weird weirder weirdest strange stranger strangest amazing amazingly crazy craziest bizarre
incredible mysterious secret secrets surprising shocking unbelievable fascinating cool coolest wild""".split())

# Wikipedia pages about media, organisations, people or colour names are never sources for a science explainer
OFF_TOPIC_DESC = re.compile(
    r"\b(album|song|single|soundtrack|film|movie|band|studio|company|corporation|television|tv series|series|"
    r"sitcom|novel|book|video game|football|soccer|club|team|character|manga|anime|magazine|newspaper|"
    r"record label|musician|singer|rapper|actor|actress|episode|musical|play by|brand|colou?r|crayon|"
    r"disambiguation|surname|given name|politician|footballer|businessperson|preschool)\b", re.I)
# Index pages collect loosely related entries ("List of discredited substances"); they explain nothing
INDEX_TITLE = re.compile(r"^(lists? of|glossary of|index of|outline of|timeline of)\b", re.I)
# Consumer-health and biomedical indexes only answer body and mind topics; for physics or chemistry they drift
# to whatever disease page mentions a keyword ("water" -> "Lead Poisoning")
HEALTH_PROVIDERS = {"medlineplus", "pubmed"}


# Short acronyms would be dropped by the length filter (and match inside other words), so spell them out
ACRONYMS = {"ai": "artificial intelligence", "ml": "machine learning", "llm": "large language model",
            "llms": "large language models", "iq": "intelligence quotient", "uv": "ultraviolet",
            "co2": "carbon dioxide", "adhd": "attention deficit hyperactivity disorder"}
# Everyday phrasings of one concept: "time feels faster" is about time perception, not about "time" and "feel"
# (as separate words they match any page that says "older" and "faster": exercise, ageing, sexuality)
# concept -> (how a topic asks about it, how a source names it). A source must name the concept itself:
# its words' stems alone are too loose ("perce" is in "percent").
PHRASE_CONCEPTS = {
    "time perception": (
        re.compile(r"\btime (feels?|seems?|flies|fly|goes|passes|speeds? up|slows? down|drags?)\b|"
                   r"\b(sense|perception) of time\b|\btime perception\b"),
        re.compile(r"\b(time perception|perception of time|sense of time|subjective time|perceived time|"
                   r"perceived duration|time (is perceived|seems to (pass|speed|go)|passes by))")),
}


def _concept_words(topic: str) -> List[List[str]]:
    """One word group per topic concept; an acronym's or a phrase's concept stays together as one group
    (a phrase concept comes first, as the subject)."""
    groups = []
    low = topic.lower()
    for concept, (asked, _) in PHRASE_CONCEPTS.items():
        if asked.search(low):
            groups.append(concept.split())
            low = asked.sub(" ", low)
    for w in re.findall(r"[A-Za-z][A-Za-z0-9\-']*", low):
        if w in ACRONYMS:
            groups.append(ACRONYMS[w].split())
        elif w not in STOPWORDS and len(w) >= 3:
            groups.append([w])
    return groups


def keywords(topic: str) -> List[str]:
    out = [w for g in _concept_words(topic) for w in g]
    return out or [topic.lower()]


# Small related-term map used for query expansion when no LLM is available.
RELATED = {
    "dream": ["REM sleep", "sleep"], "nightmare": ["sleep", "REM sleep"], "sleep": ["sleep"],
    "memory": ["memory consolidation", "brain"], "memories": ["memory", "brain"],
    "heart": ["cardiac cycle", "circulatory system", "heart"], "blood": ["circulatory system", "blood"],
    "pulse": ["heart rate", "pulse"], "lung": ["respiratory system", "lung"], "breath": ["breathing"],
    "sky": ["diffuse sky radiation", "Rayleigh scattering"], "sunset": ["sunset", "Rayleigh scattering"],
    "rainbow": ["rainbow", "dispersion (optics)"], "light": ["light", "visible spectrum"],
    "water": ["properties of water", "hydrogen bond"], "ice": ["ice", "properties of water"],
    "black": ["black hole"], "magnet": ["magnetism"], "volcano": ["volcano"], "thunder": ["thunder", "lightning"],
    "overthink": ["rumination (psychology)", "worry"], "worry": ["worry", "anxiety"], "anxiety": ["anxiety"],
    "decision": ["decision-making", "choice overload"], "procrastinat": ["procrastination"],
    "motivation": ["motivation"], "fear": ["fear", "amygdala"], "stress": ["psychological stress"],
    "habit": ["habit formation", "behavior"], "habits": ["habit formation", "behavior"],
    "emotion": ["emotion", "brain"], "emotions": ["emotion", "brain"], "yawn": ["yawning"],
    "hiccup": ["hiccups"], "hiccups": ["hiccups"], "goosebumps": ["goose bumps"],
    "artificial": ["large language model", "artificial neural network", "artificial intelligence"],
    "machine": ["machine learning", "artificial neural network"], "neural": ["artificial neural network"],
    "chatbot": ["chatbot", "large language model"], "robot": ["robotics"],
    "think": ["thought", "reasoning"], "thought": ["thought", "reasoning"],
    "song": ["earworm", "music psychology"], "earworm": ["earworm"], "music": ["music psychology"],
}


def related_terms(topic: str) -> List[str]:
    out: List[str] = [c for c, (asked, _) in PHRASE_CONCEPTS.items() if asked.search(topic.lower())]
    for k in keywords(topic):
        for key, vals in RELATED.items():
            if k.startswith(key):
                out += [v for v in vals if v not in out]
    return out


def expanded_topic(topic: str) -> str:
    """Topic plus its concept expansions (parentheticals dropped), for relevance and fact extraction."""
    return " ".join([topic] + [re.sub(r"\s*\([^)]*\)", "", t) for t in related_terms(topic)])


def _stem(word: str) -> str:
    """Five-letter prefix of the singular, so "songs" also matches a page that only says "song"."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word[:5]


def relevance(text: str, topic: str) -> int:
    stems = [_stem(k) for k in keywords(topic)]
    low = (text or "").lower()
    return sum(low.count(st) for st in stems)


def _mentions(low: str, group: List[str]) -> bool:
    """A concept is mentioned when its own words (all of an acronym's words, e.g. "artificial intelligence")
    or one of its expansions appear. A phrase concept needs the phrase itself."""
    if " ".join(group) in PHRASE_CONCEPTS:
        return bool(PHRASE_CONCEPTS[" ".join(group)][1].search(low))
    alts = [" ".join(group)] + [t for key, vals in RELATED.items() if group[0].startswith(key) for t in vals]
    phrases = [re.sub(r"\s*\([^)]*\)", "", a).lower() for a in alts]
    return any(all(_stem(w) in low for w in p.split()) for p in phrases)


def concept_coverage(text: str, topic: str) -> int:
    """How many of the topic's concepts the text mentions."""
    low = (text or "").lower()
    return sum(1 for group in _concept_words(topic) if _mentions(low, group))


def mentions_subject(text: str, topic: str) -> bool:
    """Whether the text mentions the topic's subject (its first concept: "water" in "why water is the weirdest
    substance on earth"). Applied to a page's lead, it drops pages that only share side words: "Star jelly"
    is a substance found on Earth, but its lead never mentions water."""
    groups = _concept_words(topic)
    return not groups or _mentions((text or "").lower(), groups[0])


def on_topic(text: str, topic: str) -> bool:
    """A source must cover the topic, not just one word of it: two concepts when the topic has two or more
    ("how does AI think" needs AI *and* thinking, so pages about human thought or nursing are dropped).
    A phrase-concept subject is required: "time feel faster as you get older" is not covered by "older" and
    "faster" alone (pages on exercise or ageing)."""
    groups = _concept_words(topic)
    if groups and " ".join(groups[0]) in PHRASE_CONCEPTS and not mentions_subject(text, topic):
        return False
    return concept_coverage(text, topic) >= min(2, len(groups))


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
    def _get_json(self, url: str, params: Dict) -> Dict:
        """GET JSON politely; one retry after a short pause (Wikipedia rate-limits bursts)."""
        for attempt in range(4):
            r = self.http.get(url, params=params, timeout=self.timeout)
            if r.status_code == 429 and attempt < 3:
                wait = float(r.headers.get("Retry-After") or 0) or 2.0 * (attempt + 1)
                log.info("rate limited by %s; retrying in %.0f s", url.split("/")[2], min(wait, 20))
                time.sleep(min(wait, 20))
                continue
            r.raise_for_status()
            try:
                return r.json()
            except ValueError:
                if attempt >= 3:
                    raise
                time.sleep(1.5)
        return {}

    def _wikipedia(self, topic: str, sm: SourceManager) -> int:
        """Search with the natural question, the keywords and concept expansions; drop media/organisation pages.
        A page that fails the relevance gate frees its slot for the next question/keyword hit (not for broader
        expansion hits, which drift: "rumination" finds "Ruminant"). The top page of each concept expansion is
        always fetched too, so a vague question ("how does AI think") still gets the core article."""
        api = "https://en.wikipedia.org/w/api.php"
        titles: List[str] = []
        rejected: List[str] = []
        concept_pages: List[str] = []   # top page per concept expansion, fetched even when the slots are full
        direct: set = set()               # hits of the question/keyword searches, which may refill rejected slots
        expansions = related_terms(topic)[:2]
        queries = [topic.rstrip("?"), " ".join(keywords(topic))] + expansions
        for q in dict.fromkeys(queries):
            hits = self._get_json(api, {"action": "query", "list": "search", "srsearch": q, "srlimit": 4,
                                        "format": "json"}).get("query", {}).get("search", [])
            if q in expansions and hits:
                concept_pages.append(hits[0]["title"])
            names = [h["title"] for h in hits if h["title"] not in titles]
            if not names:
                continue
            pages = self._get_json(api, {"action": "query", "prop": "description", "titles": "|".join(names),
                                         "format": "json", "redirects": 1}).get("query", {}).get("pages", {})
            desc = {pg.get("title"): pg.get("description", "") for pg in pages.values()}
            for name in names:
                d = desc.get(name, "")
                if OFF_TOPIC_DESC.search(d) or INDEX_TITLE.search(name) or "disambiguation" in name.lower() \
                        or "same term" in d.lower():
                    rejected.append(f"{name} ({d})")
                    continue
                titles.append(name)
                if q not in expansions:
                    direct.add(name)
            time.sleep(0.2)
        if rejected:
            log.info("wikipedia: skipped off-topic pages: %s", "; ".join(rejected[:8]))
        added = 0
        for i, title in enumerate(titles):
            if not (i < self.n or title in concept_pages or (title in direct and added < self.n)):
                continue
            data = self._get_json(api, {"action": "query", "prop": "extracts|info|revisions", "explaintext": 1,
                                        "exsectionformat": "plain", "titles": title, "inprop": "url",
                                        "rvprop": "timestamp", "format": "json", "redirects": 1})
            time.sleep(0.3)
            for page in data.get("query", {}).get("pages", {}).values():
                # the core concept article explains the "why" in later sections, so keep more of it
                text = (page.get("extract") or "")[:45000 if title in concept_pages else 15000]
                if not text or relevance(text, expanded_topic(topic)) < 3 or not on_topic(text, topic):
                    continue
                if title not in concept_pages and not mentions_subject(text[:1000], topic):
                    log.info("wikipedia: skipped %s (its lead never mentions the subject)", title)
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
                head = fields.get("title", "") + " " + body
                if not url or relevance(head, topic) < 2 or not on_topic(head, topic):
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
            if not pmid or not abstract or relevance(title + " " + abstract, topic) < 2 \
                    or not on_topic(title + " " + abstract, topic):
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
            if name in HEALTH_PROVIDERS and niche == "science":
                status[name] = "skipped: health index, not used for science topics"
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
        facts, uncertain = extract_facts(expanded_topic(topic), sources, sm.texts)
        ok_count = sum(1 for v in status.values() if v.startswith("ok") and not v.startswith("ok (0"))
        if niche == "science":   # the health providers are deliberately skipped, so one good source tier is enough
            ok_count += 1
        state = "unavailable" if not sources else ("ok" if ok_count >= 2 else "partial")
        notes = []
        if state == "unavailable":
            notes.append("No research provider returned sources. Script generation is blocked unless "
                         "content.allow_unresearched is enabled; no facts were invented.")
        return ResearchPack(topic=topic, niche=niche, status=state, providers=status,
                            queries=[topic, " ".join(keywords(topic))], sources=sources, facts=facts,
                            uncertain_claims=uncertain, notes=notes)
