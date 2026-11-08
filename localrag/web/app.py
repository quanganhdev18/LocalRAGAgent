"""Local desktop UI + API. Bound to loopback only; no CORS."""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..core import Core
from ..search import Filters, make_snippet

STATIC = Path(__file__).resolve().parent / "static"

PROBLEM_STATUSES = ("error", "no_text", "text_suspect", "needs_ocr", "ocr_pending", "ocr_low_quality",
                    "partial_content", "encrypted", "locked", "corrupt", "too_large",
                    "skipped_cloud_placeholder", "missing")
HINTS = {
    "needs_ocr": "Trang scan chưa có text. Bấm 'Bắt đầu OCR' để nhận dạng chữ (chạy nền, có thể tạm dừng).",
    "ocr_pending": "Đang chờ/đang OCR.",
    "ocr_low_quality": "OCR có độ tin cậy thấp: kết quả tìm có thể sai chữ. Thử bản scan rõ hơn.",
    "text_suspect": "PDF lỗi font (ký tự không đọc được). Bật OCR hoặc xuất lại PDF từ file gốc.",
    "partial_content": "Có SmartArt/biểu đồ/ảnh mà chữ bên trong không đọc được. Tìm kiếm có thể thiếu nội dung đó.",
    "encrypted": "File có mật khẩu. Gỡ mật khẩu rồi quét lại.",
    "locked": "File đang bị khóa hoặc không có quyền đọc. Đóng file rồi quét lại.",
    "corrupt": "File hỏng. Thử mở bằng ứng dụng gốc hoặc lưu lại.",
    "too_large": "File quá lớn so với giới hạn trong cấu hình.",
    "skipped_cloud_placeholder": "File OneDrive chưa tải về máy. Chọn 'Luôn giữ trên thiết bị này' rồi quét lại.",
    "no_text": "Không có text và không thể OCR.",
    "missing": "Không còn thấy file trên đĩa; sẽ bị gỡ khỏi index sau thời gian chờ.",
    "error": "Lỗi khi xử lý file; xem chi tiết và thử quét lại.",
}


class FolderBody(BaseModel):
    path: str
    ocr_policy: str = "ask"


class OcrPolicyBody(BaseModel):
    ocr_policy: str


class IndexBody(BaseModel):
    rebuild: bool = False
    verify_hash: bool = False


class OcrStartBody(BaseModel):
    document_ids: list[int] | None = None


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(10, ge=1, le=50)
    extensions: list[str] | None = None
    folder_ids: list[int] | None = None
    modified_after: str | None = None
    modified_before: str | None = None
    group_by_document: bool = False


class OpenBody(BaseModel):
    document_id: int


