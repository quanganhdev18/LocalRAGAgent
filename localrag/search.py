"""Hybrid retrieval: BM25 (SQLite FTS5) + semantic (cosine over in-memory matrix)."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from .config import Config
from .db import Database
from .embedder import Embedder
from .indexer import SEARCHABLE
from .textutil import fold, fts_query, words


@dataclass
class Filters:
    folder_ids: list[int] | None = None
    extensions: list[str] | None = None  # e.g. ["pdf"]
    modified_after: float | None = None
    modified_before: float | None = None

    @staticmethod
    def parse_date(s: str | None, end: bool = False) -> float | None:
        if not s:
            return None
        d = datetime.fromisoformat(s)
        if end and len(s) <= 10:
            d = d.replace(hour=23, minute=59, second=59)
        return d.timestamp()


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    file_name: str
    path: str  # absolute path: local use only
    relative_path: str
    page_number: int | None
    section_heading: str | None
    text: str
    score: float
    bm25: float = 0.0
    semantic: float = 0.0
    modified_time: float = 0.0
    extension: str = ""
    source: str = "text"  # 'text' | 'ocr' | 'notes'
    ocr_confidence: float | None = None
    hidden: bool = False
    status: str = "indexed"

    @property
    def location_label(self) -> str:
        if self.page_number is None:
            return ""
        return f"Slide {self.page_number}" if self.extension == ".pptx" else f"Trang {self.page_number}"

    def citation(self) -> str:
        """`tên file, tr. N` (slide: `tên file, slide N`)."""
        if self.page_number is None:
            return self.file_name
        return f"{self.file_name}, " + (f"slide {self.page_number}" if self.extension == ".pptx" else f"tr. {self.page_number}")


class VectorStore:
    """Chunk vectors cached as one float32 matrix (500 docs ~ tens of MB at most)."""

    def __init__(self, db: Database, dim: int):
        self.db, self.dim = db, dim
        self._ids = np.zeros(0, dtype=np.int64)
        self._mat = np.zeros((0, dim), dtype=np.float32)
        self._loaded = False
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        with self._lock:
            self._loaded = False

    def _load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            rows = self.db.conn().execute("SELECT chunk_id, vector FROM embeddings").fetchall()
            if rows:
                self._ids = np.fromiter((r["chunk_id"] for r in rows), dtype=np.int64, count=len(rows))
                self._mat = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
            else:
                self._ids = np.zeros(0, dtype=np.int64)
                self._mat = np.zeros((0, self.dim), dtype=np.float32)
            self._loaded = True

    def search(self, qvec: np.ndarray, allowed: set[int] | None, k: int) -> list[tuple[int, float]]:
        self._load()
        if not len(self._ids):
            return []
        sims = self._mat @ qvec  # vectors are L2-normalised -> cosine
        if allowed is not None:
            mask = np.fromiter((i in allowed for i in self._ids), dtype=bool, count=len(self._ids))
            sims = np.where(mask, sims, -np.inf)
        k = min(k, len(sims))
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top])]
        return [(int(self._ids[i]), float(sims[i])) for i in top if np.isfinite(sims[i])]


def _minmax(d: dict[int, float]) -> dict[int, float]:
    if not d:
        return {}
    lo, hi = min(d.values()), max(d.values())
    if hi - lo < 1e-9:
        return {k: 1.0 for k in d}
    return {k: (v - lo) / (hi - lo) for k, v in d.items()}


class SearchEngine:
    def __init__(self, cfg: Config, db: Database, embedder: Embedder):
        self.cfg, self.db, self.embedder = cfg, db, embedder
        self.vectors = VectorStore(db, int(cfg.get("index", "vector_dimensions", default=384)))

    def _allowed_chunk_ids(self, f: Filters | None) -> set[int] | None:
        """Filters (and the searchable-status rule) are applied BEFORE top-k, not after."""
        marks = ",".join("?" * len(SEARCHABLE))
        clauses, args = [f"d.status IN ({marks})"], list(SEARCHABLE)
        if f is not None:
            if f.folder_ids:
                clauses.append(f"d.folder_id IN ({','.join('?' * len(f.folder_ids))})")
                args += f.folder_ids
            if f.extensions:
                exts = ["." + e.lower().lstrip(".") for e in f.extensions]
                clauses.append(f"d.extension IN ({','.join('?' * len(exts))})")
                args += exts
            if f.modified_after is not None:
                clauses.append("d.modified_time >= ?"); args.append(f.modified_after)
            if f.modified_before is not None:
                clauses.append("d.modified_time <= ?"); args.append(f.modified_before)
        sql = f"SELECT c.id FROM chunks c JOIN documents d ON d.id=c.document_id WHERE {' AND '.join(clauses)}"
        return {r["id"] for r in self.db.conn().execute(sql, args)}

    def _common_terms(self, query: str) -> set[str]:
        """Terms present in a large share of chunks (e.g. 'và', 'của', 'the') carry no signal and
        only add noise to the fused ranking; they are dropped from the BM25 query."""
        n = self.db.conn().execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if n < 20:
            return set()
        terms = list(dict.fromkeys(words(fold(query))))
        if not terms:
            return set()
        rows = self.db.conn().execute(
            f"SELECT term, doc FROM chunks_vocab WHERE term IN ({','.join('?' * len(terms))})", terms).fetchall()
        return {r["term"] for r in rows if r["doc"] > 0.2 * n}

    def _coverage(self, query: str, ids: list[int]) -> dict[int, float]:
        """Share of the (informative) query terms a BM25 candidate actually contains. A candidate that
        matched on one stray word of a long query counts for less in the fusion than a full match, so
        lexical noise cannot drown a good semantic match (matters most for cross-language queries)."""
        if not ids:
            return {}
        common = self._common_terms(query)
        terms = [t for t in dict.fromkeys(words(fold(query))) if t not in common]
        if not terms:
            return {}
        rows = self.db.conn().execute(
            f"SELECT rowid, folded_text FROM chunks_fts WHERE rowid IN ({','.join('?' * len(ids))})", ids).fetchall()
        out = {}
        for r in rows:
            have = set(words(r["folded_text"]))
            out[r["rowid"]] = sum(1 for t in terms if t in have) / len(terms)
        return out

    def _bm25(self, query: str, allowed: set[int] | None, k: int) -> dict[int, float]:
        q = fts_query(query, self._common_terms(query))
        if not q:
            return {}
        rows = self.db.conn().execute(
            "SELECT rowid, bm25(chunks_fts) AS s FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY s LIMIT ?", (q, -1 if allowed is not None else k)).fetchall()  # filters first, then top-k
        out: dict[int, float] = {}
        for r in rows:
            if allowed is not None and r["rowid"] not in allowed:
                continue
            out[r["rowid"]] = -float(r["s"])  # FTS5 bm25 is lower=better (negative)
            if len(out) >= k:
                break
        return out

    def search(self, query: str, filters: Filters | None = None, limit: int = 10,
               mode: str | None = None, group_by_document: bool = False) -> list[Hit]:
        """Hybrid search. `mode` may be 'hybrid' | 'bm25' | 'semantic' (semantic needs the model)."""
        query = query.strip()
        if not query:
            return []
        mode = mode or self.cfg.get("retrieval", "mode", default="hybrid")
        k = int(self.cfg.get("retrieval", "top_k_candidates", default=30))
        allowed = self._allowed_chunk_ids(filters)
        if allowed is not None and not allowed:
            return []

        bm = self._bm25(query, allowed, k) if mode in ("hybrid", "bm25") else {}
        sem: dict[int, float] = {}
        if mode in ("hybrid", "semantic"):
            qvec = self.embedder.encode_query(query)
            sem = dict(self.vectors.search(qvec, allowed, k))

        # Reciprocal Rank Fusion over the two ranked lists
        rrf_k = int(self.cfg.get("retrieval", "rrf_k", default=60))
        bm_rank = {i: r for r, i in enumerate(sorted(bm, key=bm.get, reverse=True), 1)}
        sem_rank = {i: r for r, i in enumerate(sorted(sem, key=sem.get, reverse=True), 1)}
        cov = self._coverage(query, list(bm))
        scored = {i: (cov.get(i, 1.0) / (rrf_k + bm_rank[i]) if i in bm_rank else 0.0) +
                     (1 / (rrf_k + sem_rank[i]) if i in sem_rank else 0.0) for i in set(bm) | set(sem)}
        ranked = sorted(scored, key=scored.get, reverse=True)
        hits = self._hydrate(ranked, scored, bm, sem)
        hits = dedupe(hits, 0.85)
        per_doc = int(self.cfg.get("retrieval", "max_chunks_per_document", default=3))
        if group_by_document:
            per_doc = 1
        counts: dict[int, int] = {}
        out: list[Hit] = []
        for h in hits:
            if counts.get(h.document_id, 0) >= per_doc:
                continue
            counts[h.document_id] = counts.get(h.document_id, 0) + 1
            out.append(h)
            if len(out) >= limit:
                break
        return out

    def _hydrate(self, ids: list[int], scored, bm, sem) -> list[Hit]:
        bm_n, sem_n = _minmax(bm), _minmax(sem)
        if not ids:
            return []
        c = self.db.conn()
        q = (f"SELECT c.id cid, c.document_id, c.page_number, c.section_heading, c.text, "
             f"d.file_name, d.path, d.modified_time, d.extension, d.folder_id, d.status, c.source, c.ocr_confidence, c.hidden, f.path folder_path "
             f"FROM chunks c JOIN documents d ON d.id=c.document_id "
             f"LEFT JOIN folders f ON f.id=d.folder_id WHERE c.id IN ({','.join('?' * len(ids))})")
        rows = {r["cid"]: r for r in c.execute(q, ids)}
        hits = []
        for i in ids:
            r = rows.get(i)
            if r is None:
                continue
            try:
                rel = str(Path(r["path"]).relative_to(r["folder_path"])) if r["folder_path"] else r["file_name"]
            except ValueError:
                rel = r["file_name"]
            hits.append(Hit(
                chunk_id=i, document_id=r["document_id"], file_name=r["file_name"], path=r["path"],
                relative_path=rel.replace("\\", "/"), page_number=r["page_number"],
                section_heading=r["section_heading"], text=r["text"], score=round(scored[i], 4),
                bm25=round(bm_n.get(i, 0.0), 4), semantic=round(sem_n.get(i, 0.0), 4),
                modified_time=r["modified_time"], extension=r["extension"], source=r["source"],
                ocr_confidence=r["ocr_confidence"], hidden=bool(r["hidden"]), status=r["status"],
            ))
        return hits


def make_snippet(text: str, query: str, width: int = 280) -> str:
    """Return a window of `text` around the first query term (diacritic-insensitive)."""
    folded = fold(text)
    pos = -1
    for w in words(fold(query)):
        p = folded.find(w)
        if p != -1 and (pos == -1 or p < pos):
            pos = p
    if pos == -1:
        pos = 0
    start = max(0, pos - width // 4)
    snippet = text[start:start + width].strip()
    return ("… " if start > 0 else "") + snippet + (" …" if start + width < len(text) else "")


def dedupe(hits: list[Hit], threshold: float = 0.85) -> list[Hit]:
    """Drop duplicate / near-duplicate chunks (word-set Jaccard) keeping the best-ranked."""
    kept: list[Hit] = []
    sets: list[set[str]] = []
    for h in hits:
        s = set(words(fold(h.text)))
        if any(len(s & o) / max(len(s | o), 1) >= threshold for o in sets):
            continue
        kept.append(h)
        sets.append(s)
    return kept
