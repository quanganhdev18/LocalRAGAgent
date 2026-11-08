"""Application container shared by the CLI and the local UI."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .config import Config, load_config
from .db import Database
from .embedder import Embedder
from .indexer import Indexer
from .models import verify_models
from .ocr import OcrManager
from .setup_assets import SetupJobs
from .search import SearchEngine


class Core:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or load_config()
        self.db = Database(self.cfg.db_path)
        self.embedder = Embedder(self.cfg)
        self.search = SearchEngine(self.cfg, self.db, self.embedder)
        self.indexer = Indexer(self.cfg, self.db, self.embedder)
        self.indexer.on_change = self.search.vectors.invalidate
        self.ocr = OcrManager(self.cfg, self.db, self.indexer)
        self.indexer.on_ocr_ready = self.ocr.start
        self.jobs = SetupJobs(self.cfg)

    # --- startup checks -------------------------------------------------
    def startup_model_check(self) -> list[str]:
        """Verify embedding model on start (cheap, cached). Returns human-readable problems."""
        if not self.cfg.get("models", "verify_on_start", default=True):
            return []
        res = verify_models(self.cfg, ["embedding-multilingual-e5-small"])
        return [f"{r.id}: {r.problem}. {r.fix}" for r in res if not r.ok]

    # --- feedback / telemetry (F8): nothing leaves the machine unless the user opts in ----
    @property
    def telemetry_enabled(self) -> bool:
        v = self.db.get_setting("telemetry_enabled")
        return v == "1" if v is not None else bool(self.cfg.get("privacy", "telemetry_enabled", default=False))

    def set_telemetry(self, on: bool) -> None:
        self.db.set_setting("telemetry_enabled", "1" if on else "0")

    def record_usage(self, event: str, seconds: float | None = None) -> None:
        """Anonymous counters (searches, opens, error kinds, summed latency) kept LOCALLY, and only
        when the user opted in. Never stores queries, paths or document content. Nothing is sent."""
        if not self.telemetry_enabled:
            return
        import json
        data = json.loads(self.db.get_setting("usage_counters", "{}") or "{}")
        data[event] = data.get(event, 0) + 1
        if seconds is not None:
            data[event + "_seconds"] = round(data.get(event + "_seconds", 0.0) + seconds, 3)
        self.db.set_setting("usage_counters", json.dumps(data))

    def submit_feedback(self, message: str, email: str | None = None, wants_news: bool = False) -> dict:
        """Store feedback locally; send only what the user typed, and only if an endpoint is configured."""
        import time
        message = message.strip()
        if not message:
            raise ValueError("Nội dung góp ý trống.")
        if not self.cfg.get("feedback", "collect_email_optional", default=True):
            email = None
        c = self.db.conn()
        cur = c.execute("INSERT INTO feedback(message,email,wants_news,created_at) VALUES (?,?,?,?)",
                        (message, (email or "").strip() or None, int(wants_news), time.time()))
        c.commit()
        sent = False
        endpoint = (self.cfg.get("feedback", "endpoint", default="") or "").strip()
        if endpoint and self.cfg.get("feedback", "enabled", default=True):
            try:
                import httpx
                payload = {"message": message, "email": (email or "").strip() or None, "wants_news": wants_news}
                sent = httpx.post(endpoint, json=payload, timeout=10).is_success
                if sent:
                    c.execute("UPDATE feedback SET sent=1 WHERE id=?", (cur.lastrowid,))
                    c.commit()
            except Exception:
                sent = False
        return {"id": cur.lastrowid, "sent": sent, "stored_locally": True}

    # --- documents -----------------------------------------------------
    def document(self, doc_id: int):
        return self.db.conn().execute(
            "SELECT d.*, f.path AS folder_path FROM documents d "
            "LEFT JOIN folders f ON f.id=d.folder_id WHERE d.id=?", (doc_id,)).fetchone()

    def resolve_document_path(self, doc_id: int) -> Path | None:
        """Server-side authorisation of a file path: must belong to an indexed folder.
        Never trusts client-supplied paths."""
        d = self.document(doc_id)
        if d is None or not d["folder_path"]:
            return None
        root = Path(d["folder_path"]).resolve()
        p = Path(d["path"]).resolve()
        try:
            p.relative_to(root)
        except ValueError:
            return None  # symlink / traversal escaping the granted folder
        return p if p.is_file() else None

    def open_original(self, doc_id: int) -> None:
        """Open with the OS default application. Only on explicit user action."""
        p = self.resolve_document_path(doc_id)
        if p is None:
            raise FileNotFoundError("Không thể mở file gốc (file đã bị xóa/di chuyển hoặc ngoài thư mục đã cấp quyền).")
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
