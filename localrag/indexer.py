"""Scanner, change detector, reconciler and indexing pipeline (cancellable, progress reporting)."""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import multiprocessing
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .chunker import chunk_segments
from .config import Config
from .db import Database
from .embedder import Embedder
from .extract import Extracted, ExtractionError, Segment, extract
from .textutil import fold

# Statuses whose chunks may appear in search results.
SEARCHABLE = ("indexed", "partial_content", "text_suspect", "needs_ocr", "ocr_pending", "ocr_low_quality")
# Statuses worth retrying on the next scan even when the file did not change.
RETRY = ("pending", "error", "processing", "missing", "locked", "skipped_cloud_placeholder")

_CLOUD_ATTRS = 0x400000 | 0x40000 | 0x1000  # RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE


@dataclass
class Progress:
    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    current: str = ""
    running: bool = False
    cancelled: bool = False
    message: str = ""


def _supported(cfg: Config) -> set[str]:
    return {"." + e.lower().lstrip(".") for e in cfg.get("index", "include_extensions", default=["docx", "pdf", "pptx"])}


def scan_folder(root: Path, supported: set[str] | None = None) -> list[Path]:
    """Find supported files; skip hidden dirs/files and Office lock files (~$...)."""
    supported = supported or {".docx", ".pdf", ".pptx"}
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() in supported and not name.startswith(("~$", ".")):
                found.append(p)
    return sorted(found)


def is_cloud_placeholder(st) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & _CLOUD_ATTRS)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


# ---- parsing in a child process (timeout; a crashing/hanging parser never stops the index) ----
def _extract_worker(path: str, min_chars: int, cfg_data: dict, root: str) -> Extracted:
    return extract(Path(path), min_chars, Config(cfg_data, Path(root)))


class _ParserPool:
    def __init__(self):
        self._pool: cf.ProcessPoolExecutor | None = None

    def _get(self) -> cf.ProcessPoolExecutor:
        if self._pool is None:
            self._pool = cf.ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        return self._pool

    def run(self, cfg: Config, path: Path, min_chars: int, timeout: float) -> Extracted:
        fut = self._get().submit(_extract_worker, str(path), min_chars, cfg.data, str(cfg.root))
        try:
            return fut.result(timeout=timeout)
        except cf.TimeoutError:
            self._kill()
            raise ExtractionError(f"Hết thời gian đọc file ({int(timeout)} giây): {path.name}", "error")
        except cf.process.BrokenProcessPool:
            self._kill()
            raise ExtractionError(f"Trình đọc file bị dừng đột ngột: {path.name}", "corrupt")

    def _kill(self) -> None:
        pool, self._pool = self._pool, None
        if pool is None:
            return
        for p in list(getattr(pool, "_processes", {}).values()):
            try:
                p.kill()
            except Exception:
                pass
        pool.shutdown(wait=False, cancel_futures=True)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True)
            self._pool = None


