"""Chunking: heading/paragraph/sentence aware, ~350 tokens with ~60 token overlap."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .extract import Segment
from .textutil import count_tokens

_SENT_RE = re.compile(r"(?<=[.!?;])\s+(?=\S)")


@dataclass
class Chunk:
    chunk_index: int
    text: str
    page_number: int | None
    section_heading: str | None
    text_hash: str
    source: str = "text"
    ocr_confidence: float | None = None
    hidden: bool = False


def _split_long(text: str, limit: int) -> list[str]:
    """Split an oversized paragraph by sentence, then by words."""
    parts: list[str] = []
    cur: list[str] = []
    cur_n = 0
    for sent in _SENT_RE.split(text):
        n = count_tokens(sent)
        if n > limit:
            if cur:
                parts.append(" ".join(cur))
                cur, cur_n = [], 0
            toks = sent.split()
            step = max(limit // 2, 1)
            for i in range(0, len(toks), step):
                parts.append(" ".join(toks[i:i + step]))
            continue
        if cur_n + n > limit and cur:
            parts.append(" ".join(cur))
            cur, cur_n = [], 0
        cur.append(sent)
        cur_n += n
    if cur:
        parts.append(" ".join(cur))
    return parts


def chunk_segments(segments: list[Segment], target: int = 350, overlap: int = 60,
                   prefix_heading: bool = False) -> list[Chunk]:
    """Greedy packer. Chunks never span PDF pages (keeps page numbers exact).

    A heading is glued to the paragraph after it. `overlap` words from the end of the
    previous chunk are prepended when the next chunk stays on the same page.
    Chunks also never mix sources (text / ocr / notes) or hidden-slide state.
    `prefix_heading` (PPTX) puts the slide title at the top of every chunk for context.
    """
    hard_max = target + 100
    units: list[tuple[str, int | None, str | None, tuple]] = []
    pending_heading: str | None = None
    for seg in segments:
        if seg.is_heading:
            pending_heading = seg.text
            continue
        text = seg.text
        if pending_heading:
            text = f"{pending_heading}\n{text}"
            pending_heading = None
        meta = (seg.source, seg.confidence, seg.hidden)
        pieces = [text] if count_tokens(text) <= target else _split_long(text, target)
        for p in pieces:
            units.append((p, seg.page, seg.heading, meta))
    if pending_heading:
        units.append((pending_heading, None, pending_heading, ("text", None, False)))

    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_n = 0
    cur_page: int | None = None
    cur_heading: str | None = None
    cur_meta: tuple = ("text", None, False)
    tail_words: list[str] = []

    def flush(keep_overlap: bool) -> None:
        nonlocal buf, buf_n, tail_words
        if not buf:
            return
        text = "\n\n".join(buf).strip()
        if text:
            if prefix_heading and cur_heading and not text.startswith(cur_heading):
                text = f"{cur_heading}\n{text}"
            chunks.append(Chunk(len(chunks), text, cur_page, cur_heading,
                                hashlib.sha256(text.encode("utf-8")).hexdigest(),
                                cur_meta[0], cur_meta[1], cur_meta[2]))
        tail_words = text.split()[-overlap:] if keep_overlap and overlap > 0 else []
        buf, buf_n = [], 0

    for text, page, heading, meta in units:
        n = count_tokens(text)
        page_changed = bool(buf) and (page != cur_page or meta != cur_meta)
        if page_changed:
            flush(keep_overlap=False)
        elif buf and (buf_n + n > hard_max or (buf_n >= target and buf_n + n > target)):
            # fill towards `target`, never beyond `hard_max` (target + 100 => 250-450 band)
            flush(keep_overlap=True)
        if not buf:
            cur_page, cur_heading, cur_meta = page, heading, meta
            if tail_words and not page_changed:
                carry = " ".join(tail_words)
                buf.append(carry)
                buf_n += count_tokens(carry)
            tail_words = []
        buf.append(text)
        buf_n += n
    flush(keep_overlap=False)
    return chunks
