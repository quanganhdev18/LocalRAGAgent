"""Explicit, user-triggered setup of OCR assets and models (used by the UI and scripts/).

Nothing here runs implicitly: downloads only start when the user presses a button / runs a script.
All downloads are pinned by URL and SHA-256 and verified before use.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import Config

TESSDATA_COMMIT = "87416418657359cb625c412a48b6e1d6d41c29bd"  # tessdata_fast (Apache-2.0)
TESSDATA = {
    "vie": ("79df64caf7bcfb2a27df5042ecb6121e196eada34da774956995747636d5bfa1"),
    "eng": ("7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"),
}
INSTALLER_URL = ("https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/"
                 "tesseract-ocr-w64-setup-5.4.0.20240606.exe")
INSTALLER_SHA = "c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def user_tessdata_dir(cfg: Config) -> Path:
    """Language data kept inside the app folder (no admin rights needed)."""
    return cfg.root / "runtime" / "tessdata"


def download(url: str, want_sha: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and sha256(dest) == want_sha:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    last: Exception | None = None
    for _ in range(3):  # transient gateway errors happen
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LocalRAG-setup/0.1"})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            break
        except Exception as e:  # noqa: BLE001
            last = e
    else:
        raise RuntimeError(f"Không tải được {url}: {last}")
    if sha256(tmp) != want_sha:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 không khớp cho {dest.name}; đã hủy để đảm bảo an toàn.")
    os.replace(tmp, dest)
    return dest


def download_tessdata(cfg: Config, progress=print) -> None:
    for lang, sha in TESSDATA.items():
        progress(f"Tải dữ liệu OCR '{lang}'…")
        download(f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{TESSDATA_COMMIT}/{lang}.traineddata",
                 sha, user_tessdata_dir(cfg) / f"{lang}.traineddata")


def download_installer(cfg: Config, progress=print) -> Path:
    progress("Tải bộ cài Tesseract…")
    return download(INSTALLER_URL, INSTALLER_SHA, cfg.root / "runtime" / "downloads" / "tesseract-setup.exe")


def ocr_status(cfg: Config) -> dict:
    from .ocr import find_tesseract
    exe = find_tesseract(cfg)
    langs = cfg.get("ocr", "languages", default=["vie", "eng"])
    have = {l: any((d / f"{l}.traineddata").is_file() for d in _tessdata_candidates(cfg, exe)) for l in langs}
    return {"engine_found": bool(exe), "engine_path": str(exe) if exe else None,
            "languages": have, "ready": bool(exe) and all(have.values())}


def _tessdata_candidates(cfg: Config, exe: Path | None) -> list[Path]:
    out = [user_tessdata_dir(cfg)]
    if exe:
        out.append(exe.parent / "tessdata")
    return out


@dataclass
class JobState:
    name: str = ""
    running: bool = False
    message: str = ""
    error: str = ""
    done: bool = False


class SetupJobs:
    """One background job at a time (model download / OCR data / installer)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.state = JobState()
        self._lock = threading.Lock()

    def start(self, name: str, fn) -> bool:
        with self._lock:
            if self.state.running:
                return False
            self.state = JobState(name=name, running=True, message="Đang bắt đầu…")
        threading.Thread(target=self._run, args=(fn,), daemon=True).start()
        return True

    def _run(self, fn) -> None:
        try:
            fn(self._progress)
            self.state.done = True
            self.state.message = "Hoàn tất."
        except Exception as e:  # report, never swallow
            self.state.error = f"{type(e).__name__}: {e}"
        finally:
            self.state.running = False

    def _progress(self, msg: str) -> None:
        self.state.message = str(msg)
