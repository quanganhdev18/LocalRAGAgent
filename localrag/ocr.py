"""OCR for scanned PDF pages: Tesseract (subprocess) + background per-page queue.

Everything runs locally. Results are stored page by page in `ocr_pages`, so shutting the app
down mid-way loses nothing. Page images are temporary files deleted right after recognition.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .config import Config
from .db import Database

if TYPE_CHECKING:
    from .indexer import Indexer


class OcrUnavailable(Exception):
    """Tesseract or its language data is missing. The message says how to fix it."""


# ----------------------------------------------------------------- engine
def find_tesseract(cfg: Config) -> Path | None:
    configured = (cfg.get("ocr", "tesseract_path", default="") or "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured))
    exe = "tesseract.exe" if sys.platform.startswith("win") else "tesseract"
    candidates.append(cfg.root / "runtime" / "tesseract" / exe)
    for c in candidates:
        if c.is_file():
            return c
    found = shutil.which("tesseract")
    if found:
        return Path(found)
    if sys.platform.startswith("win"):  # default install locations (installer run from the UI)
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            if base and (Path(base) / "Tesseract-OCR" / "tesseract.exe").is_file():
                return Path(base) / "Tesseract-OCR" / "tesseract.exe"
    return None


class TesseractEngine:
    """`recognize(image_path) -> (text, mean_confidence)`; raises OcrUnavailable if not usable."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.languages = "+".join(cfg.get("ocr", "languages", default=["vie", "eng"]))
        self.timeout = int(cfg.get("ocr", "timeout_seconds_per_page", default=60))
        self.exe: Path | None = None
        self.tessdata: Path | None = None
        self._checked = False

    def _popen_kwargs(self) -> dict:
        kw: dict = {}
        if sys.platform.startswith("win"):
            flags = subprocess.CREATE_NO_WINDOW
            if self.cfg.get("ocr", "priority", default="below_normal") == "below_normal":
                flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
            kw["creationflags"] = flags
        return kw

    def check(self) -> None:
        """Verify the binary and the language data once; raise OcrUnavailable with a fix hint."""
        if self._checked:
            return
        self.exe = find_tesseract(self.cfg)
        if self.exe is None:
            raise OcrUnavailable(
                "Chưa có Tesseract OCR. Mở ứng dụng → mục \"Thiết lập\" → bấm \"Cài Tesseract\" "
                "(hoặc khai báo ocr.tesseract_path trong config.yaml).")
        # language data: the app's own runtime/tessdata (no admin needed) wins over the install dir
        from .setup_assets import user_tessdata_dir
        wanted = self.languages.split("+")
        own = user_tessdata_dir(self.cfg)
        theirs = self.exe.parent / "tessdata"
        if own.is_dir() and all((own / f"{l}.traineddata").is_file() for l in wanted):
            self.tessdata = own
        else:
            self.tessdata = theirs if theirs.is_dir() else None
        try:
            res = subprocess.run(self._cmd(["--list-langs"]), capture_output=True, text=True, timeout=30,
                                 **self._popen_kwargs())
        except (OSError, subprocess.TimeoutExpired) as e:
            raise OcrUnavailable(f"Không chạy được Tesseract ({self.exe}): {e}") from e
        have = {ln.strip() for ln in (res.stdout + res.stderr).splitlines()}
        missing = [lang for lang in self.languages.split("+") if lang not in have]
        if missing:
            raise OcrUnavailable(
                f"Thiếu dữ liệu ngôn ngữ OCR: {', '.join(missing)}. Mở ứng dụng → \"Thiết lập\" → \"Tải dữ liệu OCR\".")
        self._checked = True

    def _cmd(self, args: list[str]) -> list[str]:
        cmd = [str(self.exe)]
        if self.tessdata:
            cmd += ["--tessdata-dir", str(self.tessdata)]
        return cmd + args

    def recognize(self, image_path: Path) -> tuple[str, float | None]:
        self.check()
        res = subprocess.run(
            self._cmd([str(image_path), "stdout", "-l", self.languages, "--psm", "3",
                       "-c", "preserve_interword_spaces=1", "-c", "tessedit_create_tsv=1"]),
            capture_output=True, timeout=self.timeout, **self._popen_kwargs())
        if res.returncode != 0:
            raise RuntimeError(f"Tesseract lỗi (mã {res.returncode}): {res.stderr.decode('utf-8', 'replace')[:200]}")
        return parse_tsv(res.stdout.decode("utf-8", "replace"))


def parse_tsv(tsv: str) -> tuple[str, float | None]:
    """Rebuild text (lines grouped by block/paragraph/line) and the mean word confidence."""
    lines: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    confs: list[float] = []
    for row in tsv.splitlines()[1:]:
        parts = row.split("\t")
        if len(parts) < 12 or parts[0] != "5":
            continue
        text = parts[11].strip()
        try:
            conf = float(parts[10])
        except ValueError:
            continue
        if not text or conf < 0:
            continue
        key = (parts[2], parts[3], parts[4])
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(text)
        confs.append(conf)
    out: list[str] = []
    prev_par = None
    for key in order:
        par = key[:2]
        if prev_par is not None and par != prev_par:
            out.append("")
        out.append(" ".join(lines[key]))
        prev_par = par
    return "\n".join(out).strip(), (sum(confs) / len(confs) if confs else None)


def render_page(pdf_path: Path, page_number: int, dpi: int, out_png: Path) -> None:
    """Render one PDF page to a lightly preprocessed greyscale PNG (high contrast)."""
    import pypdfium2 as pdfium
    from PIL import ImageOps

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        page = pdf[page_number - 1]
        try:
            img = page.render(scale=dpi / 72).to_pil()
        finally:
            page.close()
    finally:
        pdf.close()
    img = ImageOps.autocontrast(ImageOps.grayscale(img))
    img.save(out_png, dpi=(dpi, dpi))


