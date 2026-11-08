"""Model asset management: manifest, prepare (download), verify, import.

Models are versioned, checksummed dependencies stored under MODEL_ROOT. Nothing here is
called implicitly at runtime: downloading only happens through `prepare_models`.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config


class ModelError(Exception):
    """Missing/corrupt model asset. The message always says how to fix it."""


@dataclass
class ModelSpec:
    id: str
    repo: str
    revision: str  # pinned commit sha, never a moving tag
    path: str  # relative to MODEL_ROOT
    format: str
    quantization: str
    license: str
    files: list[str]  # files inside the HF repo to fetch
    config_key: str  # key in config.yaml -> models.<key>
    optional: bool = False
    notes: str = ""

    @property
    def source(self) -> str:
        return f"https://huggingface.co/{self.repo}/tree/{self.revision}"


REGISTRY: dict[str, ModelSpec] = {
    "embedding-multilingual-e5-small": ModelSpec(
        id="embedding-multilingual-e5-small",
        repo="intfloat/multilingual-e5-small",
        revision="614241f622f53c4eeff9890bdc4f31cfecc418b3",
        path="embeddings/multilingual-e5-small-onnx-int8",
        format="onnx",
        quantization="int8",
        license="MIT",
        files=[
            "onnx/model_qint8_avx512_vnni.onnx",
            "onnx/tokenizer.json",
            "onnx/tokenizer_config.json",
            "onnx/special_tokens_map.json",
            "onnx/config.json",
        ],
        config_key="embedding_path",
    ),
}


# ------------------------------------------------------------------ hashing
def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _file_list(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*") if p.is_file())


def hash_asset(path: Path) -> tuple[str, int, list[dict]]:
    """Return (sha256, total_size, per_file) for a file or a directory model."""
    files = _file_list(path)
    per_file = []
    total = 0
    for f in files:
        rel = f.name if path.is_file() else f.relative_to(path).as_posix()
        size = f.stat().st_size
        total += size
        per_file.append({"path": rel, "size": size, "sha256": sha256_file(f)})
    if path.is_file():
        return per_file[0]["sha256"], total, per_file
    combined = hashlib.sha256()
    for e in per_file:
        combined.update(f"{e['path']}:{e['sha256']}\n".encode())
    return combined.hexdigest(), total, per_file


# ----------------------------------------------------------------- manifest
def load_manifest(cfg: Config) -> dict:
    p = cfg.manifest_path
    if not p.exists():
        return {"schema_version": 1, "models": []}
    return json.loads(p.read_text(encoding="utf-8"))


def save_manifest(cfg: Config, manifest: dict) -> None:
    cfg.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _upsert(manifest: dict, entry: dict) -> None:
    manifest["models"] = [m for m in manifest["models"] if m["id"] != entry["id"]] + [entry]


# ------------------------------------------------------------------ prepare
def prepare_models(
    cfg: Config,
    ids: list[str] | None = None,
    progress: Callable[[str], None] = print,
) -> list[str]:
    """Download pinned model assets into MODEL_ROOT and record checksums in MANIFEST.json.

    Resumable (huggingface_hub resumes partial downloads). This is an explicit install
    step - the app never downloads models while running.
    """
    from huggingface_hub import HfApi, hf_hub_download

    ids = ids or [k for k, s in REGISTRY.items() if not s.optional]
    root = cfg.model_root
    root.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    done: list[str] = []
    for mid in ids:
        spec = REGISTRY.get(mid)
        if spec is None:
            raise ModelError(f"Model không có trong registry: {mid}. Các model hợp lệ: {', '.join(REGISTRY)}")
        target = root / spec.path
        info = api.model_info(spec.repo, revision=spec.revision, files_metadata=True)
        sizes = {s.rfilename: (s.size or 0) for s in info.siblings}
        need = sum(sizes.get(f, 0) for f in spec.files)
        free = shutil.disk_usage(root).free
        if need * 1.2 > free:
            raise ModelError(
                f"Không đủ dung lượng đĩa cho {mid}: cần ~{need / 1e9:.1f} GB, còn trống {free / 1e9:.1f} GB. "
                "Giải phóng dung lượng hoặc đặt MODEL_ROOT sang ổ khác."
            )
        progress(f"[{mid}] revision {spec.revision[:10]}, {need / 1e6:.0f} MB")
        if spec.format == "gguf":
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = hf_hub_download(spec.repo, spec.files[0], revision=spec.revision,
                                  local_dir=str(root / "_downloads" / spec.id))
            shutil.move(tmp, target)
        else:
            target.mkdir(parents=True, exist_ok=True)
            for f in spec.files:
                progress(f"  - {f}")
                hf_hub_download(spec.repo, f, revision=spec.revision, local_dir=str(target))
        digest, size, per_file = hash_asset(target)
        manifest = load_manifest(cfg)
        _upsert(manifest, {
            "id": spec.id,
            "revision": spec.revision,
            "path": spec.path,
            "format": spec.format,
            "quantization": spec.quantization,
            "size_bytes": size,
            "sha256": digest,
            "files": per_file if target.is_dir() else None,
            "source": spec.source,
            "license": spec.license,
            "prepared_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        save_manifest(cfg, manifest)
        shutil.rmtree(root / "_downloads", ignore_errors=True)
        progress(f"[{mid}] OK sha256={digest[:16]}... ({size / 1e6:.0f} MB)")
        done.append(mid)
    return done


# ------------------------------------------------------------------- verify
@dataclass
class VerifyResult:
    id: str
    ok: bool
    problem: str = ""
    fix: str = ""


def _stat_key(path: Path) -> str:
    return ";".join(f"{f.name}:{f.stat().st_size}:{f.stat().st_mtime_ns}" for f in _file_list(path))


def verify_model(cfg: Config, entry: dict, full: bool = False) -> VerifyResult:
    mid = entry["id"]
    spec = REGISTRY.get(mid)
    path = cfg.model_root / entry["path"]
    fix = f"Chạy: python -m localrag prepare-models {mid}  (hoặc chép asset đã kiểm tra vào {path})"
    if spec and spec.revision != entry.get("revision"):
        return VerifyResult(mid, False, f"Sai revision: manifest={entry.get('revision')} != yêu cầu={spec.revision}", fix)
    if not path.exists():
        return VerifyResult(mid, False, f"Thiếu file/thư mục model: {path}", fix)
    cache_file = cfg.model_root / ".verified.json"
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    key = f"{entry['sha256']}|{_stat_key(path)}"
    if not full and cache.get(mid) == key:
        return VerifyResult(mid, True)
    digest, _, _ = hash_asset(path)
    if digest != entry["sha256"]:
        return VerifyResult(mid, False, f"Sai checksum SHA-256 (nhận {digest[:16]}..., manifest {entry['sha256'][:16]}...)", fix)
    cache[mid] = key
    cache_file.write_text(json.dumps(cache))
    return VerifyResult(mid, True)


def verify_models(cfg: Config, ids: list[str] | None = None, full: bool = False) -> list[VerifyResult]:
    manifest = load_manifest(cfg)
    entries = {m["id"]: m for m in manifest["models"]}
    results = []
    wanted = ids or [k for k, s in REGISTRY.items() if not s.optional]
    for mid in wanted:
        if mid not in entries:
            results.append(VerifyResult(mid, False, "Chưa có trong MANIFEST.json",
                                        f"Chạy: python -m localrag prepare-models {mid}"))
            continue
        results.append(verify_model(cfg, entries[mid], full=full))
    return results


def require_model(cfg: Config, mid: str) -> Path:
    """Verify one model and return its path; raises ModelError with a fix hint."""
    res = verify_models(cfg, [mid])[0]
    if not res.ok:
        raise ModelError(f"Model '{mid}' không sử dụng được: {res.problem}. {res.fix}")
    entry = next(m for m in load_manifest(cfg)["models"] if m["id"] == mid)
    return cfg.model_root / entry["path"]
