"""配置加载"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class Config:
    def __init__(self, data: dict, root: Path):
        self.data = data
        self.root = root

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def path(self, key: str) -> Path:
        return (self.root / self.data["paths"][key]).resolve()

    def abs_path(self, rel: str) -> Path:
        return (self.root / rel).resolve()


def load_config(path: str | os.PathLike | None = None) -> Config:
    root = Path(__file__).resolve().parent.parent
    # 统一在配置加载时注入 .env（嵌入/LLM/judge 各后端都需要）
    try:
        from core.env import load_dotenv
        load_dotenv()
    except Exception:
        pass
    cfg_path = Path(path) if path else root / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Config(data, root)
