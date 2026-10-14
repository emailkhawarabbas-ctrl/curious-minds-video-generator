"""Reusable visual asset library: discovery, indexing, keyword search and licensing.

Assets are SVG files under ``assets/<category>/<asset_id>.svg``. Each file carries its
own metadata (``data-title``, ``data-tags``, ``data-license``) so the library is
self-describing; ``assets/manifest.json`` is a generated index of it
(``python -m src.main assets index``).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from src.animation.svg_loader import SvgAsset, SvgError, load_svg

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = PROJECT_ROOT / "assets"
ASSET_CATEGORIES = ("human_body", "psychology", "science", "objects", "doodles", "characters")
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    category: str
    file: str
    title: str
    tags: tuple
    anchors: tuple
    license: str


class AssetManager:
    def __init__(self, root: Path = ASSET_ROOT):
        self.root = Path(root)
        self._records: Dict[str, AssetRecord] = {}
        self._cache: Dict[str, SvgAsset] = {}
        self._scan()

    # ---------------------------------------------------------------- discovery
    def _scan(self) -> None:
        for cat in ASSET_CATEGORIES:
            d = self.root / cat
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.svg")):
                if f.stem.startswith("_"):
                    continue
                if f.stem in self._records:
                    raise SvgError(f"duplicate asset id {f.stem!r} ({f})")
                try:
                    a = load_svg(f, f.stem)
                except SvgError as exc:
                    log.error("skipping invalid asset %s: %s", f, exc)
                    continue
                self._cache[f.stem] = a
                self._records[f.stem] = AssetRecord(
                    asset_id=f.stem, category=cat, file=str(f.relative_to(self.root)),
                    title=a.title, tags=a.tags, anchors=tuple(sorted(a.anchors)), license=a.license)

    # ---------------------------------------------------------------- queries
    def ids(self, category: Optional[str] = None) -> List[str]:
        return sorted(k for k, r in self._records.items() if category is None or r.category == category)

    def exists(self, asset_id: str) -> bool:
        return asset_id in self._records

    def record(self, asset_id: str) -> AssetRecord:
        return self._records[asset_id]

    def get(self, asset_id: str) -> SvgAsset:
        if asset_id not in self._records:
            raise KeyError(f"unknown asset {asset_id!r}")
        if asset_id not in self._cache:
            self._cache[asset_id] = load_svg(self.root / self._records[asset_id].file, asset_id)
        return self._cache[asset_id]

    def search(self, text: str, limit: int = 5, categories: Optional[Sequence[str]] = None) -> List[str]:
        """Rank assets by keyword overlap with id, title and tags."""
        words = set(_WORD.findall(text.lower()))
        words |= {w[:-1] for w in words if w.endswith("s") and len(w) > 3}
        scored = []
        for aid, r in self._records.items():
            if categories and r.category not in categories:
                continue
            if r.category in ("characters",):
                continue
            id_words = set(_WORD.findall(aid.replace("_", " ")))
            tag_words = set(w for t in r.tags for w in _WORD.findall(t))
            score = 3 * len(words & id_words) + 2 * len(words & tag_words) \
                + len(words & set(_WORD.findall(r.title.lower())))
            if score:
                scored.append((score, aid))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [a for _, a in scored[:limit]]

    def best_match(self, text: str, fallback: str = "lightbulb") -> str:
        hits = self.search(text, limit=1)
        return hits[0] if hits else fallback

    # ---------------------------------------------------------------- manifests
    def manifest(self) -> Dict[str, dict]:
        return {k: {"category": r.category, "file": r.file, "title": r.title, "tags": list(r.tags),
                    "anchors": list(r.anchors), "license": r.license}
                for k, r in sorted(self._records.items())}

    def write_manifest(self, path: Optional[Path] = None) -> Path:
        path = path or self.root / "manifest.json"
        path.write_text(json.dumps(self.manifest(), indent=2) + "\n")
        return path

    def licenses(self, used: Optional[Iterable[str]] = None) -> Dict[str, str]:
        ids = sorted(set(used)) if used is not None else sorted(self._records)
        return {i: self._records[i].license for i in ids if i in self._records}


@lru_cache(maxsize=1)
def get_asset_manager() -> AssetManager:
    return AssetManager()