class Indexer:
    def __init__(self, cfg: Config, db: Database, embedder: Embedder):
        self.cfg, self.db, self.embedder = cfg, db, embedder
        self.progress = Progress()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._parsers = _ParserPool()
        self.on_change: Callable[[], None] | None = None  # e.g. invalidate vector cache
        self.on_ocr_ready: Callable[[], None] | None = None  # start OCR for folders set to "always"

    # ------------------------------------------------------------ control
    def start(self, rebuild: bool = False, verify_hash: bool = False) -> bool:
        """Run indexing in a background thread so the UI never blocks."""
        with self._lock:
            if self.progress.running:
                return False
            self._cancel.clear()
            self.progress = Progress(running=True)
            self._thread = threading.Thread(target=self._run, args=(rebuild, verify_hash), daemon=True)
            self._thread.start()
            return True

    def cancel(self) -> None:
        self._cancel.set()

    def wait(self) -> None:
        if self._thread:
            self._thread.join()

    def close(self) -> None:
        self._parsers.close()

    def _run(self, rebuild: bool, verify_hash: bool) -> None:
        try:
            self.index_all(rebuild=rebuild, verify_hash=verify_hash)
        except Exception as e:  # model/runtime errors must be reported, not swallowed
            self.progress.message = f"Lỗi: {e}"
        finally:
            self.progress.running = False
            if self.on_change:
                self.on_change()

    # ----------------------------------------------------------- pipeline
    def index_all(self, rebuild: bool = False, verify_hash: bool = False) -> Progress:
        self.progress.running = True
        folders = self.db.list_folders()
        c = self.db.conn()
        if rebuild:
            c.execute("DELETE FROM chunks_fts")
            c.execute("DELETE FROM chunks")  # cascades embeddings (OCR pages are kept: they are costly)
            c.execute("UPDATE documents SET status='pending', content_hash=NULL, error_message=NULL")
            c.commit()

        supported = _supported(self.cfg)
        work: list[tuple[int, Path]] = []
        seen_paths: set[str] = set()
        reachable: list[str] = []
        for f in folders:
            root = Path(f["path"])
            if not root.is_dir():  # unplugged USB / network drive: keep the data, just report
                self.progress.message = f"Không truy cập được thư mục (giữ nguyên dữ liệu): {root}"
                continue
            reachable.append(f["path"])
            for p in scan_folder(root, supported):
                seen_paths.add(str(p))
                if self._needs_index(p, verify_hash):
                    work.append((f["id"], p))
        self._reconcile(folders, reachable, seen_paths)

        self.progress.total = len(work)
        self.progress.skipped = len(seen_paths) - len(work)
        for folder_id, path in work:
            if self._cancel.is_set():
                self.progress.cancelled = True
                self.progress.message = "Đã hủy. Có thể chạy lại để tiếp tục."
                break
            self.progress.current = path.name
            self.index_file(folder_id, path)
            self.progress.done += 1
        self._auto_queue_ocr()
        return self.progress

    def _reconcile(self, folders, reachable: list[str], seen_paths: set[str]) -> None:
        """Files gone from a reachable folder become `missing` (hidden from search); they are dropped
        after the grace period unless they come back or reappear under a new name (same hash)."""
        if not self.cfg.get("index", "reconcile_deleted", default=True):
            return
        grace = float(self.cfg.get("index", "reconcile_grace_hours", default=24)) * 3600
        now = time.time()
        c = self.db.conn()
        for r in c.execute("SELECT id, path, status, missing_since FROM documents").fetchall():
            if r["path"] in seen_paths or not any(_is_under(r["path"], fp) for fp in reachable):
                continue
            if r["status"] != "missing":
                c.execute("UPDATE documents SET prev_status=status, status='missing', missing_since=? WHERE id=?",
                          (now, r["id"]))
            elif now - (r["missing_since"] or now) >= grace:
                self.db.delete_document(r["id"])
        c.commit()
        # grace == 0: drop immediately
        if grace <= 0:
            for r in c.execute("SELECT id FROM documents WHERE status='missing'").fetchall():
                self.db.delete_document(r["id"])

    def _auto_queue_ocr(self) -> None:
        c = self.db.conn()
        cur = c.execute("UPDATE documents SET status='ocr_pending' WHERE status='needs_ocr' AND folder_id IN "
                        "(SELECT id FROM folders WHERE ocr_policy='always')")
        c.commit()
        pending = c.execute("SELECT 1 FROM documents WHERE status='ocr_pending' AND folder_id IN "
                            "(SELECT id FROM folders WHERE ocr_policy='always') LIMIT 1").fetchone()
        if (cur.rowcount or pending) and self.on_ocr_ready:
            self.on_ocr_ready()

    def _needs_index(self, path: Path, verify_hash: bool) -> bool:
        st = path.stat()
        row = self.db.conn().execute("SELECT * FROM documents WHERE path=?", (str(path),)).fetchone()
        if row is None or row["status"] in RETRY:
            return True
        if row["size_bytes"] != st.st_size or abs(row["modified_time"] - st.st_mtime) > 1e-3:
            return True
        if verify_hash and row["content_hash"]:
            return file_sha256(path) != row["content_hash"]
        return False

    # -------------------------------------------------------------- one file
    def index_file(self, folder_id: int, path: Path) -> None:
        """Index one file. Any failure is recorded on the document and never raised
        (except a missing model, which would fail every file)."""
        now = time.time()
        try:
            st = path.stat()
        except OSError:
            self.progress.failed += 1
            return
        c = self.db.conn()
        existing = c.execute("SELECT id, content_hash FROM documents WHERE path=?", (str(path),)).fetchone()
        placeholder = bool(self.cfg.get("index", "skip_cloud_placeholders", default=True)) and is_cloud_placeholder(st)
        too_big = st.st_size > float(self.cfg.get("index", "max_file_mb", default=200)) * 1024 * 1024

        # a file renamed/moved on disk keeps its index: same hash as a document that went missing
        if existing is None and not placeholder and not too_big:
            try:
                digest = file_sha256(path)
            except OSError:
                digest = None
            if digest and self._adopt_renamed(folder_id, path, st, digest):
                return

        c.execute(
            """INSERT INTO documents(folder_id, path, file_name, extension, size_bytes, modified_time,
                   status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(path) DO UPDATE SET folder_id=excluded.folder_id, size_bytes=excluded.size_bytes,
                   modified_time=excluded.modified_time, status='processing', error_message=NULL,
                   missing_since=NULL, updated_at=excluded.updated_at""",
            (folder_id, str(path), path.name, path.suffix.lower(), st.st_size, st.st_mtime, "processing", now, now),
        )
        c.commit()
        doc_id = c.execute("SELECT id FROM documents WHERE path=?", (str(path),)).fetchone()["id"]
        if placeholder:
            self._mark(doc_id, "skipped_cloud_placeholder",
                       "File OneDrive/đám mây chưa được tải về máy. Hãy chọn 'Luôn giữ trên thiết bị này' rồi quét lại.")
            return
        if too_big:
            self._mark(doc_id, "too_large", f"File lớn hơn {self.cfg.get('index', 'max_file_mb', default=200)} MB, đã bỏ qua.")
            return
        try:
            content_hash = file_sha256(path)
            old = c.execute("SELECT content_hash, status FROM documents WHERE id=?", (doc_id,)).fetchone()
            if (existing and existing["content_hash"] == content_hash and
                    c.execute("SELECT 1 FROM chunks WHERE document_id=? LIMIT 1", (doc_id,)).fetchone()):
                # touched but identical: restore the real status without re-embedding
                prev = c.execute("SELECT prev_status FROM documents WHERE id=?", (doc_id,)).fetchone()["prev_status"]
                self._mark(doc_id, prev if prev in SEARCHABLE else "indexed", None)
                c.execute("UPDATE documents SET prev_status=NULL WHERE id=?", (doc_id,))
                c.commit()
                return
            if existing and existing["content_hash"] != content_hash:
                c.execute("DELETE FROM ocr_pages WHERE document_id=?", (doc_id,))  # stale OCR of old content
                c.commit()
            self._build(doc_id, path, folder_id, content_hash, st)
        except ExtractionError as e:
            self._mark(doc_id, e.status, str(e))
            self.progress.failed += 1
        except Exception as e:
            # model/runtime failure: record on the file, keep going, and surface the cause
            self._mark(doc_id, "error", f"{type(e).__name__}: {e}")
            self.progress.failed += 1
            self.progress.message = f"Lỗi khi xử lý {path.name}: {e}"
            from .models import ModelError
            if isinstance(e, ModelError):
                raise  # a missing model would fail every file; stop and tell the user how to fix

    def _adopt_renamed(self, folder_id: int, path: Path, st, digest: str) -> bool:
        c = self.db.conn()
        row = c.execute(
            "SELECT id, prev_status FROM documents WHERE content_hash=? AND status='missing' LIMIT 1", (digest,)).fetchone()
        if row is None:
            return False
        c.execute(
            """UPDATE documents SET path=?, file_name=?, extension=?, folder_id=?, size_bytes=?, modified_time=?,
                   status=?, missing_since=NULL, prev_status=NULL, updated_at=? WHERE id=?""",
            (str(path), path.name, path.suffix.lower(), folder_id, st.st_size, st.st_mtime,
             row["prev_status"] if row["prev_status"] in SEARCHABLE else "indexed", time.time(), row["id"]))
        c.commit()
        return True

    def rebuild_document(self, doc_id: int, ocr_queued: bool = False) -> None:
        """Re-extract one document and merge its stored OCR pages (called after OCR progress)."""
        d = self.db.conn().execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if d is None:
            return
        path = Path(d["path"])
        try:
            st = path.stat()
            self._build(doc_id, path, d["folder_id"], d["content_hash"] or file_sha256(path), st, queued=False)
        except Exception as e:
            self._mark(doc_id, "error", f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------- building
    def _folder_policy(self, folder_id) -> str:
        r = self.db.conn().execute("SELECT ocr_policy FROM folders WHERE id=?", (folder_id,)).fetchone()
        return (r["ocr_policy"] if r else "ask") or "ask"

    def _extract(self, path: Path) -> Extracted:
        min_chars = int(self.cfg.get("index", "min_pdf_chars_per_page", default=40))
        max_pages = int(self.cfg.get("index", "max_pages", default=2000))
        if self.cfg.get("index", "parse_isolated", default=True):
            ex = self._parsers.run(self.cfg, path, min_chars, float(self.cfg.get("index", "parse_timeout_seconds", default=120)))
        else:
            ex = extract(path, min_chars, self.cfg)
        if ex.page_count and ex.page_count > max_pages:
            raise ExtractionError(f"Tài liệu có {ex.page_count} trang, vượt giới hạn {max_pages}.", "too_large")
        return ex

    def _build(self, doc_id: int, path: Path, folder_id, content_hash: str, st, queued: bool = True) -> None:
        ex = self._extract(path)
        c = self.db.conn()
        ocr_on = bool(self.cfg.get("ocr", "enabled", default=True)) and self._folder_policy(folder_id) != "never"
        segments = list(ex.segments)
        done_pages: dict[int, tuple[str, float | None]] = {}
        todo: list[int] = []
        if ex.ocr_pages:
            done_pages = {r["page_number"]: (r["text"], r["confidence"]) for r in c.execute(
                "SELECT page_number, text, confidence FROM ocr_pages WHERE document_id=?", (doc_id,))}
            for p in ex.ocr_pages:
                if p in done_pages:
                    text, conf = done_pages[p]
                    for para in [t.strip() for t in text.split("\n\n") if t.strip()]:
                        segments.append(Segment(para, p, source="ocr", confidence=conf))
            segments.sort(key=lambda s: s.page if s.page is not None else 0)  # stable: keeps order within a page
            limit = int(self.cfg.get("ocr", "max_pages_per_document", default=300))
            todo = [p for p in ex.ocr_pages if p not in done_pages]
            over_limit = max(0, len([p for p in todo]) - max(0, limit - len(done_pages)))
        else:
            over_limit = 0

        chunks = chunk_segments(
            segments, int(self.cfg.get("index", "chunk_tokens", default=350)),
            int(self.cfg.get("index", "chunk_overlap_tokens", default=60)), prefix_heading=ex.prefix_heading)
        vectors = self.embedder.encode_passages([ch.text for ch in chunks]) if chunks else np.zeros((0, self.embedder.dim), dtype=np.float32)

        # ---- decide the document status
        warning = ex.warning
        min_conf = float(self.cfg.get("ocr", "min_confidence", default=60))
        low_quality = any(conf is not None and conf < min_conf for _, conf in done_pages.values())
        actionable = todo  # pages OCR could still process
        if actionable and ocr_on:
            status = "ocr_pending" if queued and self._folder_policy(folder_id) == "always" else "needs_ocr"
            if over_limit:
                warning = (warning + " " if warning else "") + (
                    f"{over_limit} trang vượt giới hạn OCR {self.cfg.get('ocr', 'max_pages_per_document', default=300)} trang/tài liệu.")
        elif actionable and not ocr_on:
            status = "text_suspect" if ex.suspect_pages and chunks else ("no_text" if not chunks else ex.status)
            if not chunks:
                warning = "Tài liệu không có text (có thể là bản scan) và OCR đang tắt."
        elif low_quality:
            status = "ocr_low_quality"
            warning = (warning + " " if warning else "") + "Một số trang OCR có độ tin cậy thấp; kết quả có thể sai chữ."
        else:
            status = ex.status
            if ex.suspect_pages and all(p in done_pages for p in ex.suspect_pages):
                status, warning = "indexed", None
            if not chunks:
                status, warning = "no_text", "Tài liệu không có nội dung text."
        self._store(doc_id, chunks, vectors, content_hash, st, status, warning, ex,
                    todo=[p for p in ex.ocr_pages] if ex.ocr_pages else [])

    def _mark(self, doc_id: int, status: str, msg: str | None) -> None:
        c = self.db.conn()
        c.execute("UPDATE documents SET status=?, error_message=?, updated_at=? WHERE id=?",
                  (status, msg, time.time(), doc_id))
        c.commit()

    def _store(self, doc_id: int, chunks, vectors: np.ndarray, content_hash: str, st, status: str,
               warning: str | None, ex: Extracted, todo: list[int]) -> None:
        """Atomic replace of a document's chunks (a crash mid-write rolls back)."""
        c = self.db.conn()
        now = time.time()
        try:
            c.execute("BEGIN")
            self.db.delete_chunks(doc_id)
            for ch, vec in zip(chunks, vectors):
                cur = c.execute(
                    """INSERT INTO chunks(document_id, chunk_index, page_number, section_heading, text,
                           text_hash, source, ocr_confidence, hidden, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (doc_id, ch.chunk_index, ch.page_number, ch.section_heading, ch.text, ch.text_hash,
                     ch.source, ch.ocr_confidence, int(ch.hidden), now),
                )
                cid = cur.lastrowid
                c.execute("INSERT INTO chunks_fts(rowid, folded_text) VALUES (?,?)", (cid, fold(ch.text)))
                c.execute(
                    "INSERT INTO embeddings(chunk_id, vector, model_name, dimensions, created_at) VALUES (?,?,?,?,?)",
                    (cid, vec.astype(np.float32).tobytes(), self.embedder.model_name, len(vec), now),
                )
            c.execute(
                """UPDATE documents SET status=?, error_message=?, warning=?, content_hash=?, size_bytes=?,
                       modified_time=?, page_count=?, ocr_todo=?, missing_since=NULL, prev_status=NULL,
                       updated_at=? WHERE id=?""",
                (status, warning if status in ("no_text",) else None, warning, content_hash, st.st_size,
                 st.st_mtime, ex.page_count, json.dumps(todo) if todo else None, now, doc_id),
            )
            c.commit()
        except Exception:
            c.rollback()
            raise


def _is_under(path: str, folder: str) -> bool:
    try:
        Path(path).relative_to(folder)
        return True
    except ValueError:
        return False