# ---------------------------------------------------------------- manager
@dataclass
class OcrProgress:
    running: bool = False
    paused: bool = False
    pages_total: int = 0
    pages_done: int = 0
    current: str = ""
    message: str = ""


class OcrManager:
    """Background queue. Consent first: documents sit in `needs_ocr` until `approve()` moves them to
    `ocr_pending`. One worker thread (max_parallel=1 by default); pause / resume / cancel supported."""

    def __init__(self, cfg: Config, db: Database, indexer: "Indexer", engine=None):
        self.cfg, self.db, self.indexer = cfg, db, indexer
        self.engine = engine or TesseractEngine(cfg)
        self.progress = OcrProgress()
        self._cancel = threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ----------------------------------------------------------- planning
    def _todo(self, row) -> list[int]:
        pages = json.loads(row["ocr_todo"] or "[]")
        limit = int(self.cfg.get("ocr", "max_pages_per_document", default=300))
        done = {r["page_number"] for r in self.db.conn().execute(
            "SELECT page_number FROM ocr_pages WHERE document_id=?", (row["id"],))}
        return [p for p in pages[:limit] if p not in done]

    def estimate(self) -> dict:
        """Pages waiting for consent, with an estimated duration (shown before any bulk OCR)."""
        rows = self.db.conn().execute(
            "SELECT * FROM documents WHERE status IN ('needs_ocr','ocr_pending')").fetchall()
        pages = sum(len(self._todo(r)) for r in rows)
        per = float(self.cfg.get("ocr", "seconds_per_page_estimate", default=6))
        return {"documents": len(rows), "pages": pages, "estimated_seconds": int(pages * per),
                "awaiting_consent": sum(1 for r in rows if r["status"] == "needs_ocr")}

    def approve(self, document_ids: list[int] | None = None) -> int:
        """User consent: move `needs_ocr` documents to the queue. Returns how many were queued."""
        c = self.db.conn()
        if document_ids:
            q = ",".join("?" * len(document_ids))
            cur = c.execute(f"UPDATE documents SET status='ocr_pending' WHERE status='needs_ocr' AND id IN ({q})",
                            document_ids)
        else:
            cur = c.execute("UPDATE documents SET status='ocr_pending' WHERE status='needs_ocr'")
        c.commit()
        return cur.rowcount

    # ------------------------------------------------------------ control
    def start(self) -> bool:
        """Start (or resume) the worker over all `ocr_pending` documents."""
        if not self.cfg.get("ocr", "enabled", default=True):
            self.progress.message = "OCR đang tắt trong cấu hình."
            return False
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._resume.set()
                self.progress.paused = False
                return False
            try:
                if hasattr(self.engine, "check"):
                    self.engine.check()
            except OcrUnavailable as e:
                self.progress = OcrProgress(message=str(e))
                return False
            self._cancel.clear()
            self._resume.set()
            self.progress = OcrProgress(running=True)
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return True

    def pause(self) -> None:
        self._resume.clear()
        self.progress.paused = True

    def resume(self) -> None:
        self._resume.set()
        self.progress.paused = False

    def cancel(self) -> None:
        self._cancel.set()
        self._resume.set()

    def wait(self) -> None:
        if self._thread:
            self._thread.join()

    # ------------------------------------------------------------- worker
    def _run(self) -> None:
        try:
            rows = self.db.conn().execute(
                "SELECT * FROM documents WHERE status='ocr_pending' ORDER BY id").fetchall()
            self.progress.pages_total = sum(len(self._todo(r)) for r in rows)
            for row in rows:
                if self._cancel.is_set():
                    break
                self._ocr_document(row)
            if self._cancel.is_set():
                self.progress.message = "Đã hủy OCR. Các trang đã xong được giữ lại."
                self.db.conn().execute("UPDATE documents SET status='needs_ocr' WHERE status='ocr_pending'")
                self.db.conn().commit()
        except Exception as e:  # report, never swallow
            self.progress.message = f"Lỗi OCR: {type(e).__name__}: {e}"
        finally:
            self.progress.running = False
            self.progress.paused = False
            if self.indexer.on_change:
                self.indexer.on_change()

    def _ocr_document(self, row) -> None:
        doc_id, path = row["id"], Path(row["path"])
        dpi = int(self.cfg.get("ocr", "render_dpi", default=250))
        self.progress.current = row["file_name"]
        failed = 0
        for page in self._todo(row):
            self._resume.wait()
            if self._cancel.is_set():
                break
            tmp_dir = tempfile.mkdtemp(prefix="localrag_ocr_")
            png = Path(tmp_dir) / f"p{page}.png"
            try:
                render_page(path, page, dpi, png)
                text, conf = self.engine.recognize(png)
            except OcrUnavailable:
                raise
            except Exception as e:
                failed += 1
                self.progress.message = f"Không OCR được trang {page} của {row['file_name']}: {e}"
                continue
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)  # page images never outlive the OCR call
            c = self.db.conn()
            c.execute("INSERT OR REPLACE INTO ocr_pages(document_id, page_number, text, confidence, created_at) "
                      "VALUES (?,?,?,?,?)", (doc_id, page, text, conf, time.time()))
            c.commit()
            self.progress.pages_done += 1
        # make everything recognised so far searchable (also after pause/cancel)
        self.indexer.rebuild_document(doc_id, ocr_queued=not self._cancel.is_set())