class FeedbackBody(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    email: str | None = Field(None, max_length=200)
    wants_news: bool = False


class TelemetryBody(BaseModel):
    enabled: bool


def create_local_app(core: Core) -> FastAPI:
    app = FastAPI(title="LocalRAG", docs_url=None, redoc_url=None, openapi_url=None)
    allowed_hosts = set(core.cfg.get("local_ui", "allowed_hosts", default=["127.0.0.1", "localhost"])) | {"[::1]"}
    session_token = secrets.token_urlsafe(24)  # random per-session token, embedded in the served page
    app.state.session_token = session_token

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # DNS-rebinding / CSRF guard for a loopback-only UI
        raw = request.headers.get("host", "")
        host = raw.split("]")[0] + "]" if raw.startswith("[") else raw.rsplit(":", 1)[0]
        if host not in allowed_hosts:
            return JSONResponse({"detail": "Forbidden host"}, status_code=403)
        origin = request.headers.get("origin")
        if origin:
            oh = origin.split("//", 1)[-1]
            oh = oh.split("]")[0] + "]" if oh.startswith("[") else oh.rsplit(":", 1)[0]
            if oh not in allowed_hosts:
                return JSONResponse({"detail": "Forbidden origin"}, status_code=403)
        if request.url.path.startswith("/local/api") and request.headers.get("x-session-token") != session_token:
            return JSONResponse({"detail": "Missing or invalid session token"}, status_code=403)
        return await call_next(request)

    @app.get("/")
    def index():
        html = (STATIC / "index.html").read_text(encoding="utf-8").replace("__SESSION_TOKEN__", session_token)
        from fastapi.responses import HTMLResponse
        return HTMLResponse(html)

    # ------------------------------------------------------------ status
    @app.get("/local/api/status")
    def status():
        return {
            "index": core.db.index_status(),
            "progress": core.indexer.progress.__dict__,
            "ocr": core.ocr.progress.__dict__ | {"estimate": core.ocr.estimate()},
            "model_problems": core.startup_model_check(),
            "folders": [dict(f) | {"doc_count": core.db.conn().execute(
                "SELECT COUNT(*) FROM documents WHERE folder_id=? AND status!='missing'", (f["id"],)).fetchone()[0]}
                for f in core.db.list_folders()],
            "telemetry_enabled": core.telemetry_enabled,
            "feedback_endpoint_configured": bool((core.cfg.get("feedback", "endpoint", default="") or "").strip()),
        }

    # ----------------------------------------------------------- folders
    @app.post("/local/api/folders")
    def add_folder(body: FolderBody):
        p = Path(body.path).expanduser()
        if not p.is_dir():
            raise HTTPException(400, f"Thư mục không tồn tại: {p}")
        if p.name.startswith(".") or p.parent == p:
            raise HTTPException(400, "Không index thư mục ẩn hoặc thư mục gốc của ổ đĩa.")
        if body.ocr_policy not in ("ask", "always", "never"):
            raise HTTPException(400, "ocr_policy phải là ask | always | never")
        return {"id": core.db.add_folder(str(p.resolve()), body.ocr_policy)}

    @app.post("/local/api/folders/{folder_id}/ocr-policy")
    def folder_ocr_policy(folder_id: int, body: OcrPolicyBody):
        if body.ocr_policy not in ("ask", "always", "never"):
            raise HTTPException(400, "ocr_policy phải là ask | always | never")
        c = core.db.conn()
        c.execute("UPDATE folders SET ocr_policy=? WHERE id=?", (body.ocr_policy, folder_id))
        c.commit()
        return {"ok": True}

    @app.delete("/local/api/folders/{folder_id}")
    def del_folder(folder_id: int):
        core.db.remove_folder(folder_id)  # only forgets the index; files untouched
        core.search.vectors.invalidate()
        return {"ok": True}

    @app.post("/local/api/pick-folder")
    def pick_folder():
        try:
            import tkinter
            from tkinter import filedialog
            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(title="Chọn thư mục tài liệu")
            root.destroy()
            return {"path": path or ""}
        except Exception as e:
            raise HTTPException(500, f"Không mở được hộp thoại chọn thư mục: {e}. Hãy nhập đường dẫn thủ công.")

    # ---------------------------------------------------------- indexing
    @app.post("/local/api/index")
    def start_index(body: IndexBody):
        problems = core.startup_model_check()
        if problems:
            raise HTTPException(400, "; ".join(problems))
        return {"started": core.indexer.start(rebuild=body.rebuild, verify_hash=body.verify_hash)}

    @app.post("/local/api/index/cancel")
    def cancel_index():
        core.indexer.cancel()
        return {"ok": True}

    @app.get("/local/api/documents/problems")
    def problems():
        marks = ",".join("?" * len(PROBLEM_STATUSES))
        rows = core.db.conn().execute(
            f"SELECT id, file_name, path, status, error_message, warning, page_count, ocr_todo FROM documents "
            f"WHERE status IN ({marks}) ORDER BY updated_at DESC LIMIT 300", PROBLEM_STATUSES).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["hint"] = HINTS.get(r["status"], "")
            d["detail"] = r["error_message"] or r["warning"] or ""
            d.pop("ocr_todo")
            out.append(d)
        return out

    # --------------------------------------------------------------- OCR
    @app.get("/local/api/ocr")
    def ocr_status():
        return core.ocr.progress.__dict__ | {"estimate": core.ocr.estimate()}

    @app.post("/local/api/ocr/start")
    def ocr_start(body: OcrStartBody):
        """User consent for OCR: queue `needs_ocr` documents (all, or the given ids) and start."""
        queued = core.ocr.approve(body.document_ids)
        started = core.ocr.start()
        msg = core.ocr.progress.message
        if not started and not core.ocr.progress.running and msg:
            raise HTTPException(400, msg)
        return {"queued": queued, "started": started}

    @app.post("/local/api/ocr/pause")
    def ocr_pause():
        core.ocr.pause()
        return {"ok": True}

    @app.post("/local/api/ocr/resume")
    def ocr_resume():
        if core.ocr.progress.running:
            core.ocr.resume()
        else:
            core.ocr.start()
        return {"ok": True}

    @app.post("/local/api/ocr/cancel")
    def ocr_cancel():
        core.ocr.cancel()
        return {"ok": True}

    # ------------------------------------------------------------ search
    @app.post("/local/api/search")
    def search(body: SearchBody):
        try:
            f = Filters(folder_ids=body.folder_ids, extensions=body.extensions,
                        modified_after=Filters.parse_date(body.modified_after),
                        modified_before=Filters.parse_date(body.modified_before, end=True))
        except ValueError:
            raise HTTPException(400, "Ngày không hợp lệ (dùng YYYY-MM-DD).")
        import time
        t0 = time.perf_counter()
        try:
            hits = core.search.search(body.query, f, body.limit, group_by_document=body.group_by_document)
        except Exception as e:
            core.record_usage("error_" + type(e).__name__)
            if type(e).__name__ == "ModelError":
                raise HTTPException(400, str(e))
            raise
        core.record_usage("search", time.perf_counter() - t0)
        return {"results": [{
            "document_id": h.document_id, "file_name": h.file_name, "relative_path": h.relative_path,
            "extension": h.extension, "page_number": h.page_number, "location": h.location_label,
            "section_heading": h.section_heading, "snippet": make_snippet(h.text, body.query, 400),
            "text": h.text, "citation": h.citation(), "source": h.source,
            "ocr_label": "OCR" if h.source == "ocr" else None,
            "low_confidence": h.source == "ocr" and (h.ocr_confidence or 100) < float(core.cfg.get("ocr", "min_confidence", default=60)),
            "from_notes": h.source == "notes", "hidden_slide": h.hidden,
            "score": h.score,
        } for h in hits]}

    @app.post("/local/api/open")
    def open_file(body: OpenBody):
        try:
            core.open_original(body.document_id)
            core.record_usage("open_result")
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        return {"ok": True}

    # ------------------------------------------------------------- setup
    @app.get("/local/api/setup")
    def setup_status():
        from ..setup_assets import ocr_status
        problems = core.startup_model_check()
        return {"models": {"ok": not problems, "problems": problems},
                "ocr": ocr_status(core.cfg), "job": core.jobs.state.__dict__}

    @app.post("/local/api/setup/models")
    def setup_models():
        from ..models import prepare_models
        from ..models import verify_models
        def job(progress):
            prepare_models(core.cfg, ["embedding-multilingual-e5-small"], progress=progress)
            bad = [r for r in verify_models(core.cfg, ["embedding-multilingual-e5-small"], full=True) if not r.ok]
            if bad:
                raise RuntimeError(bad[0].problem)
        return {"started": core.jobs.start("Tải model tìm kiếm", job)}

    @app.post("/local/api/setup/ocr-data")
    def setup_ocr_data():
        from ..setup_assets import download_tessdata
        return {"started": core.jobs.start("Tải dữ liệu OCR (vie, eng)",
                                           lambda progress: download_tessdata(core.cfg, progress))}

    @app.post("/local/api/setup/tesseract-installer")
    def setup_tesseract():
        """Download the pinned installer and open it; the user confirms the Windows prompt themselves."""
        import os
        from ..setup_assets import download_installer
        def job(progress):
            path = download_installer(core.cfg, progress)
            progress("Đã tải xong. Hãy làm theo cửa sổ cài đặt vừa mở (Windows sẽ hỏi quyền quản trị).")
            os.startfile(str(path))  # noqa: S606 - explicit user action, hash-verified file
        return {"started": core.jobs.start("Cài Tesseract", job)}

    @app.post("/local/api/shutdown")
    def shutdown():
        import os, threading
        core.indexer.cancel()
        core.ocr.cancel()
        threading.Timer(0.5, lambda: os._exit(0)).start()
        return {"ok": True}

    # ---------------------------------------------------------- feedback
    @app.post("/local/api/feedback")
    def feedback(body: FeedbackBody):
        return core.submit_feedback(body.message, body.email, body.wants_news)

    @app.post("/local/api/telemetry")
    def telemetry(body: TelemetryBody):
        core.set_telemetry(body.enabled)
        return {"enabled": core.telemetry_enabled}

    return app
