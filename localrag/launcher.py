"""Windows-friendly launcher: no terminal needed. Starts the local server and opens the UI in its own window.

Run via LocalRAG.vbs (hidden window) or `pythonw -m localrag.launcher`. If the app is already
running, it just opens the browser to the existing instance. Logs go to data/app.log and never
contain document text or queries.
"""
from __future__ import annotations

import logging
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

from .config import load_config


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _is_ours(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/", timeout=2) as r:
            return b"Kho t\xc3\xa0i li\xe1\xbb\x87u c\xe1\xbb\xa5c b\xe1\xbb\x99" in r.read(4096)
    except Exception:
        return False


def _error_box(msg: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, "Kho tài liệu cục bộ", 0x10)
    except Exception:
        print(msg, file=sys.stderr)


def main() -> None:
    cfg = load_config()
    host = cfg.get("local_ui", "bind", default="127.0.0.1")
    port = int(cfg.get("local_ui", "port", default=8700))
    if host not in ("127.0.0.1", "::1", "localhost"):
        _error_box(f"local_ui.bind={host} không phải loopback; từ chối khởi động.")
        return
    url = f"http://{host}:{port}/"
    if _port_in_use(host, port):
        if _is_ours(host, port):
            webbrowser.open(url)
        else:
            _error_box(f"Cổng {port} đang được chương trình khác dùng. Đổi local_ui.port trong config.yaml.")
        return

    log_path = cfg.db_path.parent / "app.log"
    logging.basicConfig(filename=str(log_path), level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import uvicorn

    from .core import Core
    from .web.app import create_local_app

    core = Core(cfg)
    server = uvicorn.Server(uvicorn.Config(create_local_app(core), host=host, port=port,
                                           log_config=None, access_log=False))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    _wait_ready(host, port)

    try:
        import webview  # own desktop window (Edge WebView2); falls back to the browser if unavailable
    except ImportError:
        webview = None
    if webview is not None:
        try:
            _run_window(webview, core, url)
            return
        except Exception:
            logging.exception("window failed, falling back to browser")
    webbrowser.open(url)
    try:
        t.join()
    except KeyboardInterrupt:
        pass


class _WindowApi:
    """Methods callable from the UI as `pywebview.api.*` (native dialogs)."""

    def __init__(self):
        self._window = None

    def pick_folder(self) -> str:
        import webview
        res = self._window.create_file_dialog(webview.FOLDER_DIALOG) if self._window else None
        return res[0] if res else ""


def _run_window(webview, core, url: str) -> None:
    import os
    api = _WindowApi()
    window = webview.create_window("Kho tài liệu cục bộ", url, js_api=api, width=1180, height=780,
                                   min_size=(980, 640), background_color="#0b1020", text_select=True)
    api._window = window  # underscore: pywebview must not introspect the window object

    def on_closed():  # closing the window quits the app; finished OCR pages are already saved
        core.indexer.cancel()
        core.ocr.cancel()
        os._exit(0)

    window.events.closed += on_closed
    webview.start()


def _wait_ready(host: str, port: int) -> None:
    for _ in range(100):
        if _port_in_use(host, port):
            return
        time.sleep(0.1)


if __name__ == "__main__":
    main()
