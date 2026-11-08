"""Local embedding provider (multilingual-e5-small, ONNX INT8). Lazy-loaded singleton."""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from .config import Config
from .models import require_model


class Embedder:
    """Encodes queries ('query: ') and passages ('passage: ') into L2-normalised vectors."""

    MODEL_ID = "embedding-multilingual-e5-small"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dim = int(cfg.get("index", "vector_dimensions", default=384))
        self.batch_size = int(cfg.get("index", "batch_size", default=16))
        self.max_len = int(cfg.get("index", "max_seq_length", default=512))
        self.model_name = cfg.get("index", "embedding_model", default="intfloat/multilingual-e5-small")
        self._session = None
        self._tokenizer = None
        self._lock = threading.Lock()

    # lazy load: model is verified (checksum) and loaded exactly once per process
    def _load(self) -> None:
        if self._session is not None:
            return
        with self._lock:
            if self._session is not None:
                return
            import onnxruntime as ort
            from tokenizers import Tokenizer

            model_dir = Path(require_model(self.cfg, self.MODEL_ID))
            onnx_files = sorted(model_dir.rglob("*.onnx"))
            tok_files = sorted(model_dir.rglob("tokenizer.json"))
            if not onnx_files or not tok_files:
                from .models import ModelError
                raise ModelError(f"Thư mục model embedding thiếu .onnx/tokenizer.json: {model_dir}. "
                                 "Chạy: python -m localrag prepare-models")
            tok = Tokenizer.from_file(str(tok_files[0]))
            tok.enable_truncation(max_length=self.max_len)
            tok.enable_padding(pad_id=tok.token_to_id("<pad>") or 1, pad_token="<pad>")
            so = ort.SessionOptions()
            so.intra_op_num_threads = max(1, (__import__("os").cpu_count() or 4) // 2)
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(str(onnx_files[0]), so, providers=["CPUExecutionProvider"])
            self._input_names = {i.name for i in self._session.get_inputs()}
            self._tokenizer = tok

    def unload(self) -> None:
        with self._lock:
            self._session = None
            self._tokenizer = None

    def _encode(self, texts: list[str]) -> np.ndarray:
        self._load()
        enc = self._tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = self._session.run(None, {k: v for k, v in feeds.items() if k in self._input_names})[0]
        m = mask[..., None].astype(np.float32)
        pooled = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)  # mean pooling
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return (pooled / np.clip(norms, 1e-12, None)).astype(np.float32)

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), self.batch_size):
            out.append(self._encode([f"passage: {t}" for t in texts[i:i + self.batch_size]]))
        return np.vstack(out) if out else np.zeros((0, self.dim), dtype=np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        return self._encode([f"query: {text}"])[0]
