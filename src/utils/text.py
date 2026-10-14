"""Small text helpers shared across modules."""
from __future__ import annotations

import re
import unicodedata
from typing import List

_SENT_RE = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")
_ABBREV = ("Dr.", "Mr.", "Mrs.", "Ms.", "e.g.", "i.e.", "vs.", "U.S.", "U.K.", "St.", "approx.")


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text[:max_len].rstrip("_") or "episode"


def split_sentences(text: str) -> List[str]:
    """Split narration into sentences (keeps punctuation)."""
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    protected = text
    for i, ab in enumerate(_ABBREV):
        protected = protected.replace(ab, f"\x00{i}\x00")
    parts = _SENT_RE.split(protected)
    out = []
    for p in parts:
        for i, ab in enumerate(_ABBREV):
            p = p.replace(f"\x00{i}\x00", ab)
        p = p.strip()
        if p:
            out.append(p)
    return out


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def tokenize_words(text: str) -> List[str]:
    """Whitespace tokens, punctuation attached (used for captions)."""
    return [w for w in text.split() if w.strip()]


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen " \
        "sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def int_to_words(n: int) -> str:
    if n < 0:
        return "minus " + int_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else "-" + _ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + " hundred" + ("" if rest == 0 else " and " + int_to_words(rest))
    for div, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= div:
            rest = n % div
            return int_to_words(n // div) + f" {name}" + ("" if rest == 0 else
                                                          (" and " if rest < 100 else " ") + int_to_words(rest))
    return str(n)


def year_to_words(n: int) -> str:
    if 1100 <= n <= 1999 or 2010 <= n <= 2099:
        hi, lo = divmod(n, 100)
        return int_to_words(hi) + " " + ("hundred" if lo == 0 else ("oh " + _ONES[lo] if lo < 10 else int_to_words(lo)))
    return int_to_words(n)


def spoken_number_token(tok: str) -> str:
    """Rewrite a single whitespace token containing digits into words (keeps punctuation)."""
    m = re.match(r"^([^\d]*?)(\d[\d,]*(?:\.\d+)?)(?:[–-](\d[\d,]*))?(%|s)?([^\d]*)$", tok)
    if not m:
        return tok
    pre, a, b, unit, post = m.groups()
    def conv(x: str) -> str:
        x = x.replace(",", "")
        if "." in x:
            i, d = x.split(".")
            return int_to_words(int(i)) + " point " + " ".join(_ONES[int(c)] for c in d)
        v = int(x)
        return year_to_words(v) if (1100 <= v <= 2099 and len(x) == 4) else int_to_words(v)
    words = conv(a)
    if b:
        words += " to " + conv(b)
    if unit == "%":
        words += " percent"
    elif unit == "s":
        words += "s" if not words.endswith("y") else ""
        if words.endswith("y"):
            words = words[:-1] + "ies"
    return f"{pre}{words}{post}"
