"""Text normalisation helpers (Vietnamese-aware)."""
from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def normalize_text(text: str) -> str:
    """NFC-normalise, drop control chars, collapse blank runs."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fold(text: str) -> str:
    """Lowercase and strip diacritics (đ -> d) so searches work with or without accents."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d").replace("Đ", "d"))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", text)


def count_tokens(text: str) -> int:
    """Cheap token estimate (words + punctuation). Good enough for chunk sizing."""
    return len(_TOKEN_RE.findall(text))


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def fts_query(query: str, drop: set[str] | None = None) -> str:
    """Safe FTS5 OR query from user text: folded single terms, plus adjacent two-word phrases
    (Vietnamese compounds) and whole code-like tokens (e.g. HD-2024-0173) as exact phrases."""
    drop = drop or set()
    terms = [t for t in _WORD_RE.findall(fold(query)) if t]
    seen: list[str] = []
    for t in terms:
        if t not in seen:
            seen.append(t)
    parts = [f'"{t}"' for t in seen[:40] if t not in drop]
    for a, b in zip(terms, terms[1:]):
        if not (a in drop and b in drop):
            parts.append(f'"{a} {b}"')
    for raw in query.split():
        sub = _WORD_RE.findall(fold(raw))
        if len(sub) > 1 and any(ch.isdigit() for ch in raw) and any(not ch.isalnum() for ch in raw.strip(".,;:")):
            parts.append('"' + " ".join(sub) + '"')
    return " OR ".join(dict.fromkeys(parts[:80]))
