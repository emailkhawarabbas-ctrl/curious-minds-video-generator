"""Source registry: de-duplication, credibility tiers and citation records."""
from __future__ import annotations

import re
from typing import Dict, List, Optional
from urllib.parse import urlparse

from src.content.models import Source

PEER_REVIEWED_HOSTS = ("pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov/pmc", "nature.com", "science.org",
                       "cell.com", "thelancet.com", "nejm.org", "jamanetwork.com", "frontiersin.org")
REFERENCE_HOSTS = ("wikipedia.org", "britannica.com")


def classify_tier(url: str, authoritative_domains: List[str]) -> str:
    host = urlparse(url).netloc.lower()
    full = host + urlparse(url).path.lower()
    if any(full.startswith(h) or host.endswith(h) for h in PEER_REVIEWED_HOSTS):
        return "peer_reviewed"
    if any(host == d or host.endswith("." + d) for d in authoritative_domains):
        return "authoritative"
    if any(host.endswith(h) for h in REFERENCE_HOSTS):
        return "reference"
    return "general"


class SourceManager:
    def __init__(self, authoritative_domains: List[str]):
        self.authoritative = [d.lower() for d in authoritative_domains]
        self._by_url: Dict[str, Source] = {}
        self.texts: Dict[str, str] = {}      # source id -> full text used for fact extraction

    @staticmethod
    def _norm(url: str) -> str:
        return re.sub(r"[#?].*$", "", url.strip()).rstrip("/").lower()

    def add(self, *, title: str, url: str, provider: str, publisher: str = "", published: Optional[str] = None,
            text: str = "", snippet: str = "") -> Source:
        key = self._norm(url)
        if key in self._by_url:
            src = self._by_url[key]
            if text and len(text) > len(self.texts.get(src.id, "")):
                self.texts[src.id] = text
            return src
        sid = f"S{len(self._by_url) + 1}"
        src = Source(id=sid, title=title.strip()[:300] or url, url=url, publisher=publisher, published=published,
                     provider=provider, tier=classify_tier(url, self.authoritative),
                     snippet=(snippet or text)[:400].strip())
        self._by_url[key] = src
        self.texts[sid] = text or snippet
        return src

    @property
    def sources(self) -> List[Source]:
        return list(self._by_url.values())
