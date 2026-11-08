"""Command line: prepare-models, verify-models, package-offline, add-folder, index, ocr, search, serve."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
import time
import zipfile
from pathlib import Path

from .config import PROJECT_ROOT, load_config
from .models import ModelError, load_manifest, prepare_models, verify_models


def _core():
    from .core import Core
    return Core(load_config())


def cmd_prepare(a):
    cfg = load_config()
    prepare_models(cfg, a.ids or None)


def cmd_verify(a):
    cfg = load_config()
    res = verify_models(cfg, a.ids or None, full=True)
    bad = 0
    for r in res:
        print(f"{'OK  ' if r.ok else 'FAIL'} {r.id}" + ("" if r.ok else f"\n     {r.problem}\n     -> {r.fix}"))
        bad += not r.ok
    sys.exit(1 if bad else 0)


def cmd_add_folder(a):
    core = _core()
    p = Path(a.path).expanduser().resolve()
    if not p.is_dir():
        sys.exit(f"Thư mục không tồn tại: {p}")
    print(f"Đã thêm thư mục #{core.db.add_folder(str(p), a.ocr)}: {p}")


def cmd_index(a):
    core = _core()
    problems = core.startup_model_check()
    if problems:
        sys.exit("\n".join(problems))
    core.indexer.start(rebuild=a.rebuild, verify_hash=a.verify_hash)
    try:
        while core.indexer.progress.running:
            p = core.indexer.progress
            print(f"\r{p.done}/{p.total} {p.current[:50]:50}", end="", flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        core.indexer.cancel()
        core.indexer.wait()
    p = core.indexer.progress
    print(f"\nXong: {p.done}/{p.total} file, bỏ qua {p.skipped}, lỗi {p.failed}. {p.message}")
    for r in core.db.conn().execute(
            "SELECT file_name, status, error_message, warning FROM documents WHERE status NOT IN ('indexed')"):
        print(f"  ! {r['file_name']} [{r['status']}]: {r['error_message'] or r['warning'] or ''}")
    est = core.ocr.estimate()
    if est["awaiting_consent"]:
        print(f"{est['pages']} trang cần OCR (~{est['estimated_seconds'] // 60} phút). Chạy: python -m localrag ocr --yes")


def cmd_ocr(a):
    core = _core()
    est = core.ocr.estimate()
    print(f"Cần OCR: {est['pages']} trang / {est['documents']} tài liệu, ước tính ~{est['estimated_seconds'] // 60} phút.")
    if not est["pages"]:
        return
    if not a.yes:
        print("Thêm --yes để đồng ý và bắt đầu OCR.")
        return
    core.ocr.approve()
    if not core.ocr.start():
        sys.exit(core.ocr.progress.message or "Không bắt đầu được OCR.")
    try:
        while core.ocr.progress.running:
            p = core.ocr.progress
            print(f"{p.pages_done}/{p.pages_total} {p.current[:50]:50}", end="", flush=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        core.ocr.cancel()
        core.ocr.wait()
    print(f"
Xong OCR. {core.ocr.progress.message}")


def cmd_search(a):
    from .search import make_snippet
    core = _core()
    hits = core.search.search(a.query, limit=a.limit, mode=a.mode)
    for i, h in enumerate(hits, 1):
        where = f"trang {h.page_number}" if h.page_number else (h.section_heading or "page: unknown")
        print(f"{i}. {h.file_name} ({h.relative_path}) - {where} - điểm {h.score}\n   {make_snippet(h.text, a.query)}\n")
    if not hits:
        print("Không có kết quả.")


def cmd_serve(a):
    import uvicorn
    from .web.app import create_local_app

    core = _core()
    for p in core.startup_model_check():
        print("CẢNH BÁO:", p)
    host = core.cfg.get("local_ui", "bind", default="127.0.0.1")
    port = int(core.cfg.get("local_ui", "port", default=8700))
    if host not in ("127.0.0.1", "::1", "localhost"):
        sys.exit(f"local_ui.bind={host} không phải loopback; từ chối khởi động.")
    print(f"UI cục bộ: http://{host}:{port}")
    uvicorn.run(create_local_app(core), host=host, port=port, log_level="warning")


def cmd_package(a):
    """Build dist/ with app code + manifest (+ models for full-offline). Never includes data/, indexes/ or tokens."""
    cfg = load_config()
    mode = a.mode
    if mode == "full":
        res = verify_models(cfg, full=True)
        bad = [r for r in res if not r.ok]
        if bad:
            sys.exit("Không thể đóng gói full/offline:\n" + "\n".join(f" - {r.id}: {r.problem}" for r in bad))
    out = PROJECT_ROOT / "dist" / f"localrag-{mode}.zip"
    out.parent.mkdir(exist_ok=True)
    skip_dirs = {".venv", ".venv-local", "runtime", "__pycache__", "data", "indexes", "dist", ".git", ".pytest_cache", "_downloads"}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in PROJECT_ROOT.rglob("*"):
            rel = p.relative_to(PROJECT_ROOT)
            if not p.is_file() or set(rel.parts) & skip_dirs or p.suffix == ".pyc" or p.name == ".verified.json":
                continue
            if rel.parts[0] == "models" and rel.name not in ("MANIFEST.json",) and "LICENSES" not in rel.parts:
                if mode == "slim":
                    continue
            if rel.parts[0] == "Specv1.md":
                continue
            z.write(p, rel.as_posix())
        if mode == "slim":
            z.writestr("models/README-SLIM.txt",
                       "Bản slim không chứa model. Chạy: python -m localrag prepare-models rồi verify-models.\n"
                       "Model cần: " + ", ".join(m["id"] for m in load_manifest(cfg)["models"]) + "\n")
    print(f"Đã tạo {out} ({out.stat().st_size / 1e6:.0f} MB)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="localrag", description="Local document search")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("prepare-models", help="Tải model đã pin vào models/ và cập nhật MANIFEST.json")
    s.add_argument("ids", nargs="*"); s.set_defaults(fn=cmd_prepare)
    s = sub.add_parser("verify-models", help="Kiểm tra tồn tại, revision và SHA-256 của model")
    s.add_argument("ids", nargs="*"); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("package-offline", help="Đóng gói full (có model) hoặc slim")
    s.add_argument("--mode", choices=["full", "slim"], default="full"); s.set_defaults(fn=cmd_package)
    s = sub.add_parser("add-folder"); s.add_argument("path"); s.add_argument("--ocr", choices=["ask", "always", "never"], default="ask")
    s.set_defaults(fn=cmd_add_folder)
    s = sub.add_parser("index"); s.add_argument("--rebuild", action="store_true")
    s.add_argument("--verify-hash", action="store_true"); s.set_defaults(fn=cmd_index)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("-n", "--limit", type=int, default=10)
    s.add_argument("--mode", choices=["hybrid", "bm25", "semantic"], default=None); s.set_defaults(fn=cmd_search)
    s = sub.add_parser("ocr", help="Xem số trang cần OCR; --yes để đồng ý và chạy")
    s.add_argument("--yes", action="store_true"); s.set_defaults(fn=cmd_ocr)
    s = sub.add_parser("serve", help="Chạy UI cục bộ"); s.set_defaults(fn=cmd_serve)
    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except ModelError as e:
        sys.exit(f"Lỗi model: {e}")


if __name__ == "__main__":
    main()
