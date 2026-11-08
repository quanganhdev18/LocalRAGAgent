"""Configuration loading. Defaults live in config.yaml; env vars may override MODEL_ROOT."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULTS: dict[str, Any] = {}


def _deep_merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, data: dict[str, Any], root: Path):
        self.data = data
        self.root = root

    def __getitem__(self, key: str):
        return self.data[key]

    def get(self, *keys, default=None):
        cur: Any = self.data
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    def path(self, *keys) -> Path:
        """Resolve a config path relative to the project root."""
        raw = self.get(*keys)
        p = Path(raw)
        return p if p.is_absolute() else (self.root / p).resolve()

    @property
    def model_root(self) -> Path:
        env = os.environ.get("MODEL_ROOT")
        if env:
            return Path(env).resolve()
        return self.path("models", "root")

    def model_path(self, key: str) -> Path:
        """Model asset path, re-based on MODEL_ROOT when it is overridden."""
        p = self.path("models", key)
        if os.environ.get("MODEL_ROOT"):
            default_root = self.path("models", "root")
            try:
                return self.model_root / p.relative_to(default_root)
            except ValueError:
                return p
        return p

    @property
    def manifest_path(self) -> Path:
        return self.model_root / "MANIFEST.json"

    @property
    def db_path(self) -> Path:
        d = self.path("paths", "data_dir")
        d.mkdir(parents=True, exist_ok=True)
        return d / "localrag.sqlite"


def load_config(path: str | os.PathLike | None = None, root: Path | None = None) -> Config:
    root = root or PROJECT_ROOT
    env = os.environ.get("LOCALRAG_CONFIG")  # alternate config (e.g. demos/tests)
    cfg_path = Path(path) if path else (Path(env) if env else root / "config.yaml")
    data: dict[str, Any] = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return Config(data, root)
